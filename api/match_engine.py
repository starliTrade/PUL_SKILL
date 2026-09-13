"""
PULSAR P1.12/P1.13 — Authoritative match engine.

Round protocol (serverless-compatible, polling based):

  1. POST /api/queue          matchmaking by stake -> matchId
  2. POST /api/round/commit   client pre-commits an intent hash BEFORE seeing
                              the round target (binds the client to one
                              attempt per round; prevents re-rolling results)
  3. POST /api/round/target   server reveals the round target delay together
                              with a per-player result proof
  4. POST /api/round/result   client submits its measured reaction time;
                              the server validates plausibility AND the
                              per-player result proof, then stores the time
                              bound to that round's commit
  5. server settles: best validated time over 3 rounds wins; settlement
     record carries the referee signature for on-chain settlement.

Anti-cheat model (audit #2):
- A submitted result is only accepted when it carries the unforgeable
  result proof issued to THAT player for THAT round after their commit.
  Replayed, cross-player, guessed, or pre-generated proofs are rejected.
- Settlement requires the match to be genuinely complete: either both
  players finished all rounds, or a participant requested settlement after
  the server's own match deadline — never "whenever a player feels like it".
- A forfeit winner keeps at least one engine-validated time, so the oracle
  can always sign the settlement the contract can verify. (The oracle
  refuses empty time arrays; an unsigned settled match is unrecoverable
  and would lock the stake forever.)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

ROUNDS = 3
MIN_HUMAN_MS = 105.0           # below this is not humanly plausible — MUST match
                               # the client floor (antiCheat.MIN_HUMAN_REACTION_MS = 105)
                               # so an attacker gains no threshold advantage
MAX_HUMAN_MS = 1200.0          # above this is a disconnect / not a serious attempt
MAX_NETWORK_SLACK_MS = 250.0   # reveal-response + result-request transit budget
CLAIM_CLOCK_SLACK_MS = 50.0    # client duration cannot exceed server duration
ROUND_EXPIRY_SECONDS = 60
MATCH_EXPIRY_SECONDS = 600     # aligns with the on-chain refund horizon (30 min
                               # starts at deposit; the server gives up earlier)
COMMIT_WINDOW_SECONDS = 30     # per-round intent-binding window

# P0-fix (audit #2): after this long past activation, a participant may settle
# an unfinished match — missing rounds become forfeits. Before that, settle()
# refuses so nobody can race ahead of their opponent (or void a fresh match).
MATCH_SETTLE_GRACE_SECONDS = 480  # 8 minutes after activation

# Secret used to MAC result proofs. Rotating it invalidates in-flight proofs
# (they simply fail validation) — safe to restart.
_PROOF_SECRET = secrets.token_bytes(32)


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
    result_proof: str = ""  # per-player MAC binding result submission to this round


@dataclass
class Match:
    match_id: str
    stake: float
    created_at: float
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    rounds: dict[str, dict[int, Round]] = field(default_factory=dict)
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


def _result_proof(match_id: str, address: str, round_index: int, commit_hash: str, target_ms: int) -> str:
    """Unforgeable per-player round proof: unguessable before the commit +
    reveal, and unusable by any other player or round."""
    payload = f"{match_id}|{address}|{round_index}|{commit_hash}|{target_ms}".encode()
    return hmac.new(_PROOF_SECRET, payload, hashlib.sha256).hexdigest()


def commit_intent(match: Match, address: str, round_index: int, intent_hash: str) -> None:
    """Player binds this round to one intent hash before seeing the target."""
    _ensure_active(match, address)
    if round_index not in range(ROUNDS):
        raise MatchError("Invalid round")
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index) or Round(index=round_index)
    now = time.time()
    if r.commit_hash and now - r.commit_at < COMMIT_WINDOW_SECONDS:
        if r.commit_hash != intent_hash.lower():
            raise MatchError("Round already committed")
        # Idempotent retry of the SAME intent (e.g. a dropped HTTP response on
        # the first commit). Returns without error so a rejected submission can
        # be retried — the target/proof stay bound to this one commit.
        return
    r.commit_hash = intent_hash.lower()
    r.commit_at = now
    rounds[round_index] = r


def reveal_target(match: Match, address: str, round_index: int) -> dict[str, Any]:
    """
    Reveal the round target only after a commit exists, and return it together
    with the per-player result proof the client must present when submitting.
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
        # P0-fix (audit #2): bind THIS player's result submission to THIS
        # round's commit + revealed target. Issued here so the client cannot
        # pre-generate it and no other player can reuse it.
        r.result_proof = _result_proof(
            match.match_id, address.lower(), round_index, r.commit_hash, int(r.target_ms)
        )
    return {
        "targetMs": r.target_ms,
        "proof": r.target_hash,
        "resultProof": r.result_proof,
        "roundIndex": round_index,
    }


