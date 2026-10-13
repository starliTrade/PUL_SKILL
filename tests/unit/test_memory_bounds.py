"""M15/M16/M17 — the in-process maps must be bounded and thread-safe.

Audit M15: `onchain._cache` never evicted, so it grew by one entry per match id
ever queried. Audit M16: `_rl_window` never dropped a key, so it grew by one
entry per IP/address ever seen. Audit M17: the auth nonce/revocation sets were
mutated from FastAPI's threadpool with no lock.

These are slow leaks in a long-running server: they do not fail a test suite,
they fail a production process after days of traffic. The plan marked phase 6
closed (4/4) while this item (6.9) was still open.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

import auth  # noqa: E402
import main as server  # noqa: E402
import onchain  # noqa: E402
import timebase  # noqa: E402


# --- M15: the on-chain read cache ---------------------------------------------


def test_the_onchain_cache_is_bounded(monkeypatch):
    onchain._cache.clear()
    monkeypatch.setattr(onchain, "_CACHE_MAX_ENTRIES", 10)
    now = timebase.now()

    for i in range(200):
        onchain._cache_store(f"0x{i:064x}", (None, now + 60, None))

    assert len(onchain._cache) <= 10, (
        f"the on-chain cache grew to {len(onchain._cache)} entries — one per match "
        "id ever queried, forever (audit M15)"
    )


def test_the_onchain_cache_drops_expired_entries_first(monkeypatch):
    onchain._cache.clear()
    monkeypatch.setattr(onchain, "_CACHE_MAX_ENTRIES", 3)
    now = timebase.now()

    # Two already-expired entries and two fresh ones.
    onchain._cache_store("expired-a", (None, now - 1, None))
    onchain._cache_store("expired-b", (None, now - 1, None))
    onchain._cache_store("fresh-a", (None, now + 60, None))
    onchain._cache_store("fresh-b", (None, now + 60, None))

    assert "expired-a" not in onchain._cache
    assert "expired-b" not in onchain._cache
    assert "fresh-b" in onchain._cache


# --- M16: the in-process rate-limit window ------------------------------------


def test_the_rate_limit_window_drops_stale_keys(monkeypatch):
    server._rl_window.clear()
    monkeypatch.setattr(server, "_RL_WINDOW_MAX_KEYS", 5)
    monkeypatch.setattr(server, "RL_QUEUE_MAX", 1_000_000)

    # Many distinct addresses, each seen once — the shape that leaked one key per
    # address forever.
    for i in range(50):
        server._rl_check("queue", f"0x{i:040x}", 1_000_000)

    assert len(server._rl_window) <= 10, (
        f"the rate-limit window holds {len(server._rl_window)} keys — one per "
        "address ever seen, forever (audit M16)"
    )


def test_the_rate_limit_window_still_limits_a_live_key(monkeypatch):
    """The bound must not break the limiter itself."""
    server._rl_window.clear()
    monkeypatch.setattr(server, "_RL_WINDOW_MAX_KEYS", 5)

    for _ in range(3):
        server._rl_check("queue", "0x" + "aa" * 20, 3)

    with pytest.raises(Exception):
        server._rl_check("queue", "0x" + "aa" * 20, 3)


# --- M17: the auth sets are mutated from a threadpool -------------------------


class _SpyLock:
    """A stand-in for the auth lock that records whether it was taken."""

    def __init__(self) -> None:
        self.acquired = 0

    def __enter__(self) -> "_SpyLock":
        self.acquired += 1
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_remember_used_takes_the_auth_lock(monkeypatch):
    spy = _SpyLock()
    monkeypatch.setattr(auth, "_AUTH_LOCK", spy)
    auth._remember_used("nonce-" + str(timebase.now()))
    assert spy.acquired == 1, (
        "the used-nonce set is mutated without the lock — FastAPI runs sync "
        "endpoints in a threadpool (audit M17)"
    )


def test_revoke_session_takes_the_auth_lock(monkeypatch):
    spy = _SpyLock()
    monkeypatch.setattr(auth, "_AUTH_LOCK", spy)
    monkeypatch.setattr(auth, "_durable_backend", lambda: None)
    auth.revoke_session("jti-" + str(timebase.now()))
    assert spy.acquired == 1, (
        "the revoked-jti set is mutated without the lock (audit M17)"
    )
