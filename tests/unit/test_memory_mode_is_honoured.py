"""H-18 — "memory mode" has to mean memory mode in every module.

`PULSAR_MATCH_STORE=memory` is an explicit operator statement that this process
must not depend on Firestore. Three modules ignored it: `abuse`, `eligibility`
and `limits` each build their OWN client from the environment and only asked
"is `FIRESTORE_EMULATOR_HOST` set or a project id known?".

Cost, measured on 2026-10-23 inside a sandbox with no JRE (so an emulator could
never be running):

    PULSAR_E2E_STORE=memory bash scripts/start_e2e_stack.sh   # API healthy
    pytest tests/integration/test_eligibility_gate.py
      -> TimeoutError: timed out        (from socket.py, 25 s in)

The stack was healthy, the store was in memory as asked, and the live gate died
on a socket read. Every reader of that failure — including me — starts by
suspecting the test.

These tests pin the rule rather than the incident: when the operator chose the
memory backend, no module may construct a client, and an environment variable
left over from another run cannot override that.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

import abuse  # noqa: E402
import backendmode  # noqa: E402
import eligibility  # noqa: E402
import limits  # noqa: E402

MODULES = (abuse, eligibility, limits)


@pytest.fixture(autouse=True)
def _reset_clients(monkeypatch: pytest.MonkeyPatch):
    """Each module caches its resolution for the process lifetime — by design."""
    for module in MODULES:
        monkeypatch.setattr(module, "_CLIENT", None)
        monkeypatch.setattr(module, "_CLIENT_RESOLVED", False)
    yield


def test_memory_mode_refuses_a_client_even_with_an_emulator_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact combination the launcher produced."""
    monkeypatch.setenv("PULSAR_MATCH_STORE", "memory")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")
    monkeypatch.setenv("GCLOUD_PROJECT", "demo-pulsar")

    for module in MODULES:
        assert module._firestore_client() is None, (
            f"{module.__name__} built a client in memory mode — every request "
            "through its gate will block on an endpoint nobody started"
        )


def test_memory_mode_is_case_and_space_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSAR_MATCH_STORE", "  MEMORY  ")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")
    assert backendmode.firestore_may_be_used() is False


def test_firestore_mode_is_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix must not quietly turn the durable path off."""
    monkeypatch.setenv("PULSAR_MATCH_STORE", "firestore")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")
    assert backendmode.firestore_may_be_used() is True


def test_unset_store_mode_with_an_endpoint_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PULSAR_MATCH_STORE", raising=False)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")
    assert backendmode.firestore_may_be_used() is True


def test_no_endpoint_and_no_project_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PULSAR_MATCH_STORE", "FIRESTORE_EMULATOR_HOST", "FIRESTORE_PROJECT_ID", "GCLOUD_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    assert backendmode.firestore_may_be_used() is False
    for module in MODULES:
        assert module._firestore_client() is None


@pytest.mark.real_eligibility
def test_memory_mode_keeps_the_gates_working(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refusing the client must not refuse the FEATURE: the gates have an
    in-process fallback, and in memory mode it is the only implementation.

    `real_eligibility` is not decoration: `tests/conftest.py` stubs
    `eligibility.require` to a no-op for every test that does not opt out, so
    without the marker this test would assert against the stub and pass no
    matter what the module did.
    """
    monkeypatch.setenv("PULSAR_MATCH_STORE", "memory")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8081")

    addr = "0x" + "ab" * 20
    abuse._memory.clear()
    try:
        abuse.ban(addr, 60, "test")
        with pytest.raises(abuse.AbuseError):
            abuse.require(addr)
        abuse.unban(addr)
        abuse.require(addr)  # no raise

        with pytest.raises(eligibility.EligibilityError):
            eligibility.require(addr)
        eligibility.record(addr)
        eligibility.require(addr)  # no raise
    finally:
        abuse._memory.clear()
        eligibility._memory.clear()


def test_a_client_that_is_still_constructed_is_shared_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unchanged behaviour in Firestore mode: ONE client per process (the
    ~3-second constructor paid per request was the original 2026-10-15 bug)."""
    monkeypatch.setenv("PULSAR_MATCH_STORE", "firestore")
    monkeypatch.setenv("GCLOUD_PROJECT", "demo-pulsar")

    built: list[Any] = []

    class _FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            built.append(self)

    import google.cloud.firestore as fs  # noqa: PLC0415

    monkeypatch.setattr(fs, "Client", _FakeClient)

    first = eligibility._firestore_client()
    second = eligibility._firestore_client()
    assert first is second is built[0]
    assert len(built) == 1


# --- the store itself must obey the same rule (H-18, second half) -------------
#
# Audits H-06 refused an IMPLICIT fallback in production but accepted an
# EXPLICIT `PULSAR_MATCH_STORE=memory` without a word. One word in an env file
# would then cost every match on restart, and the health endpoint would report
# it as calmly as anything else. The escape hatches are PULSAR_ENV=dev (a local
# run) and PULSAR_REQUIRE_DURABLE_STORE=0 (a deliberate throwaway demo).


def _store_env(monkeypatch: pytest.MonkeyPatch, *, env: str | None, require: str | None) -> None:
    monkeypatch.setenv("PULSAR_MATCH_STORE", "memory")
    if env is None:
        monkeypatch.delenv("PULSAR_ENV", raising=False)
    else:
        monkeypatch.setenv("PULSAR_ENV", env)
    if require is None:
        monkeypatch.delenv("PULSAR_REQUIRE_DURABLE_STORE", raising=False)
    else:
        monkeypatch.setenv("PULSAR_REQUIRE_DURABLE_STORE", require)


def test_the_store_refuses_memory_in_a_production_like_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import store as store_mod  # noqa: PLC0415

    _store_env(monkeypatch, env=None, require=None)
    with pytest.raises(RuntimeError) as err:
        store_mod.DurableMatchStore(backend="memory")
    message = str(err.value)
    assert "memory" in message
    assert "PULSAR_ENV=dev" in message
    assert "PULSAR_REQUIRE_DURABLE_STORE=0" in message


def test_dev_and_explicit_optout_are_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    import store as store_mod  # noqa: PLC0415

    _store_env(monkeypatch, env="dev", require=None)
    assert store_mod.DurableMatchStore(backend="memory").backend_name == "memory"

    _store_env(monkeypatch, env=None, require="0")
    assert store_mod.DurableMatchStore(backend="memory").backend_name == "memory"
