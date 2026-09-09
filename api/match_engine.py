"""
PULSAR P1.12/P1.13 — Authoritative match engine.

Round protocol (serverless-compatible, polling based):

  1. POST /api/queue          matchmaking by stake -> matchId
  2. POST /api/round/commit   client pre-commits an intent hash BEFORE seeing
                              the round target (binds the client to one
                              attempt per round; prevents re-rolling results)
  3. POST /api/round/target   server reveals the round target delay (signed,
                              unguessable until committed)
  4. POST /api/round/result   client submits its measured reaction time;
                              server validates plausibility and stores it
  5. server settles: best validated time over 3 rounds wins; settlement
     record carries the referee signature for on-chain settlement.

The client measures its own reaction time locally (millisecond precision
requires client clocks), but the server refuses impossible values via
plausibility gates and binds each attempt to a per-round commit.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field, asdict
from typing import Any

ROUNDS = 3
MIN_HUMAN_MS = 90.0            # below this is not humanly plausible
MAX_HUMAN_MS = 1200.0          # above this is a disconnect / not a serious attempt
ROUND_EXPIRY_SECONDS = 60
MATCH_EXPIRY_SECONDS = 600     # aligns with MATCH_TIMEOUT (10 minutes) on-chain

# Per-round intent-binding: commit must precede target reveal.
COMMIT_WINDOW_SECONDS = 30


class MatchError(Exception):
    """Raised on invalid match state transitions."""


@dataclass
class Round:
    index: int
    commit_hash: str = ""
    commit_at: float = 0.0
    target_hash: str = ""
    target_salt: str = ""
    target_ms: float = 0.0
    revealed: bool = False
    result_ms: float | None = None
    submitted_at: float = 0.0
    valid: bool = False
    reject_reason: str = ""


@dataclass
class Match:
    match_id: str
    stake: float
    created_at: float
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    rounds: dict[int, dict[str, Round]] = field(default_factory=dict)
    status: str = "waiting"  # waiting | active | settled | void
    winner: str = ""
    settled_at: float = 0.0

    def public_view(self, for_address: str | None = None) -> dict[str, Any]:
        """Round data is per-player secret; only summaries are public."""
        me = self.players.get((for_address or "").lower())
        view = {
            "matchId": self.match_id,
            "stake": self.stake,
            "status": self.status,
            "winner": self.winner,
            "createdAt": self.created_at,
            "rounds": ROUNDS,
            "me": me.get("address") if me else None,
            "opponentJoined": len(self.players) > 1,
        }
        my_rounds = []
        if me:
            mine = self.rounds.get(me["address"], {})
            for idx in range(ROUNDS):
                r = mine.get(idx)
                my_rounds.append(
                    {
                        "index": idx,
                        "committed": bool(r and r.commit_hash),
                        "targetRevealed": bool(r and r.revealed),
                        "submitted": r.result_ms is not None if r else False,
                        "valid": r.valid if r else False,
                        "rejectReason": r.reject_reason if r else "",
                    }
                )
        view["myRounds"] = my_rounds
        return view


class MatchStore:
    """
    In-memory store with explicit in-memory markers so horizontal scaling
    fails loudly instead of silently splitting matches across replicas.
    """

    def __init__(self) -> None:
        self.matches: dict[str, Match] = {}
        self.queue: dict[float, list[str]] = {}

    def enqueue(self, address: str, stake: float) -> Match:
        addr = address.lower()
        bucket = self.queue.setdefault(stake, [])
        for other in list(bucket):
            m = self.matches.get(other)
            if m is None or m.status != "waiting":
                bucket.remove(other)
                continue
            if addr in m.players:
                bucket.remove(other)
                continue
            # Found an opponent: activate the match.
            m.players[addr] = {"address": addr, "joinedAt": time.time()}
            m.status = "active"
            bucket.remove(other)
            return m
        # No opponent: create a new waiting match.
        match_id = secrets.token_hex(16)
        m = Match(
            match_id=match_id,
            stake=stake,
            created_at=time.time(),
            players={addr: {"address": addr, "joinedAt": time.time()}},
        )
        self.matches[match_id] = m
        bucket.append(match_id)
        return m

    def get(self, match_id: str) -> Match:
        m = self.matches.get(match_id)
        if m is None:
            raise MatchError("Match not found")
        return m

    def sweep_expired(self) -> None:
        now = time.time()
        for mid in list(self.matches):
            m = self.matches[mid]
            if m.status in ("waiting", "active") and now - m.created_at > MATCH_EXPIRY_SECONDS:
                m.status = "void"
        for stake, bucket in list(self.queue.items()):
            self.queue[stake] = [
                mid for mid in bucket
                if mid in self.matches and self.matches[mid].status == "waiting"
            ]


def commit_intent(match: Match, address: str, round_index: int, intent_hash: str) -> None:
    """Player binds this round to one intent hash before seeing the target."""
    _ensure_active(match, address)
    if round_index not in range(ROUNDS):
        raise MatchError("Invalid round")
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index) or Round(index=round_index)
    now = time.time()
    if r.commit_hash and now - r.commit_at < COMMIT_WINDOW_SECONDS:
        raise MatchError("Round already committed")
    r.commit_hash = intent_hash.lower()
    r.commit_at = now
    rounds[round_index] = r


def reveal_target(match: Match, address: str, round_index: int) -> dict[str, Any]:
    """
    Reveal the round target only after a commit exists, and return it together
    with an HMAC proof the client can display but cannot forge or predict
    before committing.
    """
    _ensure_active(match, address)
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index)
    if r is None or not r.commit_hash:
        raise MatchError("Commit before reveal required")
    now = time.time()
    if now - r.commit_at > COMMIT_WINDOW_SECONDS:
        raise MatchError("Commit expired, re-commit the round")
    if not r.revealed:
        r.target_salt = secrets.token_hex(16)
        r.target_ms = float(secrets.randbelow(1500) + 1200)  # 1200-2700ms delay
        r.target_hash = hmac.new(
            r.target_salt.encode(), f"{r.target_ms:.0f}".encode(), hashlib.sha256
        ).hexdigest()
        r.revealed = True
    proof = hmac.new(
        r.target_salt.encode(), f"reveal|{r.target_ms:.0f}".encode(), hashlib.sha256
    ).hexdigest()
    return {"targetMs": r.target_ms, "proof": proof, "roundIndex": round_index}


def submit_result(match: Match, address: str, round_index: int, measured_ms: float) -> dict[str, Any]:
    """Validate one submitted time and store it for settlement."""
    _ensure_active(match, address)
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index)
    if r is None or not r.revealed:
        raise MatchError("Round target not revealed")
    if r.result_ms is not None:
        raise MatchError("Result already submitted")
    now = time.time()
    reason = _validate_plausibility(match, r, measured_ms, now)
    r.result_ms = measured_ms
    r.submitted_at = now
    if reason:
        r.valid = False
        r.reject_reason = reason
    else:
        r.valid = True
    return {"accepted": r.valid, "reason": r.reject_reason}


def _validate_plausibility(match: Match, r: Round, measured_ms: float, now: float) -> str:
    if measured_ms < MIN_HUMAN_MS:
        return f"implausible: {measured_ms}ms is below human minimum"
    if measured_ms > MAX_HUMAN_MS:
        return f"implausible: {measured_ms}ms exceeds maximum plausible reaction"
    return ""


def _ensure_active(match: Match, address: str) -> None:
    if match.status != "active":
        raise MatchError("Match is not active")
    if address.lower() not in match.players:
        raise MatchError("Not a participant of this match")


def settle(match: Match) -> dict[str, Any]:
    """
    Deterministically settle from validated rounds. Returns the settlement
    record (winner, per-player validated medians) for the oracle to sign.
    """
    if match.status != "active":
        raise MatchError("Match is not active")
    scores: dict[str, list[float]] = {}
    for addr in match.players:
        mine = match.rounds.get(addr, {})
        valid_times = [r.result_ms for i, r in sorted(mine.items()) if r.valid and r.result_ms is not None]
        scores[addr] = valid_times

    expected = ROUNDS
    complete = {a: t for a, t in scores.items() if len(t) == expected}
    if len(complete) < 2:
        # Not enough validated rounds: void the match (stakes refund on-chain).
        match.status = "void"
        return {"status": "void", "reason": "insufficient validated rounds"}

    a, b = sorted(complete.keys())
    median_a = _median(complete[a])
    median_of_b = _median(complete[b])
    if median_a == median_of_b:
        match.status = "void"
        return {"status": "void", "reason": "exact tie — stakes refund"}
    winner = a if median_a < median_of_b else b
    loser = b if winner == a else a
    winner_ms = int(round(median_a if winner == a else median_of_b))
    loser_ms = int(round(median_of_b if winner == a else median_a))
    match.winner = winner
    match.status = "settled"
    match.settled_at = time.time()
    return {
        "status": "settled",
        "matchId": match.match_id,
        "winner": winner,
        "loser": loser,
        "stake": match.stake,
        "validatedTimes": {a: complete[a], b: complete[b]},
        "winningMedianMs": winner_ms,
        "winnerTimeMs": winner_ms,
        "loserTimeMs": loser_ms,
    }


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
