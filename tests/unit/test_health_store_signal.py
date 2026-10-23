"""H-17 — /api/health must not call "configured" the same thing as "working".

`matchStore: "firestore"` was read everywhere (docs, incident playbook, this
repository's own go-live checklist) as proof of durability. It never was: the
value comes from a successful *constructor* call, and google-cloud-firestore
does no I/O there. Measured on 2026-10-23 with no emulator running:

    client constructed OK   -> health: matchStore "firestore"
    first read              -> hung for 60 s (get(timeout=3) does not bound it,
                               the retry policy outlives the per-call timeout)

So a deployment with a typo in the project id, revoked IAM or a blocked egress
looked perfectly durable, right up to the first write.

The fix is three things, and each one is pinned here:
  * counters that move only on a real durable write (evidence, not config);
  * a tri-state `writable` (None = never exercised, not "fine");
  * an opt-in `?deep=1` round-trip whose deadline is wall-clock, so a dead
    database cannot make the health endpoint hang.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import store as store_mod  # noqa: E402


class _FailingFs:
    """A durable backend that accepts the write and then fails, like an IAM deny."""

    def put(self, match: Any) -> None:
        raise RuntimeError("PERMISSION_DENIED: caller lacks datastore.user")

    def update(self, match_id: str, mutate: Any) -> Any:
        raise RuntimeError("PERMISSION_DENIED: caller lacks datastore.user")

    def enqueue(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError("PERMISSION_DENIED: caller lacks datastore.user")


class _WorkingFs:
    def __init__(self) -> None:
        self.put_calls = 0

    def put(self, match: Any) -> None:
        self.put_calls += 1


def _durable_store(monkeypatch: pytest.MonkeyPatch, fs: Any) -> Any:
    """A DurableMatchStore that BELIEVES it is on Firestore, with `fs` as driver."""
    s = store_mod.DurableMatchStore(backend="memory")
    s.backend_name = "firestore"
    s._fs_store = fs
    return s


# --- evidence, not configuration ---------------------------------------------


def test_memory_backend_claims_nothing_it_has_not_done() -> None:
    s = store_mod.DurableMatchStore(backend="memory")
    stats = s.write_stats()

    assert stats["backend"] == "memory"
    assert stats["durable"] is False
    # The whole point: "no durable write was ever attempted" must not read as
    # True. A boolean would have to pick one, and either choice is a lie.
    assert stats["writable"] is None
    assert stats["writes"] == 0 and stats["failures"] == 0
    assert stats["lastError"] == ""


def test_a_durable_store_that_never_wrote_is_still_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _durable_store(monkeypatch, _WorkingFs())
    assert s.durable is True
    assert s.write_stats()["writable"] is None, "construction is not evidence of durability"


def test_a_successful_durable_write_turns_writable_true(monkeypatch: pytest.MonkeyPatch) -> None:
    fs = _WorkingFs()
    s = _durable_store(monkeypatch, fs)
    match = s.memory.enqueue("0x" + "11" * 20, stake=1.0)

    s.put(match)

    stats = s.write_stats()
    assert fs.put_calls == 1
    assert stats["writes"] == 1 and stats["failures"] == 0
    assert stats["writable"] is True
    assert isinstance(stats["lastOkAt"], float)


def test_a_failed_durable_write_turns_writable_false_and_keeps_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _durable_store(monkeypatch, _FailingFs())
    match = s.memory.enqueue("0x" + "22" * 20, stake=1.0)

    with pytest.raises(RuntimeError):
        s.put(match)

    stats = s.write_stats()
    assert stats["failures"] == 1 and stats["writes"] == 0
    assert stats["writable"] is False
    assert "PERMISSION_DENIED" in stats["lastError"]
    assert isinstance(stats["lastFailureAt"], float)


def test_a_failure_after_a_success_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recency matters: a store that worked an hour ago and is failing now is down."""
    fs = _WorkingFs()
    s = _durable_store(monkeypatch, fs)
    match = s.memory.enqueue("0x" + "33" * 20, stake=1.0)
    s.put(match)
    assert s.write_stats()["writable"] is True

    s._fs_store = _FailingFs()
    with pytest.raises(RuntimeError):
        s.put(match)

    stats = s.write_stats()
    assert stats["writes"] == 1 and stats["failures"] == 1
    assert stats["writable"] is False


def test_the_error_string_is_truncated_because_the_endpoint_is_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Noisy:
        def put(self, match: Any) -> None:
            raise RuntimeError("x" * 5000)

    s = _durable_store(monkeypatch, _Noisy())
    match = s.memory.enqueue("0x" + "44" * 20, stake=1.0)
    with pytest.raises(RuntimeError):
        s.put(match)

    assert len(s.write_stats()["lastError"]) <= 200


# --- the deep probe is bounded ------------------------------------------------


def test_deep_probe_is_skipped_off_durable(monkeypatch: pytest.MonkeyPatch) -> None:
    s = store_mod.DurableMatchStore(backend="memory")
    out = s.probe(50)
    assert out["checked"] is False
    assert out["reason"] == "no durable backend configured"
    # `ok` must be None, not True: nothing was checked, so nothing is known.
    # A monitoring rule that greps `ok` must not read "no database configured"
    # as "healthy" — that is the same mistake as H-17, one field over.
    assert out["ok"] is None


