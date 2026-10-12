"""C1 regression — the Firestore-backed rate limiter must actually persist.

Audit finding C1: `api/main.py::_rl_check` opened a transaction with
`fs.db.transaction()` but never began it and never committed it. Reading through
an un-begun transaction raises `ValueError(INACTIVE_TXN)`, which the broad
`except Exception: pass` swallowed — so every call silently fell through to the
per-process limiter. The "distributed" limiter never existed: on N replicas the
effective ceiling was N x limit, and every restart cleared the window.

The pre-existing assertion in `scripts/test_firestore_integration.py`
("distributed rate limiter enforces over REAL Firestore") passes either way,
because the in-process fallback also raises 429. It cannot tell the two paths
apart. These tests assert the OBSERVABLE that only the real path produces: the
`rate_limits` document in Firestore.

Run with the emulator:  FIRESTORE_EMULATOR_HOST=127.0.0.1:8081
"""

from __future__ import annotations

import pytest

# C1 regression suite (MASTER-PLAN phase 1). These were the red baseline:
# `strict=True` means an unexpected PASS fails the suite, so the marker cannot
# be forgotten once the fix lands — remove it in the same commit as the fix.
pytestmark = pytest.mark.emulator

firestore = pytest.importorskip("google.cloud.firestore")

PROJECT = "demo-pulsar"


@pytest.fixture
def fs_db():
    """A Firestore client bound to the emulator, or skip when it is absent."""
    import os

    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set — start the emulator (scripts/start_emulator.sh)")
    try:
        client = firestore.Client(project=PROJECT)
        client.collection("_probe").document("ping").set({"ok": True})
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.skip(f"Firestore emulator unreachable at {host}: {exc}")
    return client


@pytest.fixture
def firestore_backed_store(fs_db, monkeypatch):
    """Wire the server's rate limiter onto a real Firestore store.

    `main._rl_check` looks up `store._fs_store` at call time, so injecting one
    here exercises the exact production code path without re-importing main.
    """
    import store as store_module
    from store import FirestoreStore

    monkeypatch.setattr(store_module, "_fs_store", FirestoreStore(fs_db), raising=False)
    return store_module


def _clear_window(server):
    """Empty the in-process fallback so a pass cannot come from it."""
    server._rl_window.clear()


def test_rate_limit_document_is_written_to_firestore(fs_db, firestore_backed_store):
    """The counter must land in Firestore — not only in process memory."""
    import main as server

    _clear_window(server)
    bucket, subject, limit = "c1-probe", "0x" + "c1" * 20, 5
    doc_id = f"rl:{bucket}:{subject.lower()}"
    fs_db.collection("rate_limits").document(doc_id).delete()

    for _ in range(3):
        server._rl_check(bucket, subject, limit)

    snap = fs_db.collection("rate_limits").document(doc_id).get()
    assert snap.exists, (
        "no rate_limits document was written — the Firestore limiter is not "
        "persisting (audit C1: un-begun/uncommitted transaction)"
    )
    assert int((snap.to_dict() or {}).get("count", 0)) >= 3


def test_window_is_shared_across_instances(fs_db, firestore_backed_store):
    """A second replica must CONTINUE the same window, not restart it.

    Asserted on the Firestore document, not on the 429: the in-process fallback
    also returns 429, so a status-code assertion cannot distinguish a working
    distributed limiter from a dead one (that is exactly how the original bug
    stayed hidden).
    """
    import main as server

    bucket, subject, limit = "c1-shared", "0x" + "c2" * 20, 5
    doc_id = f"rl:{bucket}:{subject.lower()}"
    fs_db.collection("rate_limits").document(doc_id).delete()

    _clear_window(server)
    for _ in range(3):
        server._rl_check(bucket, subject, limit)

    first = fs_db.collection("rate_limits").document(doc_id).get()
    assert first.exists, "replica A wrote nothing to Firestore (audit C1)"
    count_a = int((first.to_dict() or {}).get("count", 0))

    # Simulate a different replica: brand-new in-process state, same Firestore.
    _clear_window(server)
    for _ in range(2):
        server._rl_check(bucket, subject, limit)

    second = fs_db.collection("rate_limits").document(doc_id).get()
    count_b = int((second.to_dict() or {}).get("count", 0))
    assert count_b > count_a, (
        f"the second replica restarted the window instead of continuing it "
        f"(count {count_a} -> {count_b}) — the limiter is per-process, not distributed"
    )


def test_limiter_does_not_silently_fall_back(fs_db, firestore_backed_store):
    """A Firestore hiccup must be visible, not silently downgrade the limiter.

    Audit C1's root cause was `except Exception: pass`. The fix must count
    fallbacks so a dead distributed limiter shows up in monitoring.
    """
    import main as server

    assert hasattr(server, "_rl_fallback_count"), (
        "the limiter has no fallback counter — a silent downgrade to per-process "
        "limiting would be invisible in production (audit C1)"
    )
    _clear_window(server)
    before = server._rl_fallback_count
    server._rl_check("c1-fallback", "0x" + "c3" * 20, 5)
    assert server._rl_fallback_count == before, "a healthy Firestore path must not fall back"
