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
    """Advance the engine's clock without touching match state.

    Plan item 0.5 replaces the engine's direct `time.time()` calls with a single
    `match_engine.now()` seam. Until that lands, this fixture patches the module
    attribute `time` inside match_engine so tests can move time forward honestly
    instead of rewinding `revealed_at`.
    """

    class _Clock:
        def __init__(self):
            self.offset = 0.0

        def advance(self, seconds: float) -> None:
            self.offset += seconds

    c = _Clock()

    real_time = engine.time

    class _Shifted:
        @staticmethod
        def time():
            return real_time.time() + c.offset

    monkeypatch.setattr(engine, "time", _Shifted)
    return c