def submit_result(
    match: Match,
    address: str,
    round_index: int,
    measured_ms: float,
    result_proof: str = "",
) -> dict[str, Any]:
    """
    Validate one submitted time and store it for settlement. The submission
    MUST carry the per-player result proof from reveal_target — a commit that
    was never followed by an honest reveal cannot produce a valid result.
    """
    _ensure_active(match, address)
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index)
    if r is None or not r.revealed:
        raise MatchError("Round target not revealed")
    if r.result_ms is not None:
        raise MatchError("Result already submitted")
    # P0-fix (audit #2): the commit is no longer decorative. A result is only
    # stored when it carries the proof bound to this player's commit+reveal.
    if not result_proof or not hmac.compare_digest(result_proof, r.result_proof):
        raise MatchError("Invalid result proof for this round")
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
    # Timing-consistency gate: compare the claim to the complete interval seen
    # by the server, not merely to a minimum delay. Server-observed reaction is
    # expected to exceed the client measurement only by network transit. A
    # player who waits and then submits a fabricated 105ms therefore fails.
    if r.revealed_at:
        elapsed_ms = (now - r.revealed_at) * 1000.0
        if elapsed_ms < r.target_ms:
            return (
                "implausible: submitted before the target delay could have "
                "elapsed on the server clock"
            )
        observed_reaction_ms = elapsed_ms - r.target_ms
        if observed_reaction_ms - measured_ms > MAX_NETWORK_SLACK_MS:
            return "implausible: claimed reaction is faster than server-observed timing"
        if measured_ms - observed_reaction_ms > CLAIM_CLOCK_SLACK_MS:
            return "implausible: claimed reaction exceeds server-observed timing"
        if observed_reaction_ms > ROUND_EXPIRY_SECONDS * 1000.0:
            return "round expired before result submission"
    return ""


def _ensure_active(match: Match, address: str) -> None:
    if match.status != "active":
        raise MatchError("Match is not active")
    if address.lower() not in match.players:
        raise MatchError("Not a participant of this match")


def _round_winner(mine: dict[int, Round], theirs: dict[int, Round], idx: int) -> str:
    """'a' (mine wins) | 'b' (theirs wins) | '' (undecided) for one round."""
    ra = mine.get(idx)
    rb = theirs.get(idx)
    va = ra.result_ms if (ra and ra.valid and ra.result_ms is not None) else None
    vb = rb.result_ms if (rb and rb.valid and rb.result_ms is not None) else None
    if va is None and vb is None:
        return ""
    if vb is None:
        return "a"
    if va is None:
        return "b"
    if va < vb:
        return "a"
    if vb < va:
        return "b"
    return ""


def _round_decidable(mine: dict[int, Round], theirs: dict[int, Round], idx: int) -> bool:
    """A round is decidable only when BOTH players have submitted a result
    (valid or flagged). One-sided submissions must never decide a round: the
    client UI only scores mutually-disclosed rounds, so a fast player cannot
    race a slow-but-active opponent into a premature forfeit (audit #3)."""
    ra = mine.get(idx)
    rb = theirs.get(idx)
    return (
        ra is not None and ra.result_ms is not None and
        rb is not None and rb.result_ms is not None
    )


def _majority_reached(match: Match) -> bool:
    """True once a player has mathematically secured the best-of-three
    majority from the mutually-decided rounds already played — mirroring the
    client UI, which ends the match at 2-0/2-1 and requests settlement
    immediately (audit #3: the server used to demand all three rounds from
    both players, so the NATURAL outcome could never settle and the claim
    flow died on a 409)."""
    a, b = sorted(match.players)
    rounds_a = match.rounds.get(a, {}) or {}
    rounds_b = match.rounds.get(b, {}) or {}
    wins_needed = ROUNDS // 2 + 1
    wins_a = wins_b = 0
    for idx in range(ROUNDS):
        if not _round_decidable(rounds_a, rounds_b, idx):
            continue
        w = _round_winner(rounds_a, rounds_b, idx)
        if w == "a":
            wins_a += 1
        elif w == "b":
            wins_b += 1
    return wins_a >= wins_needed or wins_b >= wins_needed


def match_completed(match: Match) -> bool:
    """True when the best-of-three is decidable: a player already holds the
    round-win majority from MUTUALLY-decided rounds, OR both players finished
    all rounds, OR the grace window passed (after which unplayed rounds
    settle as forfeits)."""
    if len(match.players) < 2:
        return False
    if _majority_reached(match):
        return True
    for addr in match.players:
        mine = match.rounds.get(addr, {}) or {}
        if any(mine.get(i) is None or mine[i].result_ms is None for i in range(ROUNDS)):
            # Every round past the grace deadline is a forfeit round.
            if time.time() - match.created_at <= MATCH_SETTLE_GRACE_SECONDS:
                return False
    return True


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
    # P0-fix (audit #2): a participant could settle mid-game (or void a
    # zero-progress match instantly). Settlement only happens on explicit
    # completion, or after the grace window (then unplayed rounds forfeit).
    if not match_completed(match):
        raise MatchError(
            "Match is not complete yet — both players must finish all rounds "
            f"or the {MATCH_SETTLE_GRACE_SECONDS // 60}-minute grace window must pass"
        )

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
    # P0-fix (audit #4): the oracle refuses settlements whose time arrays are
    # empty — and main.py has no fallback, so a forfeit-only winner used to
    # strand the stake in a settled-without-signature state forever. Reserve
    # at least one engine-validated time (the max plausible value) so every
    # settled match is signable. Applied to the RETURNED arrays, not just the
    # signed scalars, so validatedTimes always matches the signed digest.
    if not times_a:
        times_a = [float(MAX_HUMAN_MS)]
    if not times_b:
        times_b = [float(MAX_HUMAN_MS)]
    winner_times = times_a if winner == a else times_b
    loser_times = times_b if winner == a else times_a
    winner_ms = int(round(min(winner_times)))
    loser_ms = int(round(min(loser_times)))
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
