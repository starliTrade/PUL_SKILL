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
import os
import secrets
from dataclasses import dataclass, field
from typing import Any

import timebase

ROUNDS = 3
MIN_HUMAN_MS = 105.0           # below this is not humanly plausible — MUST match
                               # the client floor (antiCheat.MIN_HUMAN_REACTION_MS = 105)
                               # so an attacker gains no threshold advantage
MAX_HUMAN_MS = 1200.0          # above this is a disconnect / not a serious attempt
CLOCK_TOLERANCE_MS = 250.0     # network + NTP slack for coarse wall-clock gates
REACTION_JITTER_MS = 60.0       # client timer slop allowance for the claim-vs-
                                # server-observed reaction gate (audit #4)
SUBMIT_LATENCY_TOLERANCE_MS = 400.0  # max plausible network latency between a
                                # player's click and the server receiving it —
                                # a claim faster than (observed − this) is a
                                # claim-faster-than-reality fabrication.
                                # Audit #8 F-01: this tolerance NO LONGER decides
                                # winners — ranking uses the SERVER-OBSERVED
                                # reaction time (elapsed − target_ms), so a
                                # fabricated 105ms claim cannot outrank an
                                # honest 220ms player even when it passes the
                                # plausibility gate (see Round.observed_ms).
ROUND_EXPIRY_SECONDS = 60
# --- Audit #10 (item 5): ONE deadline table -----------------------------------
#
# The expiry windows used to live in three uncoordinated places (this engine,
# oracle.py's signature deadline, the contract's MATCH_TIMEOUT). These are the
# numbers the server reasons about; oracle.py imports them so a signature can
# never outlive the on-chain refund horizon.
MATCH_TIMEOUT_SECONDS = 30 * 60  # == PulsarEscrow.MATCH_TIMEOUT (30 min): the
                                 # settlement window. Audit H19 added
                                 # PulsarEscrow.REFUND_GRACE (10 min) on top:
                                 # the permissionless refund opens only at
                                 # MATCH_TIMEOUT + REFUND_GRACE, so a stalling
                                 # loser cannot deny the winner. A signature is
                                 # therefore worthless from MATCH_TIMEOUT on,
                                 # which is what this clamp enforces.
MATCH_EXPIRY_SECONDS = 600     # active-play expiry, counted from ACTIVATION
                               # (the moment the joiner paired), NOT from queue
                               # entry (audit #8 F-05). The on-chain refund
                               # horizon (30 min) still starts at deposit.
QUEUE_EXPIRY_SECONDS = 600     # how long an UNPAIRED waiting match may sit in
                               # the queue before it is voided (counted from
                               # created_at — queue lifetime, not play time)
COMMIT_WINDOW_SECONDS = 30     # per-round intent-binding window
FORFEIT_SENTINEL_MS = 0.0      # audit #8 F-15: declared forfeit time in the
                               # signed packet (never a fabricated human time)

# P0-fix (audit #2): after this long past activation, a participant may settle
# an unfinished match — missing rounds become forfeits. Before that, settle()
# refuses so nobody can race ahead of their opponent (or void a fresh match).
MATCH_SETTLE_GRACE_SECONDS = 480  # 8 minutes after activation (unchanged)


# Audit H1 — latency fairness (D1 = option D: real money).
#
# `observed_ms` = elapsed − target_ms, where `elapsed` runs from when the server
# SENT the target to when the submission ARRIVED. Network latency can only
# inflate it, so a player 10ms from the server and one 100ms away who react
# identically differ by ~45ms — decisive in a game whose range is ~150-400ms.
#
# The ranking value is `observed − min_rtt/2`. The MINIMUM is what makes this
# safe: a naive `observed − rtt/2` rewards INFLATING the reported RTT (a larger
# rtt yields a smaller compensated time, i.e. looking faster). The minimum
# cannot be inflated — the true value stays in the set — and cannot be deflated
# below the network floor, and deflating only REDUCES the compensation, so there
# is no incentive in either direction.
MAX_COMPENSATION_MS = 150.0  # never credit more than this, whatever is reported
MAX_QUEUE_RTT_MS = 400.0  # entry gate: above this the experience is unplayable

