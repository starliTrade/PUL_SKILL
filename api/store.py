"""
PULSAR P2.2a — Durable match persistence.

Why: P1's MatchStore keeps matches in process memory. Under serverless
hosting (Freebuff/Cloud Run style: instances recycled between requests,
multiple replicas), memory is lost and matchmaking silently splits across
replicas. This module swaps the storage layer while keeping the exact
MatchStore interface, so api/main.py needs no changes.

Storage choice: Google Cloud Firestore (already part of this product's
stack — the web client uses it for profiles/leaderboard). Match documents
are small, writes are cheap, and Firestore gives atomic transactions for
matchmaking (two players enqueuing concurrently must not double-match).

Falls back to the in-memory store when FIRESTORE credentials are absent
(local dev, smoke tests). Every method is sync-friendly via short-polling,
matching the client's existing 2.5s polling loop.
"""

from __future__ import annotations

import copy
import os
import secrets
import sys
import threading
from collections.abc import Callable
from typing import Any

import metrics
import timebase

import match_engine as _default_engine  # engine fns for transactional mutations
from match_engine import (
    MATCH_EXPIRY_SECONDS,
    QUEUE_EXPIRY_SECONDS,
    Match,
    MatchError,
    Round,
)

try:  # optional dependency — absent in local dev until credentials exist
    from google.cloud import firestore as _firestore  # type: ignore

    _FIRESTORE_AVAILABLE = True
except Exception:  # pragma: no cover
    _FIRESTORE_AVAILABLE = False

COLLECTION = "pulsar_matches"
QUEUE_DOC = "pulsar_queue"

# How many matches the in-process mirror may hold. `DurableMatchStore._mirror`
# writes every match it touches into it, so without a bound a long-running
# server accumulates every duel it has ever seen.
_MEMORY_MATCH_MAX = 4096

# How many active matches one durable sweep pass may scan (audit 2026-10-13).
# The sweep is maintenance on the hottest path; an unbounded scan grows with the
# whole live population.
_SWEEP_SCAN_LIMIT = 500


def _can_pair(waiting: Match, addr: str, target: str) -> bool:
    """Audit M27 — both sides must agree before a reserved match is paired.

    `waiting` is the queued match, `addr` the arriving player, `target` the
    address the arriving player named ("" = open queueing).

    A match reserved for someone else is never offered to a stranger, and
    naming a creator who reserved THEIR match for someone else does not force a
    duel they never agreed to. Open + open still pairs exactly as before.
    """
    reserved_for = waiting.target or ""
    if reserved_for and reserved_for != addr:
        return False
    if target and target != waiting.creator:
        return False
    return True


def _creator_of(match: Match) -> str:
    """The waiting match's creator (first player), lowercased."""
    return (match.creator or next(iter(match.players), "")).lower()


def _creator_rtt(match: Match) -> float | None:
    """The RTT the waiting player reported when they queued, if any."""
    value = match.min_rtt_ms.get(_creator_of(match))
    return float(value) if value is not None else None


def _rating_band(waited_seconds: float) -> float:
    """The rating window after waiting this long (audit H23)."""
    widened = _default_engine.RATING_BAND + (
        waited_seconds / _default_engine.RATING_BAND_WIDEN_SECONDS
    ) * _default_engine.RATING_BAND
    return min(widened, _default_engine.MAX_RATING_BAND)


def check_ping_cap(rtt_ms: float | None) -> None:
    """Audit H1: the ping cap is an ENTRY GATE with a clear message.

    It lives HERE, not in the engine's standalone `MatchStore`, because that
    class is not what production runs — the cap existed only for the tests
    (audit CRITICAL-2). Lying about a HIGH ping only excludes you, and lying
    about a LOW one buys nothing (the ranking uses the server-observed time),
    so this gate is not gameable in either direction.
    """
    if rtt_ms is not None and rtt_ms > _default_engine.MAX_QUEUE_RTT_MS:
        raise MatchError(
            f"Ping too high to play fairly: {rtt_ms:.0f}ms round trip, "
            f"the limit is {_default_engine.MAX_QUEUE_RTT_MS:.0f}ms. "
            "Try a better connection."
        )


def choose_opponent(
    candidates: list[Match],
    *,
    addr: str,
    target: str,
    rtt_ms: float | None,
    rating_for: Callable[[str], float],
    now: float,
) -> Match | None:
    """THE pairing decision — both backends call this (audit CRITICAL-2).

    The ping cap and the rating band existed only in `match_engine.MatchStore`,
    which production never instantiates, so neither applied to a real duel. One
    decision function is the structural fix: the two backends cannot drift if
    there is only one of them.

    Audit H1: among compatible opponents the closest CONNECTION wins, so the
    network's contribution to the ranking is comparable on both sides. The
    server cannot measure the network's share of a round, so it must not
    subtract a client's claim from the ranking (that is a stake-transfer
    exploit); pairing is where it can act without being gameable.
    """
    compatible: list[Match] = []
    reserved_for_me: list[Match] = []
    for m in candidates:
        if not _can_pair(m, addr, target):
            continue
        creator = _creator_of(m)
        waited = now - float(m.players.get(creator, {}).get("joinedAt", 0.0) or 0.0)
        if abs(rating_for(addr) - rating_for(creator)) > _rating_band(max(waited, 0.0)):
            continue
        compatible.append(m)
        if (m.target or "") == addr:
            reserved_for_me.append(m)
    if not compatible:
        return None

    # A reservation for THIS player outranks every heuristic: someone asked for
    # them by name (audit M27), and that request must not be lost to a tiebreak.
    if reserved_for_me:
        return reserved_for_me[0]

    def distance(m: Match) -> float:
        other = _creator_rtt(m)
        if rtt_ms is None or other is None:
            return float("inf")  # unknown RTT: deprioritised, never preferred
        return abs(other - rtt_ms)

    return min(compatible, key=distance)


