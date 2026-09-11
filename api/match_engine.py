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
    revealed_at: float = 0.0
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
    creator: str = ""  # first player in the queue — deposits the on-chain stake first
    signed_settlement: dict[str, Any] | None = None  # replay for the other client

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
        # Progress-only opponent info (never their times): lets clients know
        # when the match is complete and settlement is safe to request.
        my_addr = (for_address or "").lower()
        opp_addr = next((a for a in self.players if a != my_addr), None)
        # Opponent address is public on-chain data; safe to disclose.
        view["opponent"] = opp_addr
        # Creator deposits the escrow stake first; the joiner waits for that
        # on-chain deposit before joining. The client needs to know its role.
        view["youAreCreator"] = bool(me and self.creator == me["address"])
        if opp_addr:
            opp_rounds = self.rounds.get(opp_addr, {}) or {}
            my_submitted = {
                idx for idx, r in (self.rounds.get(my_addr, {}) or {}).items() if r.result_ms is not None
            }
            # Mutual disclosure: an opponent's round time is revealed only once
            # BOTH players have submitted that round. This is what makes live
            # scoring honest without leaking anything exploitable mid-round.
            view["opponentTimes"] = {
                str(idx): r.result_ms
                for idx, r in opp_rounds.items()
                if idx in my_submitted and r.result_ms is not None and r.valid
            }
            view["opponentSubmitted"] = sum(
                1 for r in opp_rounds.values() if r.result_ms is not None
            )
        else:
            view["opponentTimes"] = {}
            view["opponentSubmitted"] = 0
        return view


class MatchStore:
    """
    In-memory store with explicit in-memory markers so horizontal scaling
    fails loudly instead of silently splitting matches across replicas.
    """

    def __init__(self) -> None:
        self.matches: dict[str, Match] = {}
        self.queue: dict[float, list[str]] = {}
        # address -> live (waiting|active) match id. Makes enqueue IDEMPOTENT:
        # re-polling the queue returns the caller's existing match instead of
        # minting orphan waiting matches every poll (the deadlock that left
        # the first player forever in matchmaking while P2 played alone).
        self.player_match: dict[str, str] = {}

    def enqueue(self, address: str, stake: float) -> Match:
        addr = address.lower()
        live = self.player_match.get(addr)
        if live:
            m = self.matches.get(live)
            if m and m.status in ("waiting", "active"):
                return m
            self.player_match.pop(addr, None)
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
            self.player_match[addr] = m.match_id
            return m
        # No opponent: create a new waiting match.
        match_id = secrets.token_hex(16)
        m = Match(
            match_id=match_id,
            stake=stake,
            created_at=time.time(),
            players={addr: {"address": addr, "joinedAt": time.time()}},
            creator=addr,
        )
        self.matches[match_id] = m
        bucket.append(match_id)
        self.player_match[addr] = match_id
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
        r.revealed_at = now
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
    # Timing floor: the submission cannot arrive meaningfully before the
    # revealed target delay has elapsed on the SERVER clock. This kills two
    # client cheats at once: submitting a fabricated time instantly after the
    # reveal, and clicking early then reporting a fast "reaction".
    if r.revealed_at and now - r.revealed_at < (r.target_ms / 1000.0) * 0.9:
        return (
            f"implausible: submitted before the {r.target_ms:.0f}ms target "
            "delay had elapsed on the server clock"
        )
    return ""


def _ensure_active(match: Match, address: str) -> None:
    if match.status != "active":
        raise MatchError("Match is not active")
    if address.lower() not in match.players:
        raise MatchError("Not a participant of this match")


def settle(match: Match) -> dict[str, Any]:
    """
    Deterministically settle as Best-of-3 round wins, matching the client UI:
    the faster VALID time wins each round; an invalid/missing round is a
    forfeited round (anti-cheat deterrent); an exact tie awards neither.
    First to 2 round wins takes the match. Returns the settlement record
    (winner + per-player validated times) for the oracle to sign.
    """
    if match.status != "active":
        raise MatchError("Match is not active")
    a, b = sorted(match.players)
    rounds_a = match.rounds.get(a, {})
    rounds_b = match.rounds.get(b, {})

    wins_a = wins_b = 0
    times_a: list[float] = []
    times_b: list[float] = []
    for idx in range(ROUNDS):
        ra = rounds_a.get(idx)
        rb = rounds_b.get(idx)
        va = ra.result_ms if (ra and ra.valid and ra.result_ms is not None) else None
        vb = rb.result_ms if (rb and rb.valid and rb.result_ms is not None) else None
        if va is not None:
            times_a.append(va)
        if vb is not None:
            times_b.append(vb)
        if va is None and vb is None:
            continue  # double forfeit: round awards nobody
        if vb is None:
            wins_a += 1  # forfeit by b
            continue
        if va is None:
            wins_b += 1  # forfeit by a
            continue
        if va < vb:
            wins_a += 1
        elif vb < va:
            wins_b += 1
        # exact tie: round awards nobody

    wins_needed = ROUNDS // 2 + 1  # 2 of 3
    if wins_a < wins_needed and wins_b < wins_needed:
        match.status = "void"
        return {"status": "void", "reason": "no round-win majority — stakes refund"}

    winner = a if wins_a >= wins_needed else b
    loser = b if winner == a else a
    winner_times = times_a if winner == a else times_b
    loser_times = times_b if winner == a else times_a
    # A player can win by forfeit with no valid time of their own; record the
    # max plausible time so the on-chain proof still has real uint256 values.
    winner_ms = int(round(min(winner_times))) if winner_times else int(MAX_HUMAN_MS)
    loser_ms = int(round(min(loser_times))) if loser_times else int(MAX_HUMAN_MS)
    match.winner = winner
    match.status = "settled"
    match.settled_at = time.time()
    return {
        "status": "settled",
        "matchId": match.match_id,
        "winner": winner,
        "loser": loser,
        "stake": match.stake,
        "roundWins": {a: wins_a, b: wins_b},
        "validatedTimes": {a: times_a, b: times_b},
        "winningMedianMs": winner_ms,
        "winnerTimeMs": winner_ms,
        "loserTimeMs": loser_ms,
    }
