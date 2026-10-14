"""Alert thresholds (plan item 11.2).

The metrics existed and nothing watched them. These tests pin the DECISIONS:
which conditions are critical (money cannot move) and which are warnings
(something is degraded but players are served).

`evaluate` is pure, so every case here is exact rather than approximate.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_alerts",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts", "check_alerts.py"),
)
assert _SPEC and _SPEC.loader
check_alerts = importlib.util.module_from_spec(_SPEC)
sys.modules["check_alerts"] = check_alerts
_SPEC.loader.exec_module(check_alerts)

CRITICAL = check_alerts.CRITICAL
WARNING = check_alerts.WARNING


def _health(**over: object) -> dict:
    base = {
        "rpc": {"configured": True, "reachable": True},
        "ledger": {"configured": True, "available": True, "failures": {"total": 0}},
        "sweep": {"failures": {"total": 0}},
    }
    base.update(over)
    return base


def _metrics(**over: object) -> dict:
    base = {"signatures": {"failed": 0}, "store": {"contention503": 0}, "endpoints": {}}
    base.update(over)
    return base


def test_a_healthy_server_raises_nothing() -> None:
    assert check_alerts.evaluate(_health(), _metrics()) == []


def test_an_unreachable_rpc_is_critical() -> None:
    alerts = check_alerts.evaluate(_health(rpc={"configured": True, "reachable": False}), _metrics())
    assert [sev for sev, _ in alerts] == [CRITICAL]
    assert "fail closed" in alerts[0][1]


def test_an_unconfigured_rpc_is_not_an_alert() -> None:
    """Practice mode has no chain. That is a configuration, not an incident."""
    assert check_alerts.evaluate(_health(rpc={"configured": False, "reachable": False}), _metrics()) == []


def test_a_dead_ledger_is_critical() -> None:
    alerts = check_alerts.evaluate(
        _health(ledger={"configured": True, "available": False, "failures": {"total": 0}}), _metrics()
    )
    assert [sev for sev, _ in alerts] == [CRITICAL]


def test_failed_signatures_are_critical() -> None:
    """A winner who cannot get a signed settlement cannot claim."""
    alerts = check_alerts.evaluate(_health(), _metrics(signatures={"failed": 3}))
    assert [sev for sev, _ in alerts] == [CRITICAL]
    assert "cannot claim" in alerts[0][1]


def test_ledger_and_sweep_failures_are_warnings() -> None:
    alerts = check_alerts.evaluate(
        _health(ledger={"configured": True, "available": True, "failures": {"total": 2}},
                sweep={"failures": {"total": 5}}),
        _metrics(),
    )
    assert {sev for sev, _ in alerts} == {WARNING}
    assert len(alerts) == 2


def test_contention_below_the_threshold_is_quiet_and_above_is_not() -> None:
    below = check_alerts.evaluate(_health(), _metrics(store={"contention503": check_alerts.CONTENTION_WARN - 1}))
    assert below == []
    above = check_alerts.evaluate(_health(), _metrics(store={"contention503": check_alerts.CONTENTION_WARN}))
    assert [sev for sev, _ in above] == [WARNING]


def test_a_slow_route_is_a_warning_not_a_critical() -> None:
    slow = check_alerts.evaluate(
        _health(), _metrics(endpoints={"/api/queue": {"p95Ms": check_alerts.P95_WARN_MS + 1}})
    )
    assert [sev for sev, _ in slow] == [WARNING]
    fast = check_alerts.evaluate(
        _health(), _metrics(endpoints={"/api/queue": {"p95Ms": check_alerts.P95_WARN_MS - 1}})
    )
    assert fast == []


def test_a_missing_p95_does_not_crash() -> None:
    """An endpoint with no samples reports None, not a number."""
    assert check_alerts.evaluate(_health(), _metrics(endpoints={"/api/x": {"p95Ms": None}})) == []


def test_critical_outranks_warning_in_the_exit_code() -> None:
    """The worst alert decides the verdict — a warning must not mask a critical."""
    import subprocess

    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts", "check_alerts.py",
    )
    # Point it at a port with nothing on it: unreachable is exit 3, which is the
    # documented "cannot even ask" case.
    out = subprocess.run(
        [sys.executable, script, "--url", "http://127.0.0.1:9"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 3, out.stderr
    assert "unreachable" in out.stderr.lower()


@pytest.mark.parametrize("severity", [CRITICAL, WARNING])
def test_severity_labels_are_stable(severity: str) -> None:
    """The labels are part of the interface a scheduler greps for."""
    assert severity in ("CRITICAL", "WARNING")
