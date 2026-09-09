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

import os
import secrets
import threading
import time
from typing import Any, Callable, Optional

from match_engine import (
    MATCH_EXPIRY_SECONDS,
    ROUND_EXPIRY_SECONDS,
    Match,
    MatchError,
    Round,
)

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
        "submitted_at": r.submitted_at,
        "valid": r.valid,
        "reject_reason": r.reject_reason,
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
    r.submitted_at = float(d.get("submitted_at", 0.0))
    r.valid = bool(d.get("valid", False))
    r.reject_reason = d.get("reject_reason", "")
    return r


def _match_to_doc(m: Match) -> dict[str, Any]:
    return {
        "match_id": m.match_id,
        "stake": m.stake,
        "created_at": m.created_at,
        "players": m.players,
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
        self._lock = threading.Lock()

    def enqueue(self, address: str, stake: float) -> Match:
        addr = address.lower()
        with self._lock:
            bucket = self.queue.setdefault(stake, [])
            for other in list(bucket):
                m = self.matches.get(other)
                if m is None or m.status != "waiting":
                    bucket.remove(other)
                    continue
                if addr in m.players:
                    bucket.remove(other)
                    continue
                m.players[addr] = {"address": addr, "joinedAt": time.time()}
                m.status = "active"
                bucket.remove(other)
                return m
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
        queue_ref = self._queue_ref(stake)

        @firestore.transactional  # type: ignore[name-defined]
        def _txn_enqueue(transaction: Any) -> Optional[Match]:
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
                        transaction.set(mref, _match_to_doc(m))
                        transaction.set(queue_ref, {"waitingMatchId": None})
                        return m
            # No opponent: create a fresh waiting match and claim the queue slot.
            match_id = secrets.token_hex(16)
            m = Match(
                match_id=match_id,
                stake=stake,
                created_at=time.time(),
                players={addr: {"address": addr, "joinedAt": time.time()}},
            )
            transaction.set(self._match_ref(match_id), _match_to_doc(m))
            transaction.set(queue_ref, {"waitingMatchId": match_id})
            return m

        transaction = self.db.transaction()
        match = _txn_enqueue(transaction)
        assert match is not None
        self.local.put(match)
        return match

    def get(self, match_id: str) -> Match:
        snap = self._match_ref(match_id).get()
        if not snap.exists:
            raise MatchError("Match not found")
        return _match_from_doc(snap.to_dict())

    def sweep_expired(self) -> None:
        """Void expired matches and clear stale queue slots (best effort)."""
        now = time.time()
        queue_docs = self.db.collection(QUEUE_DOC).stream()
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
            if m.status == "waiting" and now - m.created_at > MATCH_EXPIRY_SECONDS:
                m.status = "void"
                self._match_ref(m.match_id).set(_match_to_doc(m))
                qd.reference.set({"waitingMatchId": None})

    def put(self, match: Match) -> None:
        self._match_ref(match.match_id).set(_match_to_doc(match))
        self.local.put(match)


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
                self.backend_name = "firestore"
            except Exception:
                self._firestore = None
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
        if self._firestore is not None:
            match = FirestoreStore(self._firestore).enqueue(address, stake)
            self.memory.put(match)
            return match
        return self.memory.enqueue(address, stake)

    def get(self, match_id: str) -> Match:
        if self._firestore is not None:
            match = FirestoreStore(self._firestore).get(match_id)
            self.memory.put(match)
            return match
        return self.memory.get(match_id)

    def sweep_expired(self) -> None:
        if self._firestore is not None:
            FirestoreStore(self._firestore).sweep_expired()
        self.memory.sweep_expired()

    def put(self, match: Match) -> None:
        """Persist after a mutation (commit/reveal/submit/settle)."""
        if self._firestore is not None:
            FirestoreStore(self._firestore).put(match)
        self.memory.put(match)


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

    def submit_result(match: Match, address: str, round_index: int, measured_ms: float):
        return _save(original_submit, match, address, round_index, measured_ms)

    def settle(match: Match):
        return _save(original_settle, match)

    engine_module.commit_intent = commit_intent
    engine_module.reveal_target = reveal_target
    engine_module.submit_result = submit_result
    engine_module.settle = settle


def create_store() -> DurableMatchStore:
    store = DurableMatchStore()
    return store