def _queue_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The queue document's waiting slots (audit M27).

    The document used to hold a single `waitingMatchId`, which cannot express
    two players waiting at the same stake for different people — exactly what
    friend challenges need. It now holds a list of `{matchId, target}` slots.
    The legacy single-id shape is still read, so a deployment mid-upgrade keeps
    matchmaking.
    """
    waiting = data.get("waiting")
    if isinstance(waiting, list):
        return [e for e in waiting if isinstance(e, dict) and e.get("matchId")]
    legacy = data.get("waitingMatchId")
    if legacy:
        return [{"matchId": str(legacy), "target": ""}]
    return []


def _round_to_doc(r: Round) -> dict[str, Any]:
    return {
        "index": r.index,
        "commit_hash": r.commit_hash,
        "commit_at": r.commit_at,
        # Audit H2: the server's commit salt must survive persistence, or a
        # recycled instance cannot reproduce `result_proof` and every submission
        # after a restart is rejected as invalid.
        "commit_salt": r.commit_salt,
        "target_hash": r.target_hash,
        "target_salt": r.target_salt,
        "target_ms": r.target_ms,
        "revealed": r.revealed,
        "revealed_at": r.revealed_at,
        "result_ms": r.result_ms,
        # Audit #8 F-01: the server-observed reaction must survive
        # persistence, or the cross-replica ranking falls back to the
        # fabricable client claim.
        "observed_ms": r.observed_ms,
        "submitted_at": r.submitted_at,
        "valid": r.valid,
        "reject_reason": r.reject_reason,
        # P0-fix (audit #2): the per-player result proof must survive
        # persistence, otherwise a recycled instance can't validate the
        # submission that follows a reveal.
        "result_proof": r.result_proof,
    }


def _round_from_doc(d: dict[str, Any]) -> Round:
    r = Round(index=int(d.get("index", 0)))
    r.commit_hash = d.get("commit_hash", "")
    r.commit_at = float(d.get("commit_at", 0.0))
    r.commit_salt = d.get("commit_salt", "")
    r.target_hash = d.get("target_hash", "")
    r.target_salt = d.get("target_salt", "")
    r.target_ms = float(d.get("target_ms", 0.0))
    r.revealed = bool(d.get("revealed", False))
    r.revealed_at = float(d.get("revealed_at", 0.0))
    r.result_ms = d.get("result_ms")
    r.observed_ms = d.get("observed_ms")
    r.submitted_at = float(d.get("submitted_at", 0.0))
    r.valid = bool(d.get("valid", False))
    r.reject_reason = d.get("reject_reason", "")
    r.result_proof = d.get("result_proof", "")
    return r


# --- document schema versioning (plan item 6.11 / G16) ------------------------
#
# Audit 2026-10-15: this item was marked done for months with NO implementation.
# The read path tolerated missing fields, which is not the same thing as
# versioning: tolerating a MISSING field is safe, but nothing stopped old code
# from silently misreading a NEWER document — it would take the fields it knew
# and ignore the rest, which is exactly how a schema change corrupts data.
#
# So there are three parts, and the third is the one that matters:
#   1. every document written carries `schemaVersion`;
#   2. legacy documents are migrated forward (derived fields stamped);
#   3. a document NEWER than this code refuses to be read, loudly.
SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """A stored document is newer than this code understands."""


def _creator_from_players(players: dict[str, Any]) -> tuple[str, str]:
    """(creator, joiner) for a document that predates those fields.

    Audit 2026-10-15: this used to be `next(iter(players))` — "the first key is
    the creator, because insertion order is preserved". That assumption is
    FALSE for Firestore: writing `{"0xaa": ..., "0xbb": ...}` and reading it back
    five times returned `('0xbb', '0xaa')` every time. So the derivation could
    name the WRONG player as the creator — and in a money game the creator is the
    one who deposits first, so this is not cosmetic.

    The stable signal is `joinedAt`, which every player entry carries: the
    creator is the one who joined first. When it is absent there is no honest way
    to tell, so both are returned empty rather than guessed.
    """
    entries = [
        (addr, info) for addr, info in (players or {}).items() if isinstance(info, dict)
    ]
    stamped = [(addr, float(info.get("joinedAt", 0.0) or 0.0)) for addr, info in entries]
    if not stamped or all(ts == 0.0 for _addr, ts in stamped):
        # No timestamps: refuse to guess. An empty creator is visible; a wrong
        # one is not.
        return "", ""
    stamped.sort(key=lambda pair: pair[1])
    creator = stamped[0][0]
    joiner = stamped[1][0] if len(stamped) > 1 else ""
    return creator, joiner


def migrate_document(d: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a stored document to SCHEMA_VERSION, in place, and return it.

    Idempotent: a document already at the current version is returned unchanged.
    Unknown FUTURE versions raise rather than being guessed at.
    """
    version = int(d.get("schemaVersion", 0) or 0)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"document schemaVersion={version} is newer than this server "
            f"understands ({SCHEMA_VERSION}) — refusing to read it rather than "
            "silently ignoring fields it does not know about"
        )
    # The field-stamping below runs for EVERY version, not only for older ones.
    #
    # Audit 2026-10-15: it used to `return d` early when the version already
    # matched — so a document that claimed v1 but was missing a required field
    # (which the backup round trip produced) was never repaired. A version number
    # is a claim about shape; if the shape is wrong, the claim is not a reason to
    # leave it wrong.
    players = dict(d.get("players", {}) or {})
    if not d.get("creator") or not d.get("joiner"):
        creator, joiner = _creator_from_players(players)
        if not d.get("creator"):
            d["creator"] = creator
        if not d.get("joiner"):
            d["joiner"] = joiner
    d.setdefault("target", "")
    d.setdefault("min_rtt_ms", {})
    d["schemaVersion"] = SCHEMA_VERSION
    return d


def _match_to_doc(m: Match) -> dict[str, Any]:
    return {
        # Plan item 6.11: every document states the schema it was written under.
        "schemaVersion": SCHEMA_VERSION,
        "match_id": m.match_id,
        "stake": m.stake,
        "created_at": m.created_at,
        # Audit #8 F-05: activation instant (play clock origin) persisted.
        "activated_at": m.activated_at,
        "players": m.players,
        # P0-fix: creator was never persisted, so after the first read the
        # queueing player lost youAreCreator=true and nobody ever sent
        # createDuel — the on-chain deposit step could never happen.
        "creator": m.creator,
        # Audit #5: persist the joiner role — the client needs youAreJoiner
        # before the creator's deposit is visible on-chain.
        "joiner": m.joiner,
        "rounds": {
            addr: {str(idx): _round_to_doc(r) for idx, r in per_player.items()}
            for addr, per_player in m.rounds.items()
        },
        "status": m.status,
        "winner": m.winner,
        "settled_at": m.settled_at,
        "signed_settlement": m.signed_settlement,
        # Audit M27: the reserved target of a friend challenge ("" = open).
        "target": m.target,
        # Audit CRITICAL-2: the per-match minimum RTT. It was never persisted, so
        # on the durable backend every re-read lost it and the latency
        # compensation could never apply in production.
        "min_rtt_ms": m.min_rtt_ms,
    }