def test_deep_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Doc:
        def get(self, timeout: float | None = None) -> Any:
            return object()

    class _Coll:
        def document(self, _name: str) -> _Doc:
            return _Doc()

    class _Db:
        def collection(self, _name: str) -> _Coll:
            return _Coll()

    s = _durable_store(monkeypatch, _WorkingFs())
    s._firestore = _Db()

    out = s.probe(500)
    assert out["checked"] is True and out["ok"] is True
    assert out["latencyMs"] >= 0


def test_deep_probe_reports_a_driver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Db:
        def collection(self, _name: str) -> Any:
            raise RuntimeError("401 unauthenticated")

    s = _durable_store(monkeypatch, _WorkingFs())
    s._firestore = _Db()

    out = s.probe(500)
    assert out["checked"] is True and out["ok"] is False
    assert "401" in out["error"]


def test_deep_probe_cannot_hang_the_health_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 60-second hang, turned into a bounded answer.

    A driver that ignores its own timeout (or blocks in DNS) must not hold
    /api/health open. The deadline is wall-clock in a daemon thread.
    """
    release = __import__("threading").Event()

    class _Doc:
        def get(self, timeout: float | None = None) -> Any:
            release.wait(10)  # ignores `timeout`, like the real client did
            return object()

    class _Coll:
        def document(self, _name: str) -> _Doc:
            return _Doc()

    class _Db:
        def collection(self, _name: str) -> _Coll:
            return _Coll()

    s = _durable_store(monkeypatch, _WorkingFs())
    s._firestore = _Db()

    started = time.monotonic()
    out = s.probe(200)
    elapsed = time.monotonic() - started
    release.set()

    assert out["ok"] is False
    assert "no answer within 200 ms" in out["error"]
    assert elapsed < 2.0, f"probe held the caller for {elapsed:.1f}s"


# --- what the endpoint actually serves ---------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


def test_health_carries_the_store_block_but_not_the_probe(client: TestClient) -> None:
    body = client.get("/api/health").json()

    assert "store" in body
    for key in ("backend", "durable", "writes", "failures", "writable", "lastError"):
        assert key in body["store"], f"health lost store.{key}"
    # The cheap path stays cheap: no round-trip on the liveness probe.
    assert "probe" not in body["store"]


def test_deep_health_adds_the_probe(client: TestClient) -> None:
    body = client.get("/api/health?deep=1").json()
    probe = body["store"]["probe"]
    assert probe["checked"] is False  # memory backend in tests
    assert probe["ok"] is None


def test_match_store_and_store_backend_cannot_disagree(client: TestClient) -> None:
    """Two fields describing the same thing must not tell two stories."""
    body = client.get("/api/health").json()
    assert body["matchStore"] == body["store"]["backend"]
    assert body["store"]["durable"] == (body["matchStore"] == "firestore")


# --- H-23: the deep probe must not be free ------------------------------------
#
# `?deep=1` is unauthenticated and performs one BILLED Firestore read inside a
# fresh daemon thread. Before this, nothing limited it: the one route an attacker
# is certain exists could be looped as a cost amplifier and a thread factory.


@pytest.fixture
def counted_probe(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def _probe(timeout_ms: int = 1500) -> dict[str, Any]:
        calls.append(timeout_ms)
        return {"checked": True, "ok": True, "latencyMs": 1, "error": ""}

    monkeypatch.setattr(server.store, "probe", _probe)
    monkeypatch.setattr(server, "_deep_probe_cache", {"at": -1e9, "payload": None})
    monkeypatch.setattr(server, "_rl_window", {}, raising=False)
    return calls


def test_the_deep_probe_is_cached_within_the_window(
    client: TestClient, counted_probe: list[int]
) -> None:
    for _ in range(3):
        r = client.get("/api/health?deep=1")
        assert r.status_code == 200, r.text
    assert len(counted_probe) == 1, "a monitor polling every second must not cost a read per poll"


def test_the_cached_probe_expires(client: TestClient, counted_probe: list[int], monkeypatch) -> None:
    client.get("/api/health?deep=1")
    import timebase  # noqa: PLC0415

    later = timebase.now() + server.HEALTH_PROBE_CACHE_SECONDS + 1
    monkeypatch.setattr(timebase, "now", lambda: later)
    client.get("/api/health?deep=1")
    assert len(counted_probe) == 2


def test_the_deep_probe_is_rate_limited_per_ip(
    client: TestClient, counted_probe: list[int]
) -> None:
    codes = [client.get("/api/health?deep=1").status_code for _ in range(server.RL_HEALTH_DEEP_MAX + 1)]
    assert codes[-1] == 429, f"the deep probe is unlimited: {codes}"
    assert all(c == 200 for c in codes[:-1])
    last = client.get("/api/health?deep=1")
    assert last.status_code == 429
    assert last.headers.get("Retry-After"), "a 429 without Retry-After is not a contract"


def test_the_plain_health_endpoint_stays_free(client: TestClient, counted_probe: list[int]) -> None:
    """The liveness probe must never be rate limited — an orchestrator that gets
    429 on its health check restarts a healthy container."""
    for _ in range(server.RL_HEALTH_DEEP_MAX * 3):
        assert client.get("/api/health").status_code == 200
    assert counted_probe == []
