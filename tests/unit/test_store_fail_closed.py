"""Audit H-06 (2026-10-22) — monetary play must not run on per-replica memory.

`DurableMatchStore` fell back to `InMemoryStore` when Firestore could not be
reached, printed one line to stderr, and served traffic. With more than one
replica the consequences are not "degraded": a waiter's match exists in exactly
one process, so the next poll — load-balanced to another replica — answers
"match not found" while the stake is already in escrow. The result is a duel
that can never be played or settled from the UI, and a player who has to wait
out the on-chain refund horizon.

A deployment must therefore REFUSE TO START. `PULSAR_ENV=dev` (or an explicit
`PULSAR_REQUIRE_DURABLE_STORE=0`) opts out for a local run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import store as store_module  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("PULSAR_ENV", "PULSAR_REQUIRE_DURABLE_STORE", "PULSAR_MATCH_STORE"):
        monkeypatch.delenv(name, raising=False)


def test_an_unset_environment_is_treated_as_production():
    assert store_module._requires_durable_store() is True


@pytest.mark.parametrize("value", ["dev", "DEV", "test", "local", "ci"])
def test_a_local_environment_may_use_memory(monkeypatch, value):
    monkeypatch.setenv("PULSAR_ENV", value)
    assert store_module._requires_durable_store() is False


def test_the_escape_hatch_must_be_explicit(monkeypatch):
    monkeypatch.setenv("PULSAR_REQUIRE_DURABLE_STORE", "0")
    assert store_module._requires_durable_store() is False


def test_production_refuses_to_boot_when_firestore_is_unreachable(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("no credentials")

    monkeypatch.setattr(store_module._firestore, "Client", _boom)
    monkeypatch.setenv("PULSAR_MATCH_STORE", "auto")
    if not store_module._FIRESTORE_AVAILABLE:  # pragma: no cover - env specific
        pytest.skip("google-cloud-firestore is not installed")

    with pytest.raises(RuntimeError, match="Refusing to start"):
        store_module.DurableMatchStore(backend="auto")


def test_dev_still_gets_the_memory_backend(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("no credentials")

    monkeypatch.setattr(store_module._firestore, "Client", _boom)
    monkeypatch.setenv("PULSAR_ENV", "dev")
    if not store_module._FIRESTORE_AVAILABLE:  # pragma: no cover - env specific
        pytest.skip("google-cloud-firestore is not installed")

    s = store_module.DurableMatchStore(backend="auto")
    assert s.backend_name == "memory"