def _match_from_doc(d: dict[str, Any]) -> Match:
    # Migrate on read: this is where a document from a NEWER server is refused
    # instead of being half-understood.
    d = migrate_document(dict(d))
    m = Match(
        match_id=d["match_id"],
        stake=float(d["stake"]),
        created_at=float(d["created_at"]),
    )
    m.players = dict(d.get("players", {}))
    # Audit #8 F-05: restore the activation instant (None for legacy docs).
    m.activated_at = d.get("activated_at")
    # P0-fix: restore creator; for documents written before this field
    # existed, derive it (players preserves insertion order — creator first).
    # Audit 2026-10-15: derive from `joinedAt`, NOT from key order — Firestore
    # does not preserve map key order, so "first key" could name the wrong
    # player as the creator.
    _derived_creator, _derived_joiner = _creator_from_players(m.players)
    m.creator = d.get("creator", "") or _derived_creator
    m.joiner = d.get("joiner", "") or _derived_joiner
    m.rounds = {
        addr: {int(idx): _round_from_doc(r) for idx, r in per_player.items()}
        for addr, per_player in (d.get("rounds", {}) or {}).items()
    }
    m.status = d.get("status", "waiting")
    m.winner = d.get("winner", "")
    m.settled_at = float(d.get("settled_at", 0.0))
    m.signed_settlement = d.get("signed_settlement")
    # Audit M27: legacy documents have no target — they were open queueing.
    m.target = str(d.get("target") or "")
    # Audit CRITICAL-2: restore the per-match RTT record (legacy docs: empty).
    m.min_rtt_ms = {
        str(k): float(v) for k, v in (d.get("min_rtt_ms") or {}).items()
    }
    return m


class InMemoryStore:
    """The P1 store — used as fallback and as the local cache layer."""

    def __init__(self) -> None:
        self.matches: dict[str, Match] = {}
        self.queue: dict[float, list[str]] = {}
        # address -> live (waiting|active) match id (idempotent enqueue).
        self.player_match: dict[str, str] = {}
        # Audit H23: address -> ELO rating (process-local, see DurableMatchStore).
        self.ratings: dict[str, float] = {}
        self._lock = threading.Lock()

    def rating_for(self, address: str) -> float:
        return self.ratings.get(address.lower(), _default_engine.DEFAULT_RATING)

    def apply_rating_result(self, winner: str, loser: str) -> None:
        win = winner.lower()
        lose = loser.lower()
        rw = self.rating_for(win)
        rl = self.rating_for(lose)
        delta = _default_engine.K_FACTOR * (1.0 - 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0)))
        self.ratings[win] = rw + delta
        self.ratings[lose] = rl - delta

    def enqueue(
        self,
        address: str,
        stake: float,
        rtt_ms: float | None = None,
        target: str | None = None,
    ) -> Match:
        addr = address.lower()
        # Audit M27: the address a friend challenge is reserved for ("" = open).
        reserved_for = (target or "").lower()
        # Audit H1: the ping cap is an entry gate (audit CRITICAL-2 put it here,
        # where production actually runs).
        check_ping_cap(rtt_ms)
        with self._lock:
            live = self.player_match.get(addr)
            if live:
                m = self.matches.get(live)
                if m and m.status in ("waiting", "active"):
                    return m
                self.player_match.pop(addr, None)
            bucket = self.queue.setdefault(stake, [])
            # Prune stale/self slots, then let the ONE pairing decision choose.
            candidates: list[Match] = []
            for other in list(bucket):
                m = self.matches.get(other)
                if m is None or m.status != "waiting":
                    bucket.remove(other)
                    continue
                if addr in m.players:
                    bucket.remove(other)
                    continue
                candidates.append(m)
            chosen = choose_opponent(
                candidates,
                addr=addr,
                target=reserved_for,
                rtt_ms=rtt_ms,
                rating_for=self.rating_for,
                now=timebase.now(),
            )
            if chosen is not None:
                # Found an opponent: activate the match.
                chosen.players[addr] = {"address": addr, "joinedAt": timebase.now()}
                chosen.status = "active"
                chosen.joiner = addr
                # Audit #8 F-05: the PLAY clock starts when the joiner pairs,
                # not when the creator queued.
                chosen.activated_at = timebase.now()
                if rtt_ms is not None:
                    chosen.min_rtt_ms[addr] = float(rtt_ms)
                bucket.remove(chosen.match_id)
                self.player_match[addr] = chosen.match_id
                return chosen
            match_id = secrets.token_hex(16)
            m = Match(
                match_id=match_id,
                stake=stake,
                created_at=timebase.now(),
                players={addr: {"address": addr, "joinedAt": timebase.now()}},
                creator=addr,
                target=reserved_for,
            )
            if rtt_ms is not None:
                # The waiting player's own RTT, so the next arrival can be paired
                # by closest connection (audit H1).
                m.min_rtt_ms[addr] = float(rtt_ms)
            self.matches[match_id] = m
            bucket.append(match_id)
            self.player_match[addr] = match_id
            return m

    def get(self, match_id: str) -> Match:
        m = self.matches.get(match_id)
        if m is None:
            raise MatchError("Match not found")
        return m

    def pending_challenges(self, address: str) -> list[dict[str, Any]]:
        """Waiting matches RESERVED for `address` (audit M27 closure).

        Without this the challenged player had no way to learn a challenge
        existed: the reservation was real but invisible, and the target only
        found out by queueing for something else.
        """
        addr = address.lower()
        out: list[dict[str, Any]] = []
        with self._lock:
            for stake, bucket in self.queue.items():
                for mid in bucket:
                    m = self.matches.get(mid)
                    if m is None or m.status != "waiting":
                        continue
                    if (m.target or "") != addr:
                        continue
                    out.append({"matchId": m.match_id, "address": m.creator, "stake": stake})
        return out

    def update(self, match_id: str, mutate: Any) -> Any:
        """Single-process serialization of read-modify-write, WITH rollback:
        the match is deep-copied first and restored if the mutation raises.
        This is the memory-mode parity of the Firestore transaction (whose
        rollback is automatic) — a signing failure inside a mutation used to
        wedge the in-memory match as settled-without-proof forever (audit #4)."""
        with self._lock:
            m = self.get(match_id)
            snapshot = copy.deepcopy(m)
            try:
                out = mutate(m)
            except BaseException:
                self.matches[match_id] = snapshot
                raise
            return out

    def sweep_expired(self) -> list[Match]:
        """Void unpaired matches; RETURN the active ones that are due to settle.

        Audit H8: this used to void every ACTIVE match past MATCH_EXPIRY. By
        then the settle grace window has also passed, so `match_completed()` is
        TRUE — the missing rounds are forfeits and the match is exactly what the
        settlement path exists for. Voiding it destroyed the winner's prize:
        `settle()` refuses, no oracle signature is minted, and both players get
        only a refund even though the escrow would still honour a settlement.

        The store has no engine logic, so it does not settle anything itself —
        it hands the due matches back to the caller.
        """
        now = timebase.now()
        due: list[Match] = []
        for mid in list(self.matches):
            m = self.matches[mid]
            if m.status == "waiting" and now - m.created_at > QUEUE_EXPIRY_SECONDS:
                m.status = "void"
            elif m.status == "active" and now - m.play_started_at() > MATCH_EXPIRY_SECONDS:
                due.append(m)
        for stake, bucket in list(self.queue.items()):
            self.queue[stake] = [
                mid for mid in bucket
                if mid in self.matches and self.matches[mid].status == "waiting"
            ]
        return due

    def put(self, match: Match) -> None:
        with self._lock:
            self.matches[match.match_id] = match
            if len(self.matches) <= _MEMORY_MATCH_MAX:
                return
            # Audit (phase 0–7 review): nothing ever removed a match from this
            # map, and `DurableMatchStore._mirror` writes EVERY match it touches
            # into it — so a long-running server accumulated every duel it had
            # ever seen, rounds and all. Same class as M15/M16.
            #
            # Only TERMINAL matches are evictable: a waiting/active duel must
            # never disappear from the cache. The durable sweep
            # (`sweep_stale_settlements`) is the authoritative re-sign pass, so
            # dropping a settled match here costs nothing but a cache miss.
            overflow = len(self.matches) - _MEMORY_MATCH_MAX
            evictable = sorted(
                (
                    (mid, m)
                    for mid, m in self.matches.items()
                    if m.status in ("settled", "void")
                ),
                key=lambda kv: kv[1].settled_at or kv[1].created_at,
            )
            for mid, m in evictable[:overflow]:
                self.matches.pop(mid, None)
                # A `player_match` entry pointing at an evicted match would make
                # `player_live_match` fall through to Firestore on every poll.
                for addr in m.players:
                    if self.player_match.get(addr) == mid:
                        self.player_match.pop(addr, None)


