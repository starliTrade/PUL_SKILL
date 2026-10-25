"""The rate limiter's two halves: the part that must degrade, and the key it degrades on.

`docs/COVERAGE-REPORT.md §3.1` calls the Firestore half of the limiter
environmental — it needs the emulator. But three of the functions around it are
pure, and they decide whether a degraded limiter is *visible* (audit C1) and
*who gets limited* (audit #10 item 4 / M-09). Their bodies had never executed:
the Firestore branch is skipped without an emulator, and the IP-key path only
runs on `/api/auth/*`.

What is at stake, stated as the failure each test prevents:

* `_client_ip` — before M-09, `X-Forwarded-For` was honoured whenever the socket
  address *looked* private. Every container network is private, including one
  where the header passes through untouched, so a script could rotate its quota
  across forged IPs AND pin the blame on a victim. The header is now used only
  with `TRUST_PROXY_HEADERS=1`; this test pins both directions.
* `_rl_note_fallback` — the limiter silently downgrading to the in-process
  window is exactly how audit C1 survived: the "distributed" limiter never
  worked and nothing said so. The counter, the recorded reason and the stderr
  line are the only trace.
* `_is_transient_backend_error` — the downgrade must cover transport failures
  and nothing else. A `ValueError` from our own code turned into a silent
  fallback is how a bug becomes invisible.
* `_rl_expiry` — a rate-limit document without a TTL lives forever.
"""

from __future__ import annotations

import datetime as _dt

import main as server
import pytest
import timebase
from starlette.requests import Request


def _request(headers: dict[str, str] | None = None, client: str | None = "10.0.0.9") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/auth/verify",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": (client, 4444) if client else None,
        }
    )


@pytest.fixture()
def limited(monkeypatch):
    """Capture what the limiter was asked to count, instead of counting it."""
    seen: list[tuple[str, str, int]] = []
    monkeypatch.setattr(server, "_rl_check", lambda bucket, key, limit: seen.append((bucket, key, limit)))
    return seen


# --- 1. the key: forged headers must not become quota ------------------------
def test_a_forwarded_header_is_ignored_unless_a_proxy_is_declared(monkeypatch, limited) -> None:
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    server._rl_check_ip("auth", _request({"x-forwarded-for": "1.2.3.4"}), 10)
    assert limited == [("auth", "10.0.0.9", 10)], (
        "X-Forwarded-For was honoured without TRUST_PROXY_HEADERS — a script can "
        "rotate its quota across forged IPs and pin the blame on a victim"
    )


def test_a_declared_proxy_makes_the_first_hop_the_client(monkeypatch, limited) -> None:
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    server._rl_check_ip("auth", _request({"x-forwarded-for": "1.2.3.4, 10.0.0.9"}), 10)
    # The composed key keeps the socket address too, so the same forwarded IP
    # coming through two different proxies is two buckets, not one.
    assert limited == [("auth", "1.2.3.4|10.0.0.9", 10)]


def test_an_empty_hop_list_falls_back_to_the_socket(monkeypatch, limited) -> None:
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    server._rl_check_ip("auth", _request({"x-forwarded-for": "  ,  "}), 10)
    assert limited == [("auth", "10.0.0.9", 10)]


def test_a_request_with_no_client_is_still_counted(monkeypatch, limited) -> None:
    # A Unix-socket or test client has no `client`; the limiter must not raise.
    server._rl_check_ip("auth", _request(client=None), 10)
    assert limited == [("auth", "unknown", 10)]


# --- 2. the fallback must be loud -------------------------------------------
def test_a_fallback_is_counted_and_its_reason_recorded(monkeypatch, capsys) -> None:
    monkeypatch.setattr(server, "_rl_fallback_count", 0)
    server._rl_fallback_last.clear()

    server._rl_note_fallback(ConnectionError("firestore is unreachable"))

    assert server._rl_fallback_count == 1
    assert "unreachable" in server._rl_fallback_last["error"]
    assert isinstance(server._rl_fallback_last["at"], int)
    assert "Firestore limiter unavailable" in capsys.readouterr().err, (
        "a silent downgrade is how audit C1 stayed invisible for the life of the "
        "project; the line on stderr is the operator's only trace"
    )


def test_the_recorded_reason_is_bounded(monkeypatch) -> None:
    # An exception string can carry a whole traceback / request body; this dict
    # is served on /api/metrics, so it must not grow with the failure.
    server._rl_note_fallback(RuntimeError("x" * 5000))
    assert len(server._rl_fallback_last["error"]) <= 200


# --- 3. what counts as transient ---------------------------------------------
@pytest.mark.parametrize("exc", [OSError("boom"), TimeoutError("slow"), ConnectionError("down")])
def test_transport_failures_are_transient(exc: BaseException) -> None:
    assert server._is_transient_backend_error(exc) is True


@pytest.mark.parametrize("exc", [ValueError("a bug"), TypeError("another"), KeyError("k")])
def test_our_own_bugs_are_not_transient(exc: BaseException) -> None:
    assert server._is_transient_backend_error(exc) is False, (
        "a bug in this module was converted into a silent downgrade — the "
        "limiter would look healthy while its logic was broken"
    )


def test_a_google_api_error_is_transient() -> None:
    from google.api_core import exceptions as gexc  # noqa: PLC0415

    assert server._is_transient_backend_error(gexc.ServiceUnavailable("down")) is True


# --- 4. the TTL stamp --------------------------------------------------------
def test_the_ttl_stamp_is_a_datetime_one_hour_ahead() -> None:
    now_ms = 1_700_000_000_000
    stamp = server._rl_expiry(now_ms)
    assert isinstance(stamp, _dt.datetime), "Firestore's TTL policy needs a timestamp"
    assert stamp.tzinfo is not None, "a naive datetime is read as UTC by some SDKs and local by others"
    expected = now_ms // 1000 + server.RL_DOC_TTL_SECONDS
    assert int(stamp.timestamp()) == expected


# --- 5. the window's eviction order -----------------------------------------
def test_a_quiet_window_is_dropped_before_a_busy_one(monkeypatch) -> None:
    """`test_memory_bounds` pins the SIZE of `_rl_window`; this pins WHICH key goes.

    Audit M16's eviction has two passes: drop windows whose newest hit is older
    than the whole window (indistinguishable from absent), then — only if still
    over the cap — the oldest. The first pass never ran in any test, because the
    cap test fills the map with keys that were all touched just now.
    """
    server._rl_window.clear()
    monkeypatch.setattr(server, "_RL_WINDOW_MAX_KEYS", 2)
    now = timebase.now()
    # Two keys that stopped being used an hour ago, and one live key.
    server._rl_window["queue:0xdead"] = [now - 3600]
    server._rl_window["queue:0xbeef"] = [now - 1800]

    server._rl_check("queue", "0x" + "aa" * 20, 1_000_000)

    assert "queue:0xdead" not in server._rl_window
    assert "queue:0xbeef" not in server._rl_window
    assert "queue:" + "0x" + "aa" * 20 in server._rl_window, (
        "the eviction dropped the live key instead of the quiet ones"
    )