# Audit H23 / G5 — skill-based matchmaking (D1 = option D: real money).
#
# Pairing the first two players in a stake bucket is, under real money, a
# money-transfer mechanism: a novice and a veteran queue at the same stake, are
# paired instantly, and the novice's stake moves to the veteran. No amount of
# anti-cheat fixes that — the veteran is not cheating.
#
# The rating is ELO-style and derived from settled OUTCOMES. It is deliberately
# NOT derived from raw reaction times: a reaction time is one noisy sample, and
# a rating built on noise would move every player's number by tens of points per
# match, which makes the band meaningless.
DEFAULT_RATING = 1200.0
K_FACTOR = 32.0  # standard ELO step
RATING_BAND = 150.0  # initial pairing window, in rating points
RATING_BAND_WIDEN_SECONDS = 10.0  # wait this long and the window grows
MAX_RATING_BAND = 800.0  # ...but never past this: a queue that never matches
                         # is its own failure, and beyond this the mismatch is
                         # worse than the wait


def settlement_deadline(match: Any) -> int:
    """Return the contract's refund horizon for this match.

    Audit H20 changed the contract's anchor: `refundTimeoutMatch` now counts
    MATCH_TIMEOUT from ACTIVATION when the duel was paired, and from the deposit
    only for a duel that never paired. This must mirror that exactly — a clamp
    anchored to the wrong instant either mints a proof the contract rejects or
    leaves one valid after a permissionless refund became available.

    (Before H20 the contract anchored on `createdAt` alone, which is why this
    used to read `created_at` unconditionally.)
    """
    created = float(getattr(match, "created_at", 0.0))
    activated = float(getattr(match, "activated_at", 0.0) or 0.0)
    origin = max(created, activated)
    return int(origin + MATCH_TIMEOUT_SECONDS)

# Secret used to MAC result proofs.
# Audit #6 C4: this was a per-process `secrets.token_bytes(32)`, so with N
# replicas (the exact deployment Firestore exists for) commit/reveal landing
# on replica A and result on replica B → proof validation failed → 409 on a
# valid round. Now derived deterministically from ORACLE_SIGNING_SECRET with
# a context label via HKDF-SHA256, so EVERY replica derives the identical
# key while remaining cryptographically independent of the oracle key
# itself. Rotating the secret invalidates in-flight proofs only.
# Audit #10 (item 9): the `secrets.token_bytes(32)` fallback branch here was
# DEAD CODE — api/auth.py refuses to start without ORACLE_SIGNING_SECRET, so
# this module can never be imported without it. A per-process random proof key
# silently splitting commit/reveal across replicas was the exact bug class
# audit #6 C4 fixed; keeping a fallback branch that re-introduces it (should
# the auth gate ever change) is worse than failing loudly.
if not os.environ.get("ORACLE_SIGNING_SECRET"):
    raise RuntimeError(
        "ORACLE_SIGNING_SECRET is required: result-proof keys must be "
        "identical across replicas (derive deterministically, never per-process)."
    )
_PROOF_SECRET = hashlib.pbkdf2_hmac(
    "sha256",
    os.environ["ORACLE_SIGNING_SECRET"].encode("utf-8"),
    b"pulsar/result-proof/v1",
    dklen=32,
    iterations=1,  # HKDF-style single-round derivation of a high-entropy input
)

class MatchError(Exception):
    """Raised on invalid match state transitions."""