class FirestoreStore:
    """
    Durable store. Matchmaking uses a per-stake queue document holding the
    oldest waiting match id; pairing happens inside a Firestore transaction,
    so concurrent enqueues can never double-match or lose a pairing.
    """

    def __init__(
        self,
        client: Any,
        rating_for: Callable[[str], float] | None = None,
    ) -> None:
        self.db = client
        self.local = InMemoryStore()  # write-through cache for hot reads
        # Audit H9: the last sweep failure, surfaced through /api/health.
        self.last_sweep_error: str = ""
        # address -> live (waiting|active) match id for idempotent re-polls.
        self.player_match: dict[str, str] = {}
        # Audit CRITICAL-2: the rating lookup used by the pairing band. Injected
        # by DurableMatchStore so the durable path applies the SAME band the
        # memory path does. Ratings are still process-local (a documented
        # phase-6 limitation): the band therefore holds within a replica, and
        # across replicas only once ratings are persisted.
        self._rating_for: Callable[[str], float] = rating_for or (
            lambda _addr: _default_engine.DEFAULT_RATING
        )

    # -- internal ------------------------------------------------------------

    def _match_ref(self, match_id: str) -> Any:
        return self.db.collection(COLLECTION).document(match_id)

    def _queue_ref(self, stake: float) -> Any:
        # Document IDs cannot contain '.' — format stakes as integer cents.
        return self.db.collection(QUEUE_DOC).document(str(int(round(stake * 100))))

    @staticmethod
    def _stake_from_doc_id(doc_id: str) -> float:
        return int(doc_id) / 100.0

    # -- public interface (mirrors MatchStore) --------------------------------

    def enqueue(
        self,
        address: str,
        stake: float,
        rtt_ms: float | None = None,
        target: str | None = None,
    ) -> Match:
        addr = address.lower()
        # Audit M27: the address a friend challenge is reserved for ("" = open).
        reserved_for = (target or "").lower()
        # Audit H1 / CRITICAL-2: the ping cap applies on the durable backend too.
        check_ping_cap(rtt_ms)
        live = self.player_match.get(addr)
        if live:
            m = self.local.matches.get(live)
            if m and m.status in ("waiting", "active"):
                return m
            self.player_match.pop(addr, None)
        queue_ref = self._queue_ref(stake)

        def _txn_body(transaction: Any) -> Match | None:
            snap = queue_ref.get(transaction=transaction)
            data = (snap.to_dict() or {}) if snap.exists else {}
            # Load every live waiting slot (dangling/paired slots are dropped).
            loaded: list[tuple[dict[str, Any], Match]] = []
            for entry in _queue_entries(data):
                msnap = self._match_ref(str(entry["matchId"])).get(transaction=transaction)
                if not msnap.exists:
                    continue
                m = _match_from_doc(msnap.to_dict())
                if m.status != "waiting":
                    continue
                loaded.append((entry, m))

            # Idempotent re-poll: the caller already owns a waiting slot. Without
            # this branch the slot was stolen from under them and every poll
            # minted an orphan match.
            for _entry, m in loaded:
                if addr in m.players:
                    transaction.set(queue_ref, {"waiting": [e for e, _ in loaded]})
                    return m

            # Audit CRITICAL-2: the SAME pairing decision the memory backend
            # uses — ping cap, rating band and closest-connection preference all
            # apply here, because production runs THIS path.
            chosen = choose_opponent(
                [m for _e, m in loaded],
                addr=addr,
                target=reserved_for,
                rtt_ms=rtt_ms,
                rating_for=self._rating_for,
                now=timebase.now(),
            )
            if chosen is not None:
                chosen.players[addr] = {"address": addr, "joinedAt": timebase.now()}
                chosen.status = "active"
                chosen.joiner = addr
                # Audit #8 F-05: activation instant — the play/grace clock
                # starts at pairing, not queue entry.
                chosen.activated_at = timebase.now()
                if rtt_ms is not None:
                    chosen.min_rtt_ms[addr] = float(rtt_ms)
                transaction.set(self._match_ref(chosen.match_id), _match_to_doc(chosen))
                transaction.set(
                    queue_ref,
                    {"waiting": [e for e, mm in loaded if mm is not chosen]},
                )
                return chosen

            # No compatible opponent: create a fresh waiting match and append a
            # slot for it.
            match_id = secrets.token_hex(16)
            m = Match(
                match_id=match_id,
                stake=stake,
                created_at=timebase.now(),
                players={addr: {"address": addr, "joinedAt": timebase.now()}},
                creator=addr,
                target=reserved_for,
            )
            if rtt_ms is not None:
                m.min_rtt_ms[addr] = float(rtt_ms)
            transaction.set(self._match_ref(match_id), _match_to_doc(m))
            transaction.set(
                queue_ref,
                {"waiting": [e for e, _ in loaded] + [{"matchId": match_id, "target": reserved_for}]},
            )
            return m

        # P0-fix: the decorator MUST come from the imported module (aliased
        # `_firestore`). The old `@firestore.transactional` referenced an
        # undefined name and raised NameError on the very first Firestore
        # enqueue — invisible to CI because every test ran the memory store.
        # Without the real module (unit tests with fake clients) run the body
        # directly so matchmaking stays testable.
        if _FIRESTORE_AVAILABLE:
            _txn_enqueue = _firestore.transactional(_txn_body)  # type: ignore[union-attr]
        else:
            _txn_enqueue = _txn_body

        transaction = self.db.transaction()
        match = _txn_enqueue(transaction)
        assert match is not None
        self.local.put(match)
        self.player_match[addr] = match.match_id
        return match

    def get(self, match_id: str) -> Match:
        # Audit 2026-10-13: `metrics.note_firestore_read` had NO caller, so the
        # "Firestore reads per match" metric (plan item 6.1) reported `None`
        # forever. Count the reads that actually happen.
        metrics.note_firestore_read()
        snap = self._match_ref(match_id).get()
        if not snap.exists:
            raise MatchError("Match not found")
        return _match_from_doc(snap.to_dict())

    def pending_challenges(self, address: str) -> list[dict[str, Any]]:
        """Waiting matches RESERVED for `address` (audit M27 closure).

        Bounded by the number of queue documents (one per allowed stake), not by
        the number of matches.
        """
        addr = address.lower()
        out: list[dict[str, Any]] = []
        for qd in self.db.collection(QUEUE_DOC).stream():
            stake = self._stake_from_doc_id(qd.id)
            for entry in _queue_entries(qd.to_dict() or {}):
                snap = self._match_ref(str(entry["matchId"])).get()
                if not snap.exists:
                    continue
                m = _match_from_doc(snap.to_dict())
                if m.status != "waiting" or (m.target or "") != addr:
                    continue
                out.append({"matchId": m.match_id, "address": m.creator, "stake": stake})
        return out

    def update(self, match_id: str, mutate: Any) -> Any:
        """Transactional read-modify-write (audit #3): the mutation is applied
        to a freshly-read match INSIDE a Firestore transaction, so concurrent
        replicas (or two players hitting different backends) can no longer
        overwrite each other's rounds or settle/sign past one another."""
        db = self.db

        def _txn_body(transaction: Any) -> Any:
            metrics.note_firestore_read()
            snap = self._match_ref(match_id).get(transaction=transaction)
            if not snap.exists:
                raise MatchError("Match not found")
            m = _match_from_doc(snap.to_dict())
            out = mutate(m)
            transaction.set(self._match_ref(match_id), _match_to_doc(m))
            return out

        txn = db.transaction()
        transactional = getattr(_firestore, "transactional", None)
        if transactional is not None:
            return transactional(_txn_body)(txn)
        snap = self._match_ref(match_id).get()
        m = _match_from_doc(snap.to_dict())
        out = mutate(m)
        self._match_ref(match_id).set(_match_to_doc(m))
        return out

    def sweep_expired(self) -> list[Match]:
        """Void unpaired matches; RETURN the active ones that are due to settle.

        Audit H8: see InMemoryStore.sweep_expired — an ACTIVE match past its
        play expiry is a forfeit settlement, not an abandonment.

        Audit #10 (item 10): this previously voided only WAITING matches —
        the memory backend voids expired ACTIVE ones too, so the two backends
        disagreed. Now ACTIVE matches past MATCH_EXPIRY (counted from
        ACTIVATION, audit #8 F-05) are voided here as well, keeping both
        stores consistent. Settled matches are never touched."""
        now = timebase.now()
        due: list[Match] = []
        queue_docs = self.db.collection(QUEUE_DOC).stream()
        seen_match_ids: set[str] = set()
        for qd in queue_docs:
            data = qd.to_dict() or {}
            entries = _queue_entries(data)
            if not entries:
                continue
            # Audit M27 closure: this loop used to rewrite the whole queue
            # document with the surviving slots. That is a non-transactional
            # read-modify-write on shared state, and a concurrent `enqueue`
            # appending a slot between the read and the write was silently
            # dropped — a lost wakeup that stranded a waiting player. The sweep
            # no longer writes the queue document at all: `enqueue` prunes
            # dangling/paired slots itself when it loads them, and
            # `pending_challenges` ignores slots whose match is not waiting. So
            # the slot list self-heals on the next enqueue and nothing depends
            # on the sweep tidying it.
            for entry in entries:
                snap = self._match_ref(str(entry["matchId"])).get()
                if not snap.exists:
                    continue
                m = _match_from_doc(snap.to_dict())
                seen_match_ids.add(m.match_id)
                if m.status == "waiting" and now - m.created_at > QUEUE_EXPIRY_SECONDS:
                    m.status = "void"
                    self._match_ref(m.match_id).set(_match_to_doc(m))
                    continue
                if m.status == "active" and now - m.play_started_at() > MATCH_EXPIRY_SECONDS:
                    due.append(m)  # settle it, do not void it (audit H8)
                    continue

        # Active matches are not always reachable through a queue slot (the
        # slot is cleared on pairing). Scan active-looking docs directly so
        # expired duels never linger 'active' on the durable backend.
        # A subset of active matches is visible via the status index; to stay
        # shard-safe we scan only documents modified in the last few hours
        # would need an index — instead we accept the small scan below: this
        # deployment's match volume is bounded by active play.
        try:
            active_docs = (
                self.db.collection(COLLECTION)
                .where("status", "==", "active")
                .limit(_SWEEP_SCAN_LIMIT)
                .stream()
            )
            scanned = 0
            for doc in active_docs:
                scanned += 1
                if doc.id in seen_match_ids:
                    continue
                m = _match_from_doc(doc.to_dict() or {})
                if m.status == "active" and now - m.play_started_at() > MATCH_EXPIRY_SECONDS:
                    due.append(m)  # settle it, do not void it (audit H8)
            if scanned >= _SWEEP_SCAN_LIMIT:
                # Audit 2026-10-13: an unbounded scan of every active duel grows
                # with the whole live population. The limit keeps the sweep
                # bounded; hitting it means the population exceeded the bound, and
                # that must be VISIBLE rather than silently truncating the sweep.
                self.last_sweep_error = (
                    f"active-match scan hit the {_SWEEP_SCAN_LIMIT}-document limit; "
                    "some expired duels were not swept this pass"
                )
        except Exception as exc:
            # Audit 2026-10-13: this used to `pass` — the same silent-failure
            # class audit H9 closed for the memory backend. A missing index or a
            # permission error made the sweep a no-op that looked healthy.
            self.last_sweep_error = f"active-match scan failed: {exc!r}"
        return due

    def put(self, match: Match) -> None:
        self._match_ref(match.match_id).set(_match_to_doc(match))
        self.local.put(match)

    def sweep_stale_settlements(self) -> list[Match]:
        """Audit #11 C2: re-sign sweep over the DURABLE backend.

        ``_resign_stale_settlements`` used to iterate ``store.memory.matches``
        — the per-REPLICA cache. On Firestore, a settled match written by
        replica A was invisible to replica B's sweep, so if both players
        closed their tabs before claiming, the winner's proof expired and was
        refreshed by nobody (prize unspendable until pure luck re-routed the
        traffic). This scans the COLLECTION itself for settled matches whose
        signed envelope's on-chain deadline has passed and hands them to the
        caller (main.py re-signs inside the store transaction).

        Ordered by settled_at ascending (oldest first) so the freshest
        settlements always make the cut. Best-effort: a missing composite
        index or a transient error returns what was scanned so far."""
        now = timebase.now()
        found: list[Match] = []
        try:
            docs = (
                self.db.collection(COLLECTION)
                .where("status", "==", "settled")
                .order_by("settled_at")
                .limit(100)
                .stream()
            )
            for doc in docs:
                try:
                    m = _match_from_doc(doc.to_dict() or {})
                except Exception:
                    continue
                if m.status != "settled" or not m.signed_settlement:
                    continue
                deadline = int((m.signed_settlement or {}).get("deadline", 0) or 0)
                if deadline and now < deadline:
                    continue  # still spendable — nothing to do
                found.append(m)
        except Exception as exc:
            # Audit H9: this used to be a bare `pass`. A missing composite index
            # (see firestore.indexes.json) raises here, so the durable re-sign
            # sweep — the F-12 prize rescue — silently no-opped in production
            # while still paying for the query. Best-effort must still be LOUD.
            print(f"[store] stale-settlement sweep failed: {exc!r}", file=sys.stderr)
            self.last_sweep_error = repr(exc)[:200]
        return found


