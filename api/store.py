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
import threading
import time
from typing import Any, Callable, Optional

from match_engine import (
    MATCH_EXPIRY_SECONDS,
    QUEUE_EXPIRY_SECONDS,
    ROUND_EXPIRY_SECONDS,
    Match,
    MatchError,
    Round,
)
import match_engine as _default_engine  # engine fns for transactional mutations

try:  # optional dependency — absent in local dev until credentials exist
    from google.cloud import firestore as _firestore  # type: ignore
    from google.cloud.firestore_v1.transaction import Transaction  # type: ignore

    _FIRESTORE_AVAILABLE = True
except Exception:  # pragma: no cover
    _FIRESTORE_AVAILABLE = False

COLLECTION = "pulsar_matches"
QUEUE_DOC = "pulsar_queue"


def _round_to_doc(r: Round) -> dict[str, Any]:
    return {
        "index": r.index,
        "commit_hash": r.commit_hash,
        "commit_at": r.commit_at,
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


def _match_to_doc(m: Match) -> dict[str, Any]:
    return {
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
    }


def _match_from_doc(d: dict[str, Any]) -> Match:
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
    m.creator = d.get("creator", "") or next(iter(m.players), "")
    # Audit #5: restore joiner; derive it for legacy docs (2nd player).
    m.joiner = d.get("joiner", "") or (
        list(m.players)[1] if len(m.players) > 1 else ""
    )
    m.rounds = {
        addr: {int(idx): _round_from_doc(r) for idx, r in per_player.items()}
        for addr, per_player in (d.get("rounds", {}) or {}).items()
    }
    m.status = d.get("status", "waiting")
    m.winner = d.get("winner", "")
    m.settled_at = float(d.get("settled_at", 0.0))
    m.signed_settlement = d.get("signed_settlement")
    return m


class InMemoryStore:
    """The P1 store — used as fallback and as the local cache layer."""

    def __init__(self) -> None:
        self.matches: dict[str, Match] = {}
        self.queue: dict[float, list[str]] = {}
        # address -> live (waiting|active) match id (idempotent enqueue).
        self.player_match: dict[str, str] = {}
        self._lock = threading.Lock()

    def enqueue(self, address: str, stake: float) -> Match:
        addr = address.lower()
        with self._lock:
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
                m.joiner = addr
                # Audit #8 F-05: the PLAY clock starts when the joiner pairs,
                # not when the creator queued.
                m.activated_at = time.time()
                bucket.remove(other)
                self.player_match[addr] = m.match_id
                return m
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

    def sweep_expired(self) -> None:
        now = time.time()
        for mid in list(self.matches):
            m = self.matches[mid]
            if m.status == "waiting" and now - m.created_at > QUEUE_EXPIRY_SECONDS:
                m.status = "void"
            elif (
                m.status == "active"
                and now - m.play_started_at() > MATCH_EXPIRY_SECONDS
            ):
                m.status = "void"
        for stake, bucket in list(self.queue.items()):
            self.queue[stake] = [
                mid for mid in bucket
                if mid in self.matches and self.matches[mid].status == "waiting"
            ]

    def put(self, match: Match) -> None:
        with self._lock:
            self.matches[match.match_id] = match


class FirestoreStore:
    """
    Durable store. Matchmaking uses a per-stake queue document holding the
    oldest waiting match id; pairing happens inside a Firestore transaction,
    so concurrent enqueues can never double-match or lose a pairing.
    """

    def __init__(self, client: Any) -> None:
        self.db = client
        self.local = InMemoryStore()  # write-through cache for hot reads
        # address -> live (waiting|active) match id for idempotent re-polls.
        self.player_match: dict[str, str] = {}

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

    def enqueue(self, address: str, stake: float) -> Match:
        addr = address.lower()
        live = self.player_match.get(addr)
        if live:
            m = self.local.matches.get(live)
            if m and m.status in ("waiting", "active"):
                return m
            self.player_match.pop(addr, None)
        queue_ref = self._queue_ref(stake)

        def _txn_body(transaction: Any) -> Optional[Match]:
            snap = queue_ref.get(transaction=transaction)
            waiting_id = (snap.to_dict() or {}).get("waitingMatchId") if snap.exists else None
            if waiting_id:
                mref = self._match_ref(str(waiting_id))
                msnap = mref.get(transaction=transaction)
                if msnap.exists:
                    m = _match_from_doc(msnap.to_dict())
                    if m.status == "waiting" and addr not in m.players:
                        m.players[addr] = {"address": addr, "joinedAt": time.time()}
                        m.status = "active"
                        m.joiner = addr
                        # Audit #8 F-05: activation instant — the play/grace
                        # clock starts at pairing, not queue entry.
                        m.activated_at = time.time()
                        transaction.set(mref, _match_to_doc(m))
                        transaction.set(queue_ref, {"waitingMatchId": None})
                        return m
                    if addr in m.players:
                        # Idempotent re-poll: the caller IS this waiting match's
                        # creator. Without this branch the queue slot was stolen
                        # from under them and every poll minted an orphan match.
                        transaction.set(queue_ref, {"waitingMatchId": waiting_id})
                        return m
            # No opponent: create a fresh waiting match and claim the queue slot.
            match_id = secrets.token_hex(16)
            m = Match(
                match_id=match_id,
                stake=stake,
                created_at=time.time(),
                players={addr: {"address": addr, "joinedAt": time.time()}},
                creator=addr,
            )
            transaction.set(self._match_ref(match_id), _match_to_doc(m))
            transaction.set(queue_ref, {"waitingMatchId": match_id})
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
        snap = self._match_ref(match_id).get()
        if not snap.exists:
            raise MatchError("Match not found")
        return _match_from_doc(snap.to_dict())

    def update(self, match_id: str, mutate: Any) -> Any:
        """Transactional read-modify-write (audit #3): the mutation is applied
        to a freshly-read match INSIDE a Firestore transaction, so concurrent
        replicas (or two players hitting different backends) can no longer
        overwrite each other's rounds or settle/sign past one another."""
        db = self.db

        def _txn_body(transaction: Any) -> Any:
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

    def sweep_expired(self) -> None:
        """Void expired matches and clear stale queue slots (best effort).

        Audit #10 (item 10): this previously voided only WAITING matches —
        the memory backend voids expired ACTIVE ones too, so the two backends
        disagreed. Now ACTIVE matches past MATCH_EXPIRY (counted from
        ACTIVATION, audit #8 F-05) are voided here as well, keeping both
        stores consistent. Settled matches are never touched."""
        now = time.time()
        queue_docs = self.db.collection(QUEUE_DOC).stream()
        seen_match_ids: set[str] = set()
        for qd in queue_docs:
            data = qd.to_dict() or {}
            waiting_id = data.get("waitingMatchId")
            if not waiting_id:
                continue
            snap = self._match_ref(str(waiting_id)).get()
            if not snap.exists:
                qd.reference.set({"waitingMatchId": None})
                continue
            m = _match_from_doc(snap.to_dict())
            seen_match_ids.add(m.match_id)
            if m.status == "waiting" and now - m.created_at > QUEUE_EXPIRY_SECONDS:
                m.status = "void"
                self._match_ref(m.match_id).set(_match_to_doc(m))
                qd.reference.set({"waitingMatchId": None})
            elif (
                m.status == "active"
                and now - m.play_started_at() > MATCH_EXPIRY_SECONDS
            ):
                m.status = "void"
                self._match_ref(m.match_id).set(_match_to_doc(m))
                qd.reference.set({"waitingMatchId": None})

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
                .stream()
            )
            for doc in active_docs:
                if doc.id in seen_match_ids:
                    continue
                m = _match_from_doc(doc.to_dict() or {})
                if m.status == "active" and now - m.play_started_at() > MATCH_EXPIRY_SECONDS:
                    m.status = "void"
                    self._match_ref(m.match_id).set(_match_to_doc(m))
        except Exception:
            # Sweep is best-effort; a missing composite index must not crash it.
            pass

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
        now = time.time()
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
        except Exception:
            # Sweep is best-effort (a missing index must not crash queueing).
            pass
        return found