@dataclass
class Round:
    index: int
    commit_hash: str = ""
    commit_at: float = 0.0
    # Audit H2: a SERVER-chosen salt, minted at commit time and folded into
    # `result_proof`. Without it the binding rested entirely on a client-chosen
    # hash, so the server could not prove the commitment predates the target.
    commit_salt: str = ""
    target_hash: str = ""
    target_salt: str = ""
    target_ms: float = 0.0
    revealed: bool = False
    revealed_at: float = 0.0
    result_ms: float | None = None
    # Audit #8 F-01: the reaction the SERVER witnessed for this submission
    # (elapsed − target_ms). Network latency can only inflate it, never shrink
    # it, so it is the authoritative ranking signal; result_ms stays as the
    # client's claim (display + cross-check only).
    observed_ms: float | None = None
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
    # Audit #8 F-05: play deadlines (grace window, play expiry) are counted
    # from ACTIVATION (the joiner pairing in), not from queue entry. A match
    # that waited 9 minutes in a slow queue must still get its full play
    # window after pairing. None for unpaired (waiting) matches.
    activated_at: float | None = None
    # Audit #5: the joiner must know its role BEFORE the creator's deposit is
    # visible on-chain (the creator deposits first by protocol design), so
    # role is persisted and restored with the match instead of being inferred
    # from an on-chain read that cannot succeed yet.
    joiner: str = ""  # second player — deposits after the creator's deposit is visible
    # Audit H1: the MINIMUM RTT each player has reported this match. Per match,
    # not per round, so a player cannot "warm up" a good value late.
    min_rtt_ms: dict[str, float] = field(default_factory=dict)
    # Audit M27: a friend challenge is a waiting match RESERVED for one
    # address. Empty string = open queueing (the default, and every legacy
    # document). Pairing requires BOTH sides to agree: the reservation must be
    # for the arriving player, and the arriving player must not have named
    # someone else.
    target: str = ""

    def play_started_at(self) -> float:
        """The instant the PLAY clock started (activation, falling back to
        creation for legacy documents that pre-date the field)."""
        return self.activated_at if self.activated_at else self.created_at

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
            # Audit-#5 refresh recovery: a page reload wipes the client's local
            # scoreboard. The player's own valid times (their data) plus the
            # mutually-disclosed opponentTimes below let the client rebuild
            # the exact score and resume at the right round.
            view["myTimes"] = {
                str(idx): r.result_ms
                for idx, r in mine.items()
                if r.result_ms is not None and r.valid
            }
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
        view["youAreJoiner"] = bool(me and self.joiner == me["address"])
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
        # Audit H23: address -> ELO rating. Absent means "new player", so the
        # default is applied at read time rather than seeded here.
        self.ratings: dict[str, float] = {}

    def rating_for(self, address: str) -> float:
        """The player's current rating (audit H23). Default for a new player."""
        return self.ratings.get(address.lower(), DEFAULT_RATING)

    def apply_rating_result(self, winner: str, loser: str) -> None:
        """ELO update from a settled match (audit H23).

        Zero-sum by construction: the winner gains exactly what the loser drops,
        so the pool cannot inflate and the band keeps its meaning.
        """
        win = winner.lower()
        lose = loser.lower()
        rw = self.rating_for(win)
        rl = self.rating_for(lose)
        expected_w = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
        delta = K_FACTOR * (1.0 - expected_w)
        self.ratings[win] = rw + delta
        self.ratings[lose] = rl - delta

    def _rating_band(self, waited_seconds: float) -> float:
        """The pairing window after waiting this long (audit H23)."""
        widened = RATING_BAND + (waited_seconds / RATING_BAND_WIDEN_SECONDS) * RATING_BAND
        return min(widened, MAX_RATING_BAND)

    def enqueue(self, address: str, stake: float, rtt_ms: float | None = None) -> Match:
        """Queue a player. `rtt_ms` is the client's measured round trip.

        Audit H1: the ping cap is an ENTRY GATE with a clear message, not a
        silent loss. Above MAX_QUEUE_RTT_MS the compensation cannot make the
        match fair, so the player is told rather than quietly losing.
        """
        if rtt_ms is not None and rtt_ms > MAX_QUEUE_RTT_MS:
            raise MatchError(
                f"Ping too high to play fairly: {rtt_ms:.0f}ms round trip, "
                f"the limit is {MAX_QUEUE_RTT_MS:.0f}ms. Try a better connection."
            )
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
            # Audit H23: pair within a rating band, widened by how long the
            # WAITING player has been in the queue. A queue that never matches
            # is its own failure, so the band is not a hard filter.
            other_addr = next(iter(m.players), "")
            waited = timebase.now() - float(m.players.get(other_addr, {}).get("joinedAt", 0.0))
            band = self._rating_band(max(waited, 0.0))
            if abs(self.rating_for(addr) - self.rating_for(other_addr)) > band:
                continue
            # Found an opponent: activate the match.
            m.players[addr] = {"address": addr, "joinedAt": timebase.now()}
            m.status = "active"
            m.joiner = addr
            bucket.remove(other)
            self.player_match[addr] = m.match_id
            return m
        # No opponent: create a new waiting match.
        match_id = secrets.token_hex(16)
        m = Match(
            match_id=match_id,
            stake=stake,
            created_at=timebase.now(),
            players={addr: {"address": addr, "joinedAt": timebase.now()}},
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
        now = timebase.now()
        for mid in list(self.matches):
            m = self.matches[mid]
            if m.status in ("waiting", "active") and now - m.created_at > MATCH_EXPIRY_SECONDS:
                m.status = "void"
        for stake, bucket in list(self.queue.items()):
            self.queue[stake] = [
                mid for mid in bucket
                if mid in self.matches and self.matches[mid].status == "waiting"
            ]


def _result_proof(
    match_id: str,
    address: str,
    round_index: int,
    commit_hash: str,
    target_ms: int,
    commit_salt: str,
) -> str:
    """Unforgeable per-player round proof.

    Audit H2: `commit_salt` is REQUIRED. It is minted by the server at commit
    time, so the proof is bound to a value the client could not predict when it
    committed — and a commitment cannot be swapped for a different one after the
    target is revealed, because the salt changes with it.
    """
    payload = f"{match_id}|{address}|{round_index}|{commit_hash}|{target_ms}|{commit_salt}".encode()
    return hmac.new(_PROOF_SECRET, payload, hashlib.sha256).hexdigest()


def commit_intent(match: Match, address: str, round_index: int, intent_hash: str) -> None:
    """Player binds this round to one intent hash before seeing the target."""
    _ensure_active(match, address)
    if round_index not in range(ROUNDS):
        raise MatchError("Invalid round")
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index) or Round(index=round_index)
    now = timebase.now()
    if r.commit_hash:
        if r.commit_hash != intent_hash.lower():
            # Audit H2: a commitment is FINAL — the window is not an escape
            # hatch. It used to allow a replacement once COMMIT_WINDOW_SECONDS
            # had elapsed, so a player could commit, reveal the target, wait,
            # and commit again with a hash chosen AFTER seeing it. The stored
            # commitment then carried no information, and `result_proof` was
            # bound to it.
            raise MatchError("Round already committed")
        # Idempotent retry of the SAME intent (e.g. a dropped HTTP response on
        # the first commit). Returns without error so a rejected submission can
        # be retried — the target/proof stay bound to this one commit.
        return
    r.commit_hash = intent_hash.lower()
    r.commit_at = now
    # Audit H2: the server's own salt, minted here and never re-minted.
    r.commit_salt = secrets.token_hex(16)
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
    now = timebase.now()
    if now - r.commit_at > COMMIT_WINDOW_SECONDS:
        # Audit H2: a commit is final, so this round is DEAD for this player —
        # the same policy as a stale result. The old message promised a
        # re-commit that is no longer possible.
        raise MatchError("Commit expired — this round is lost")
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
            match.match_id,
            address.lower(),
            round_index,
            r.commit_hash,
            int(r.target_ms),
            r.commit_salt,
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
    rtt_ms: float | None = None,
) -> dict[str, Any]:
    """
    Validate one submitted time and store it for settlement. The submission
    MUST carry the per-player result proof from reveal_target — a commit that
    was never followed by an honest reveal cannot produce a valid result.
    """
    _ensure_active(match, address)
    # Audit H1: record the player's best observed round trip BEFORE anything
    # else, so a rejected submission still contributes its measurement.
    if rtt_ms is not None:
        if rtt_ms < 0:
            raise MatchError("Invalid rtt: must not be negative")
        me = address.lower()
        current = match.min_rtt_ms.get(me)
        if current is None or rtt_ms < current:
            match.min_rtt_ms[me] = float(rtt_ms)
    rounds = match.rounds.setdefault(address.lower(), {})
    r = rounds.get(round_index)
    if r is None or not r.revealed:
        raise MatchError("Round target not revealed")
    if r.result_ms is not None:
        raise MatchError("Result already submitted")
    # Audit #4: a stale round is DEAD — the player lost their chance. Without
    # this, an unplayed round survives all the way to the grace-window settle
    # and converts an opponent who simply stepped away into a forfeit loser.
    if r.revealed_at and timebase.now() - r.revealed_at > ROUND_EXPIRY_SECONDS:
        raise MatchError(
            f"Round expired — results must be submitted within "
            f"{ROUND_EXPIRY_SECONDS}s of the target appearing"
        )
    # P0-fix (audit #2): the commit is no longer decorative. A result is only
    # stored when it carries the proof bound to this player's commit+reveal.
    if not result_proof or not hmac.compare_digest(result_proof, r.result_proof):
        raise MatchError("Invalid result proof for this round")
    now = timebase.now()
    reason = _validate_plausibility(match, r, measured_ms, now)
    r.result_ms = measured_ms
    r.submitted_at = now
    # Audit #8 F-01: record the SERVER-OBSERVED reaction (elapsed − target_ms)
    # for every submission. Ranking uses this, not the client's claim.
    if r.revealed_at:
        r.observed_ms = max(0.0, (now - r.revealed_at) * 1000.0 - r.target_ms)
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
    # Dual timing-consistency gate (audit #4) — the claim is measured from
    # TARGET APPEARANCE, so it is checked against what the SERVER observed:
    #   (a) NO PRE-VISIBLE SUBMISSION: the submission cannot arrive before the
    #       target was even displayed. revealed_at and now share the same
    #       server clock, so this has ZERO tolerance — it closes the audit's
    #       145ms early-submission arbitrage completely.
    #   (b) CLAIM vs SERVER-OBSERVED REACTION: elapsed − target_ms is the
    #       reaction the server actually witnessed (network latency only ever
    #       INCREASES it). A claim faster than that, minus small jitter for
    #       client timer slop, is a fabrication (the 105ms-after-delay cheat).
    if r.revealed_at:
        elapsed_ms = (now - r.revealed_at) * 1000.0
        if elapsed_ms < r.target_ms:
            return "implausible: submitted before the target was displayed"
        observed_reaction = elapsed_ms - r.target_ms
        if observed_reaction + REACTION_JITTER_MS < measured_ms:
            return "implausible: server-observed reaction is faster than the claimed time"
        if measured_ms + SUBMIT_LATENCY_TOLERANCE_MS < observed_reaction:
            return (
                "implausible: claimed reaction is faster than the "
                "server-observed submission timing allows"
            )
    return ""