def _requires_durable_store() -> bool:
    """True in every deployment that has not explicitly opted out (audit H-06).

    The default is production-like: a deployment opts OUT with PULSAR_ENV=dev.
    `PULSAR_REQUIRE_DURABLE_STORE=0` is the escape hatch for a deliberate
    single-process demo, and it must be set on purpose.
    """
    if os.environ.get("PULSAR_REQUIRE_DURABLE_STORE", "").strip().lower() in ("0", "false", "no"):
        return False
    if str(os.environ.get("PULSAR_ENV", "")).strip().lower() in ("dev", "test", "local", "ci"):
        return False
    return True


class DurableMatchStore:
    """
    Facade with the MatchStore interface used by api/main.py:

      - store/matches live in Firestore when credentials are present
      - writes persist every state transition (put after each mutation)
      - falls back to InMemoryStore when Firestore is unavailable
    """

    def __init__(self, backend: str | None = None) -> None:
        # Phase 6.4: match id -> list of dispute reports.
        self.disputes: dict[str, list[dict]] = {}
        backend = backend or os.environ.get("PULSAR_MATCH_STORE", "auto")
        self.backend_name = "memory"
        self._firestore: Any = None
        # P0-fix: ONE FirestoreStore for the process lifetime. The old code
        # constructed a fresh FirestoreStore (with its own empty player_match
        # map and cache) for EVERY enqueue/get/put, so the idempotent re-poll
        # logic never engaged across requests and post-activation re-polls
        # minted orphan waiting matches.
        self._fs_store: Any = None
        # Original (un-hooked) engine functions, injected by
        # install_persistence() so transactional mutations never double-save.
        self._orig_engine: Any = None
        self.memory = InMemoryStore()

        if backend in ("firestore", "auto") and _FIRESTORE_AVAILABLE:
            project = os.environ.get("FIRESTORE_PROJECT_ID") or None
            try:
                key_path = os.environ.get("FIRESTORE_CREDENTIALS_JSON", "")
                if key_path and os.path.exists(key_path):
                    self._firestore = _firestore.Client.from_service_account_json(
                        key_path, project=project
                    )
                else:
                    # Application Default Credentials (Cloud Run / Freebuff)
                    self._firestore = _firestore.Client(project=project)
                # Audit CRITICAL-2: hand the durable store the same rating
                # lookup the memory backend uses, so the pairing band applies on
                # the path production actually runs.
                self._fs_store = FirestoreStore(
                    self._firestore, rating_for=self.memory.rating_for
                )
                self.backend_name = "firestore"
            except Exception as exc:  # noqa: BLE001
                # Audit 2026-10-14 (found by the phase-10 E2E): this swallowed
                # the reason. A deployment that asked for `firestore` and got
                # `memory` went on serving traffic — every match in one process,
                # nothing durable, and the only signal was a health field an
                # operator had to know to look at. Say it out loud.
                print(
                    f"[store] PULSAR_MATCH_STORE={backend} but the Firestore client "
                    f"could not be created ({type(exc).__name__}: {exc}); "
                    "FALLING BACK TO MEMORY — matches will not persist.",
                    file=sys.stderr,
                )
                self._firestore = None
                self._fs_store = None
                self.backend_name = "memory"
                # Audit H-06 (2026-10-22): in a production-like deployment the
                # fallback is not a survivable mode — waiters and their matches
                # would live in ONE replica's memory, so a re-poll routed to
                # another replica answers "match not found" while the stake is
                # already in escrow. Refuse to boot instead of serving traffic
                # that cannot keep the promise the contract makes.
                if _requires_durable_store():
                    raise RuntimeError(
                        "Refusing to start: the durable match store is required "
                        f"(PULSAR_MATCH_STORE={backend}) but Firestore could not be "
                        f"reached ({type(exc).__name__}: {exc}). Monetary play "
                        "cannot run on per-replica memory. Fix credentials, or set "
                        "PULSAR_ENV=dev for a local run."
                    ) from exc
        elif backend == "firestore":
            raise RuntimeError(
                "PULSAR_MATCH_STORE=firestore but google-cloud-firestore is not installed"
            )

    # -- interface ---------------------------------------------------------

    @property
    def durable(self) -> bool:
        return self.backend_name == "firestore"

    def enqueue(
        self,
        address: str,
        stake: float,
        rtt_ms: float | None = None,
        target: str | None = None,
    ) -> Match:
        # Audit H1: `rtt_ms` must be forwarded. It was missing here, so the ping
        # cap and the RTT record were silently bypassed on the DURABLE store —
        # i.e. in production, while the in-memory store (used by unit tests)
        # enforced them. A gate that only exists in tests is not a gate.
        # Audit M27: `target` is forwarded for the same reason — a friend
        # challenge that only works on the memory backend is not a feature.
        if self._fs_store is not None:
            match = self._fs_store.enqueue(address, stake, rtt_ms, target)
            self._mirror(match)
            return match
        return self.memory.enqueue(address, stake, rtt_ms, target)

    def record_dispute(self, match_id: str, report: dict) -> None:
        """Attach a player's dispute report to a match (phase 6.4).

        Kept on the match so an operator inspecting it finds the report
        alongside the state it is about. In-process for now: persisting reports
        durably needs their own collection, which is a separate change.
        """
        self.disputes.setdefault(match_id, []).append(report)

    def rating_for(self, address: str) -> float:
        """Audit H23: the durable store keeps ratings in the in-memory backend.

        Ratings are per-player aggregates, not per-match state, so they do not
        belong in the match documents. Persisting them durably is a phase-6
        concern (they need their own collection and a migration); until then
        they are process-local and reset on restart, which is honest for a
        feature that is not yet live.
        """
        return self.memory.rating_for(address)

    def apply_rating_result(self, winner: str, loser: str) -> None:
        self.memory.apply_rating_result(winner, loser)

    def get(self, match_id: str) -> Match:
        if self._fs_store is not None:
            match = self._fs_store.get(match_id)
            self._mirror(match)
            return match
        return self.memory.get(match_id)

    def recent_matches(self, limit: int = 2000) -> list[Match]:
        """Recent matches, newest first — the input to the analytics snapshot.

        Reads the durable collection: analytics is about what was PERSISTED, and
        the in-process cache only holds what this process touched. A store outage
        returns an empty list and the caller reports `available: false` rather
        than pretending the numbers are zero.
        """
        if self._fs_store is None:
            return list(self.memory.matches.values())[:limit]
        out: list[Match] = []
        for snap in self._fs_store.db.collection(COLLECTION).stream():
            try:
                out.append(_match_from_doc(snap.to_dict() or {}))
            except Exception:  # noqa: BLE001 — one unreadable doc must not kill the snapshot
                continue
        out.sort(key=lambda m: m.created_at, reverse=True)
        return out[:limit]

    def settled_matches(self, limit: int = 50) -> list[Match]:
        """Settled matches, newest first — the public settlement log (G11).

        Reads the durable collection directly: the log is about what was
        PERSISTED, and the in-process cache only holds what this process has
        touched. An empty result on a store outage is the honest answer; the
        endpoint reports `available: false` rather than pretending.
        """
        if self._fs_store is None:
            return [
                m
                for m in self.memory.matches.values()
                if m.status == "settled" and m.signed_settlement
            ][:limit]
        out: list[Match] = []
        for snap in self._fs_store.db.collection(COLLECTION).stream():
            data = snap.to_dict() or {}
            if data.get("status") != "settled" or not data.get("signed_settlement"):
                continue
            out.append(_match_from_doc(data))
        out.sort(key=lambda m: m.settled_at, reverse=True)
        return out[:limit]

    def identity(self, match_id: str) -> Match:
        """The match's IMMUTABLE identity (players, stake, creator) — cheaply.

        Audit 2026-10-14 (plan item 10.3, reads per match measured at 47 against
        a target of <20): the deposit gate ran `get()` before every round
        action, and `update()` then read the match again inside its transaction
        — two Firestore reads per commit/reveal/submit, 37 of a match's 47.

        The gate only needs `stake` and `players`, which are immutable after
        activation (its own docstring says so), and the mirror already holds the
        match after `enqueue`/`get`/`update`. Serving the gate from the mirror
        removes one read per round action WITHOUT weakening the gate: the
        on-chain state it verifies is still read fresh on every call.

        Falls back to a real read whenever the mirror does not have it, so this
        can only ever be a cache hit, never a wrong answer.
        """
        if self._fs_store is not None:
            cached = self.memory.matches.get(match_id)
            if cached is not None and cached.status in ("waiting", "active"):
                return cached
            return self.get(match_id)
        return self.memory.get(match_id)

    def pending_challenges(self, address: str) -> list[dict[str, Any]]:
        """Audit M27 closure: challenges waiting for this address."""
        if self._fs_store is not None:
            return self._fs_store.pending_challenges(address)
        return self.memory.pending_challenges(address)

    def _mirror(self, match: Match) -> None:
        """Refresh the local cache + idempotency map from durable state."""
        self.memory.put(match)
        for addr in match.players:
            self.memory.player_match[addr] = match.match_id

    def sweep_expired(self) -> list[Match]:
        """Void unpaired matches; return the active ones due to settle (H8)."""
        due: list[Match] = []
        if self._fs_store is not None:
            due.extend(self._fs_store.sweep_expired())
        due.extend(self.memory.sweep_expired())
        # The two backends can see the same match; hand each id over once.
        seen: set[str] = set()
        unique: list[Match] = []
        for m in due:
            if m.match_id not in seen:
                seen.add(m.match_id)
                unique.append(m)
        return unique

    def sweep_stale_settlements(self) -> list[Match]:
        """Audit #11 C2: settled matches with an expired envelope, read from
        the DURABLE backend (empty list on the memory backend — the caller's
        own cache IS the full dataset there, the original path still works)."""
        if self._fs_store is not None:
            return self._fs_store.sweep_stale_settlements()
        return []

    def put(self, match: Match) -> None:
        """Persist after a mutation (commit/reveal/submit/settle)."""
        if self._fs_store is not None:
            self._fs_store.put(match)
        self.memory.put(match)

    def update(self, match_id: str, mutate: Any) -> Any:
        """Transactional read-modify-write. ``mutate(m, engine)`` runs against
        a freshly-read match with the ORIGINAL (un-hooked) engine functions,
        so nothing persists outside the transaction. On Firestore this is a
        real transaction (concurrent replicas can no longer clobber each
        other's rounds); in memory it is lock-serialized."""
        eng = self._orig_engine or _default_engine

        def _one_arg(m: Match) -> Any:
            return mutate(m, eng)

        if self._fs_store is not None:
            out = self._fs_store.update(match_id, _one_arg)
            self._mirror_idempotent(match_id)
            return out
        return self.memory.update(match_id, _one_arg)

    def _mirror_idempotent(self, match_id: str) -> None:
        try:
            self._mirror(self._fs_store.get(match_id))
        except MatchError:
            pass

    def player_live_match(self, address: str) -> Match | None:
        """Audit #8 F-13: DURABLE idempotency for matchmaking.

        Previously the address→live-match map lived only in process memory
        (``player_match`` + the local cache), so a re-poll landing on another
        replica (or after a recycle) minted an orphan waiting match that the
        client could then fund twice. Now the mapping is read from Firestore
        itself: any live (waiting|active) match whose doc contains this
        address is returned, regardless of which replica holds the cache.
        """
        addr = address.lower()
        if self._fs_store is None:
            live = self.memory.player_match.get(addr)
            if not live:
                return None
            try:
                return self.memory.get(live)
            except MatchError:
                # Stale map entry (match voided/expunged) — not an error.
                return None
        try:
            docs = (
                self._fs_store.db.collection(COLLECTION)
                .where(f"players.{addr}.address", "==", addr)
                .limit(5)
                .stream()
            )
            candidates = [
                _match_from_doc(d.to_dict())
                for d in docs
                if _match_from_doc(d.to_dict()).status in ("waiting", "active")
            ]
            if not candidates:
                return None
            # Deterministic pick: the most recently activated/created live match.
            candidates.sort(
                key=lambda m: m.activated_at or m.created_at, reverse=True
            )
            return candidates[0]
        except Exception:
            # A query failure must not break matchmaking — fall back to the
            # per-process map (the old behavior) rather than raising.
            live = self.memory.player_match.get(addr)
            if live:
                try:
                    return self.memory.get(live)
                except MatchError:
                    return None
            return None