class DurableMatchStore:
    """
    Facade with the MatchStore interface used by api/main.py:

      - store/matches live in Firestore when credentials are present
      - writes persist every state transition (put after each mutation)
      - falls back to InMemoryStore when Firestore is unavailable
    """

    def __init__(self, backend: Optional[str] = None) -> None:
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
                self._fs_store = FirestoreStore(self._firestore)
                self.backend_name = "firestore"
            except Exception:
                self._firestore = None
                self._fs_store = None
                self.backend_name = "memory"
        elif backend == "firestore":
            raise RuntimeError(
                "PULSAR_MATCH_STORE=firestore but google-cloud-firestore is not installed"
            )

    # -- interface ---------------------------------------------------------

    @property
    def durable(self) -> bool:
        return self.backend_name == "firestore"

    def enqueue(self, address: str, stake: float) -> Match:
        if self._fs_store is not None:
            match = self._fs_store.enqueue(address, stake)
            self._mirror(match)
            return match
        return self.memory.enqueue(address, stake)

    def get(self, match_id: str) -> Match:
        if self._fs_store is not None:
            match = self._fs_store.get(match_id)
            self._mirror(match)
            return match
        return self.memory.get(match_id)

    def _mirror(self, match: Match) -> None:
        """Refresh the local cache + idempotency map from durable state."""
        self.memory.put(match)
        for addr in match.players:
            self.memory.player_match[addr] = match.match_id

    def sweep_expired(self) -> None:
        if self._fs_store is not None:
            self._fs_store.sweep_expired()
        self.memory.sweep_expired()

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
                .where("players.%s.address" % addr, "==", addr)
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

    def commit_intent(match: Match, address: str, round_index: int, intent_hash: str):
        return _save(original_commit, match, address, round_index, intent_hash)

    def reveal_target(match: Match, address: str, round_index: int):
        return _save(original_reveal, match, address, round_index)

    def submit_result(match: Match, address: str, round_index: int, measured_ms: float, result_proof: str = ""):
        return _save(original_submit, match, address, round_index, measured_ms, result_proof)

    def settle(match: Match):
        return _save(original_settle, match)

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
    return store
