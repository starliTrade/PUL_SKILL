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
    """A fresh in-memory match store per test (no cross-test bleed)."""
    return engine.MatchStore()


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


@pytest.fixture(autouse=True)
def _isolate_server_store():
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

    def _clear() -> None:
        mem = server.store.memory
        mem.matches.clear()
        mem.queue.clear()
        mem.player_match.clear()

    _clear()
    yield
    _clear()