def _ensure_active(match: Match, address: str) -> None:
    if match.status != "active":
        raise MatchError("Match is not active")
    if address.lower() not in match.players:
        raise MatchError("Not a participant of this match")


def _rank_time(r: Round | None, min_rtt_ms: float | None = None) -> float | None:
    """The ranking time for one player's round, latency-compensated.

    Audit #8 F-01: the server-OBSERVED reaction (elapsed − target_ms) is
    authoritative, because network latency can only ever inflate it. A client
    that fabricates a 105ms claim while really reacting in 450ms cannot outrank
    an honest 220ms player — its observed time is 450ms.

    Audit H1: observed is then compensated by half the player's MINIMUM round
    trip, so the ranking reflects the reaction rather than the network distance.
    The compensation is capped at MAX_COMPENSATION_MS so a wild report cannot
    make a player look faster than they were. Falls back to the claim for legacy
    documents written before observed_ms existed.
    """
    if r is None or not r.valid or r.result_ms is None:
        return None
    if r.observed_ms is None:
        return r.result_ms
    if min_rtt_ms is None:
        return r.observed_ms
    compensation = min(max(min_rtt_ms, 0.0) / 2.0, MAX_COMPENSATION_MS)
    return r.observed_ms - compensation


def _round_winner(
    mine: dict[int, Round],
    theirs: dict[int, Round],
    idx: int,
    min_rtt_a: float | None = None,
    min_rtt_b: float | None = None,
) -> str:
    """'a' (mine wins) | 'b' (theirs wins) | '' (undecided) for one round."""
    ra = mine.get(idx)
    rb = theirs.get(idx)
    va = _rank_time(ra, min_rtt_a)
    vb = _rank_time(rb, min_rtt_b)
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
    rtt_a = match.min_rtt_ms.get(a)
    rtt_b = match.min_rtt_ms.get(b)
    for idx in range(ROUNDS):
        if not _round_decidable(rounds_a, rounds_b, idx):
            continue
        w = _round_winner(rounds_a, rounds_b, idx, rtt_a, rtt_b)
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
            # Audit #8 F-05: the grace window counts from ACTIVATION (the
            # moment the joiner paired), not from queue entry — a match that
            # waited 9 minutes in a slow queue must not be instantly voided
            # (or instantly forfeitable) at its first round.
            if timebase.now() - match.play_started_at() <= MATCH_SETTLE_GRACE_SECONDS:
                return False
    return True


