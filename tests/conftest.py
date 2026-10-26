"""PULSAR — shared pytest fixtures (plan item 0.3).

Import-order note: `api/auth.py` and `api/match_engine.py` both raise at import
time when `ORACLE_SIGNING_SECRET` is missing (deliberately — a per-process
random proof key silently splits commit/reveal across replicas). conftest is
imported before any test module, so the environment is seeded here, at module
level, before anything under `api/` is imported.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- environment must exist before `api/` is imported -------------------------
os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)
os.environ.setdefault("ORACLE_CHAIN_ID", "80002")
# Audit H6 inverted the production default: every environment is production-like
# unless it opts out explicitly. The test process must opt out, or importing
# `api/main.py` correctly refuses to start without the full production env.
os.environ.setdefault("PULSAR_ENV", "dev")

API_DIR = Path(__file__).resolve().parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import pytest  # noqa: E402
from eth_account import Account  # noqa: E402

import match_engine as engine  # noqa: E402


# --- backend ------------------------------------------------------------------
@pytest.fixture
def memory_backends(monkeypatch):
    """Pin this test to the in-process backends, whatever the environment says.

    The suite is written in memory mode — `pytest` with no emulator, which is
    what every developer runs and the configuration the coverage floor was
    measured in. CI exports `FIRESTORE_EMULATOR_HOST` for the WHOLE session
    because the `emulator`-marked tests need it, and that silently switched the
    backend under every test that never said which one it wanted.

    The first CI run with the emulator up made that concrete: five tests failed,
    none of them because the product broke. `test_privacy` cleared the memory
    mirror while its sibling module still read Firestore; `test_queue_velocity`
    read a counter an earlier test in the same emulator session had written;
    `test_health_store_signal` asserted "memory backend in tests" in a process
    whose store was Firestore. A test that does not name its backend is a test
    whose meaning is whatever the environment happens to be.

    Requesting this fixture is the way to say it. The `emulator` marker is the
    way to say the opposite.
    """
    import abuse
    import auditlog
    import eligibility
    import integrity
    import limits
    import main as server
    import privacy
    import profiles

    import store as store_module

    for module in (abuse, eligibility, limits):
        monkeypatch.setattr(module, "_firestore_client", lambda: None)
    for module in (auditlog, integrity, privacy, profiles):
        monkeypatch.setattr(module, "_client", lambda: None)
    # `main.store` is the DurableMatchStore INSTANCE built at import time, and it
    # was built from the environment; the attribute is what the limiter and the
    # health probe actually read.
    monkeypatch.setattr(store_module, "durable_db", lambda: None)
    monkeypatch.setattr(server.store, "_fs_store", None, raising=False)
    yield


# --- identities ---------------------------------------------------------------
@pytest.fixture
def player():
    """A funded-looking EVM identity. Address is lowercased, like the server."""
    return Account.create()


@pytest.fixture
def opponent():
    return Account.create()


@pytest.fixture
def addr(player):
    return player.address.lower()


@pytest.fixture
def opp_addr(opponent):
    return opponent.address.lower()


# --- match fixtures -----------------------------------------------------------
@pytest.fixture
def store():
    """A fresh store per test (no cross-test bleed).

    Audit CRITICAL-2: this used to return `engine.MatchStore` — a class
    PRODUCTION NEVER INSTANTIATES (`main.store` is a DurableMatchStore over
    InMemoryStore/FirestoreStore). Every test that "guarded" the ping cap, the
    rating band or the latency compensation therefore exercised a dead class:
    reverting the production behaviour changed nothing. It now returns the
    production class, so those tests guard what actually runs.
    """
    from store import InMemoryStore

    return InMemoryStore()


@pytest.fixture
def waiting_match(store, addr):
    """One player queued, nobody paired yet."""
    return store.enqueue(addr, 1.0)


@pytest.fixture
def active_match(store, addr, opp_addr):
    """Two players paired into an ACTIVE best-of-three."""
    store.enqueue(addr, 1.0)
    return store.enqueue(opp_addr, 1.0)


# --- helpers ------------------------------------------------------------------
@pytest.fixture
def play_round():
    """Play one honest round for `address` and return the engine's verdict.

    `reaction_ms` is the reaction the player really produced; the helper rewinds
    `revealed_at` so the server observes exactly that reaction. This mirrors the
    legacy suites' `wait_out_target`, but is centralised so every test measures
    timing the same way.
    """

    def _play(match, address, index, reaction_ms=250.0, intent=b"intent"):
        import hashlib

        engine.commit_intent(
            match, address, index, "0x" + hashlib.sha256(intent + str(index).encode()).hexdigest()
        )
        target = engine.reveal_target(match, address, index)
        r = match.rounds[address.lower()][index]
        if r.revealed_at:
            r.revealed_at -= (r.target_ms + reaction_ms) / 1000.0
        return engine.submit_result(match, address, index, reaction_ms, target["resultProof"])

    return _play


@pytest.fixture
def clock(monkeypatch):
    """Move the whole server's clock forward without touching match state.

    Plan item 0.5: every wall-clock read in `api/` goes through `timebase.now`
    (and `timebase.now_ms`), so patching those two functions moves time for the
    engine, the store, the oracle, the deposit-gate cache and the rate limiter
    at once. Tests therefore exercise the real timing gates instead of rewinding
    `Round.revealed_at`, which used to mask wrong-origin bugs.
    """
    import timebase

    class _Clock:
        def __init__(self) -> None:
            self.offset = 0.0

        def advance(self, seconds: float) -> None:
            """Move the clock forward by `seconds`."""
            self.offset += seconds

        def rewind(self, seconds: float) -> None:
            """Move the clock backward (rare; for boundary tests)."""
            self.offset -= seconds

        @property
        def value(self) -> float:
            return _real_now() + self.offset

    c = _Clock()
    _real_now = timebase.now

    monkeypatch.setattr(timebase, "now", lambda: _real_now() + c.offset)
    monkeypatch.setattr(timebase, "now_ms", lambda: int((_real_now() + c.offset) * 1000))
    return c


# The rate limiter is keyed by IP and every test shares one TestClient IP, so a
# test that polls the queue a few times can trip a bucket another test needs.
# Clearing the buckets per test is not enough on its own — the Firestore-backed
# path writes asynchronously enough that a clear can lose a race. Raising the
# ceilings for the test process removes the interaction entirely; the tests that
# VERIFY the limiter pass an explicit limit to `_rl_check` and are unaffected.
_RL_LIMIT_NAMES = (
    "RL_AUTH_MAX",
    "RL_VERIFY_MAX",
    "RL_QUEUE_MAX",
    "RL_COMMIT_MAX",
    "RL_ROUND_MAX",
    "RL_SETTLE_MAX",
    "RL_CLAIM_MAX",
    "RL_USERNAME_LOOKUP_MAX",
)


@pytest.fixture(autouse=True)
def _isolate_server_store(monkeypatch):
    """Reset the server's in-process match state around every test.

    `main.store` is a module-level singleton, so a match left WAITING by one
    test is still in the queue bucket when the next test's players enqueue —
    they pair with the previous test's player and get a different match id.
    That surfaced as a confusing "matchId mismatch" in an unrelated test.

    Only touches `main` when it is already imported, so tests that never touch
    the server do not pay for importing it.
    """
    import sys

    server = sys.modules.get("main")
    if server is None:
        yield
        return

    for name in _RL_LIMIT_NAMES:
        if hasattr(server, name):
            monkeypatch.setattr(server, name, 1_000_000)

    def _clear() -> None:
        mem = server.store.memory
        mem.matches.clear()
        mem.queue.clear()
        mem.player_match.clear()
        # Audit H9 throttles the maintenance sweep to once per
        # SWEEP_MIN_INTERVAL_SECONDS. Without resetting it here, whether a test
        # exercises the sweep depends on how recently another test polled the
        # queue — which made the coverage ratchet wobble by ~2 points between
        # runs. A ratchet must be deterministic.
        if hasattr(server, "_reset_sweep_clock"):
            server._reset_sweep_clock()
        # The rate limiter is keyed by IP, and every test comes from the same
        # TestClient IP — so buckets accumulate across tests and eventually
        # return 429. That surfaced as an INTERMITTENT pytest failure (and, via
        # the aborted run, a coverage number that wobbled by 5 points).
        server._rl_window.clear()
        if hasattr(server, "_rl_fallback_last"):
            server._rl_fallback_last.clear()
        # ...and when the server boots Firestore-backed the limiter uses the
        # `rate_limits` COLLECTION, not `_rl_window` — so clearing the in-process
        # window is not enough. The documents persist in the emulator across
        # tests and the bucket eventually returns 429.
        fs = getattr(server.store, "_fs_store", None)
        if fs is not None:
            try:
                for doc in fs.db.collection("rate_limits").stream():
                    doc.reference.delete()
            except Exception:
                pass  # emulator unavailable: the in-process reset still applies

    _clear()
    yield
    _clear()


# --- "a skip is not coverage" -------------------------------------------------
#
# Audit 2026-10-14: the live-stack gate ran `test_ranked_flow_e2e.py`, the test
# SKIPPED because the server held a stale match, and the gate reported PASS —
# because pytest's exit code does not care about skips. So a gate whose entire
# purpose is "these tests actually run" could pass while running nothing.
#
# With PULSAR_FAIL_ON_SKIP=1 a skipped test is reported as a FAILURE, at report
# time — `pytest_sessionfinish` is too late, because the exit code is taken from
# the terminal reporter. It is opt-in: most gates have legitimate skips (chain
# tests without anvil, the refund module by design); only the gates that claim
# execution turn it on.
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):  # type: ignore[no-untyped-def]
    # A hookwrapper MUST yield exactly once, whatever it decides — returning
    # early made pytest raise INTERNALERROR (exit 3) on every ordinary run.
    outcome = yield
    if os.environ.get("PULSAR_FAIL_ON_SKIP") != "1":
        return
    report = outcome.get_result()
    if report.skipped:
        reason = getattr(report, "wasxfail", "") or report.longrepr
        report.outcome = "failed"
        report.longrepr = (
            f"SKIPPED, and PULSAR_FAIL_ON_SKIP=1 — a skip is not coverage.\n{reason}"
        )


# --- eligibility: attested by default in tests --------------------------------
#
# Plan item 11.3/G2 put a server-side eligibility gate on `/api/queue`. That is
# correct for production and wrong for ~20 tests that are about something else —
# they queue a match to test the sweep, the ledger, settlement, and so on, and do
# not care about eligibility. Without this they all get 403 and stop testing what
# they name.
#
# So eligibility is ATTESTED BY DEFAULT in the test process, and the gate's own
# tests (`tests/integration/test_eligibility_gate.py`) opt out with the marker
# below so they exercise the real thing. A bypass that is invisible is a lie;
# this one is named, documented, and has a test that proves the gate still refuses
# when it is not applied.
@pytest.fixture(autouse=True)
def _eligibility_attested(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.node.get_closest_marker("real_eligibility"):
        return
    try:
        import eligibility  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(eligibility, "attested", lambda _address: True)
    monkeypatch.setattr(eligibility, "require", lambda _address: None)