def install_persistence(store: DurableMatchStore, engine_module: Any) -> None:
    """
    Wire persistence into the engine's module-level mutators: every function
    that mutates a Match (commit/reveal/submit/settle) gets a save hook so
    state survives process recycling. Called once at app startup.
    """
    original_commit = engine_module.commit_intent
    original_reveal = engine_module.reveal_target
    original_submit = engine_module.submit_result
    original_settle = engine_module.settle

    def _save(fn: Callable, *args: Any, **kwargs: Any):
        result = fn(*args, **kwargs)
        match = args[0] if args else None
        if isinstance(match, Match):
            store.put(match)
        return result

    # Audit H1: these wrappers must be SIGNATURE-TRANSPARENT. They used to
    # restate the engine's parameters, so adding one to the engine (H1 added
    # `rtt_ms` to submit_result) made the wrapper reject it — and the failure
    # only appeared when `main` had been imported, i.e. in the full suite but
    # not in a focused run. Forwarding *args/**kwargs cannot drift.
    def commit_intent(*args: Any, **kwargs: Any):
        return _save(original_commit, *args, **kwargs)

    def reveal_target(*args: Any, **kwargs: Any):
        return _save(original_reveal, *args, **kwargs)

    def submit_result(*args: Any, **kwargs: Any):
        return _save(original_submit, *args, **kwargs)

    def settle(*args: Any, **kwargs: Any):
        return _save(original_settle, *args, **kwargs)

    # Transactional mutations: expose the ORIGINAL engine functions to
    # DurableMatchStore.update so mutate(m, engine) runs hook-free inside the
    # transaction and the store persists exactly once, atomically.
    store._orig_engine = type("_OriginalEngine", (), {
        "commit_intent": staticmethod(original_commit),
        "reveal_target": staticmethod(original_reveal),
        "submit_result": staticmethod(original_submit),
        "settle": staticmethod(original_settle),
        "match_completed": staticmethod(engine_module.match_completed),
    })()

    engine_module.commit_intent = commit_intent
    engine_module.reveal_target = reveal_target
    engine_module.submit_result = submit_result
    engine_module.settle = settle