# Audit M7: a MAC over the settlement's identity, so the oracle can prove a
# record came from THIS engine rather than from a caller that built a dict with
# the right keys. The key is the same proof secret the round proofs use, so no
# new secret is introduced.
def stamp_settlement(record: dict[str, Any]) -> None:
    """Stamp a settlement record as engine-produced (audit M7)."""
    record["engineStamp"] = _settlement_stamp(record)


def _settlement_stamp(record: dict[str, Any]) -> str:
    payload = "|".join(
        [
            str(record.get("matchId", "")),
            str(record.get("winner", "")),
            str(record.get("loser", "")),
            str(record.get("winnerTimeMs", "")),
            str(record.get("loserTimeMs", "")),
            str(record.get("status", "")),
        ]
    ).encode()
    return hmac.new(_PROOF_SECRET, payload, hashlib.sha256).hexdigest()


def settlement_is_stamped(record: dict[str, Any]) -> bool:
    """True when the record carries a valid engine stamp (audit M7)."""
    supplied = record.get("engineStamp")
    if not isinstance(supplied, str) or not supplied:
        return False
    return hmac.compare_digest(supplied, _settlement_stamp(record))


def settlement_record_for_resign(match: Match) -> dict[str, Any]:
    """Rebuild a settlement record from a SETTLED match, stamped (audit M7).

    The F-12 re-sign path used to build this dict by hand and hand it to
    `sign_settlement` — which is exactly the hole M7 closes: a caller that can
    build a dict with the right keys got a signature over real money. The record
    is now reconstructed from the match the ENGINE owns, and stamped, so the
    oracle can verify its provenance.

    The values come from the stored envelope (the engine's own earlier output),
    never from the caller.
    """
    envelope = match.signed_settlement or {}
    record = {
        "status": "settled",
        "matchId": match.match_id,
        "winner": match.winner,
        "loser": envelope.get("loser", ""),
        "winnerTimeMs": int(envelope.get("winnerTimeMs", 0)),
        "loserTimeMs": int(envelope.get("loserTimeMs", 0)),
        "validatedTimes": envelope.get("validatedTimes", {}),
    }
    stamp_settlement(record)
    return record