def create_store() -> DurableMatchStore:
    store = DurableMatchStore()
    # Audit CRITICAL-1: expose the ACTIVE store so the modules that need the
    # durable client (auth, economy, the username registry) can find it.
    #
    # They used to resolve it as `getattr(store_module, "_fs_store", None)` — a
    # MODULE attribute that never existed, because `_fs_store` is an INSTANCE
    # attribute of DurableMatchStore. In production every one of them therefore
    # saw "no durable backend": the ledger never wrote, SIWE replay protection
    # and session revocation were per-process only, and the username registry
    # always 503'd. The suite hid it by monkeypatching the module attribute into
    # existence.
    global _active_store
    _active_store = store
    return store


# The store `create_store()` last returned. `main` holds the same object as its
# module-level `store`; this is the seam the other modules read.
_active_store: DurableMatchStore | None = None


def durable_client() -> Any | None:
    """The FirestoreStore the ACTIVE store is using, or None in memory mode."""
    return getattr(_active_store, "_fs_store", None)


def durable_db() -> Any | None:
    """The Firestore client the ACTIVE store is using, or None in memory mode.

    ONE definition for every consumer (audit CRITICAL-1). A second copy of this
    resolution is how the bug survived: each module re-derived it, and each
    re-derivation was wrong in the same way.
    """
    return getattr(durable_client(), "db", None)