def apply_settlement_ratings(store: MatchStore, result: dict[str, Any]) -> None:
    """Update both players' ratings from a settled result (audit H23).

    Kept OUT of `settle()` because that function is pure match logic with no
    store handle, and because a VOID must not move anyone's rating: nobody won.
    """
    if result.get("status") != "settled":
        return
    winner = result.get("winner")
    loser = result.get("loser")
    if winner and loser:
        store.apply_rating_result(winner, loser)


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
    forfeit_a = forfeit_b = False
    times_a: list[float] = []
    times_b: list[float] = []
    rtt_a = match.min_rtt_ms.get(a)
    rtt_b = match.min_rtt_ms.get(b)
    for idx in range(ROUNDS):
        ra = rounds_a.get(idx)
        rb = rounds_b.get(idx)
        va = _rank_time(ra, rtt_a)
        vb = _rank_time(rb, rtt_b)
        if va is not None:
            times_a.append(va)
        if vb is not None:
            times_b.append(vb)
        if va is None and vb is None:
            continue  # double forfeit: round awards nobody
        if vb is None:
            wins_a += 1  # forfeit by b
            forfeit_b = True
            continue
        if va is None:
            wins_b += 1  # forfeit by a
            forfeit_a = True
            continue
        if va < vb:
            wins_a += 1
        elif vb < va:
            wins_b += 1
        # exact tie: round awards nobody

    wins_needed = ROUNDS // 2 + 1  # 2 of 3

    # Audit H24: an absent player forfeits the MATCH, not just the rounds they
    # missed.
    #
    # The loop above awards a round to the present player only when the OTHER
    # player submitted. A round where NEITHER submitted awards nobody — which
    # conflates two very different situations:
    #
    #   1. both players were present and neither submitted (a mutual stall)
    #   2. one player was present, played, and the other never showed
    #
    # In case 2 the present player cannot play the remaining rounds against
    # nobody, so they finish 1-0, reach no majority, and the match VOIDS with
    # both stakes refunded. The player who showed up and won got nothing; the
    # one who never appeared got their stake back. Under D1 (real money) that
    # makes abandoning a FREE OPTION — strictly better than losing.
    #
    # The principle: the player who showed up must not be punished for the
    # opponent's absence.
    submitted_a = sum(
        1 for idx in range(ROUNDS)
        if rounds_a.get(idx) is not None and rounds_a[idx].result_ms is not None
    )
    submitted_b = sum(
        1 for idx in range(ROUNDS)
        if rounds_b.get(idx) is not None and rounds_b[idx].result_ms is not None
    )
    if submitted_a > 0 and submitted_b == 0:
        wins_a, wins_b = wins_needed, 0
        forfeit_b = True
    elif submitted_b > 0 and submitted_a == 0:
        wins_a, wins_b = 0, wins_needed
        forfeit_a = True

    if wins_a < wins_needed and wins_b < wins_needed:
        # Audit H24, second half: the match cannot complete. Who benefits from a
        # void? The player who is BEHIND — they recover a stake they were losing.
        # So a void is a free option for the trailing player, and "just void it"
        # is not a neutral default.
        #
        # The server cannot tell "A is waiting for B" from "both left": with
        # equal submissions the only signal is who submitted last, which is
        # noise. So the rule favours the LEADER, and the residual risk is that a
        # leading player can abandon and still win — a weaker incentive than the
        # current one, where a trailing player can always abandon and get their
        # stake back.
        if wins_a > wins_b:
            wins_a = wins_needed
        elif wins_b > wins_a:
            wins_b = wins_needed
        else:
            # A genuine tie (0-0, or 1-1 with the decider unplayed): nobody is
            # ahead, so nobody is punished. Both are refunded.
            match.status = "void"
            return {"status": "void", "reason": "no round-win majority — stakes refund"}

    winner = a if wins_a >= wins_needed else b
    loser = b if winner == a else a
    # Audit #8 F-15: a forfeit side no longer gets a FABRICATED human time
    # (1200ms) written into the oracle-signed packet and the on-chain event.
    # Forfeits are declared with the sentinel FORFEIT_SENTINEL_MS = 0 and a
    # per-side forfeit flag the oracle packet carries; the chain record and
    # the ledger then tell the truth ("opponent forfeited"), not a lie
    # ("they reacted in 1200ms"). The oracle still accepts the settlement
    # because the sentinel keeps the arrays non-empty (audit #4's signability
    # requirement) while being unambiguous.
    if not times_a:
        times_a = [FORFEIT_SENTINEL_MS]
        forfeit_a = True
    if not times_b:
        times_b = [FORFEIT_SENTINEL_MS]
        forfeit_b = True
    winner_times = times_a if winner == a else times_b
    loser_times = times_b if winner == a else times_a
    winner_ms = int(round(min(winner_times)))
    loser_ms = int(round(min(loser_times)))
    match.winner = winner
    match.status = "settled"
    match.settled_at = timebase.now()
    settled = {
        "status": "settled",
        "matchId": match.match_id,
        "winner": winner,
        "loser": loser,
        "stake": match.stake,
        "roundWins": {a: wins_a, b: wins_b},
        "forfeits": {a: forfeit_a, b: forfeit_b},
        "validatedTimes": {a: times_a, b: times_b},
        "winningMedianMs": winner_ms,
        "winnerTimeMs": winner_ms,
        "loserTimeMs": loser_ms,
    }
    # Audit M7: stamp it, so the oracle can prove this came from the engine.
    stamp_settlement(settled)
    return settled
