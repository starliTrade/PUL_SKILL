"""The chain-binding cross-check must fail closed FOR ITS OWN REASON.

`onchain._chain_ok()` compares the RPC's `eth_chainId` with `ORACLE_CHAIN_ID` so a
server pointed at the wrong network refuses to read duel state. The legacy probe
(`scripts/probe_a5.py`) claims to prove that, and for months it did not:

    def read(self) -> bytes:
        return '{"jsonrpc":"2.0","id":1,"result":"' + result + b'"}'

`str + bytes` raises `TypeError` on EVERY call. The probe's assertion —
"chain mismatch → duel_status fails closed (None)" — passed anyway, because
`duel_status` swallows read failures and returns None. So the check was satisfied
by a broken test double, not by the cross-check. Two very different facts produce
the same observable, and only one of them is a working guard.

That is the class of defect this file exists for: an assertion that cannot
distinguish "the guard fired" from "everything was already broken". The probe now
also asserts the LATCH (`onchain._chain_id_mismatch`), which is the mechanism.
"""
from __future__ import annotations

import json

import pytest

import onchain


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _fake_rpc(chain_id_hex: str, status_word: int = 1):
    """An urlopen replacement that answers eth_chainId and matches(bytes32)."""

    def urlopen(req, timeout=None):  # noqa: ANN001, ARG001 - signature of urlopen
        method = json.loads(req.data.decode())["method"]
        if method == "eth_chainId":
            result: str = chain_id_hex
        else:
            words = ["0" * 64] * 10
            words[6] = format(status_word, "064x")
            result = "0x" + "".join(words)
        return _Resp({"jsonrpc": "2.0", "id": 1, "result": result})

    return urlopen


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("ESCROW_RPC_URL", "http://stub.invalid")
    monkeypatch.setenv("ESCROW_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setenv("ORACLE_CHAIN_ID", "80002")
    onchain.reset_chain_now_cache()
    onchain._chain_id_checked = False
    onchain._chain_id_mismatch = False
    onchain._chain_mismatch_until = 0.0
    onchain._cache.clear()
    yield
    onchain._chain_id_checked = False
    onchain._chain_id_mismatch = False
    onchain._chain_mismatch_until = 0.0
    onchain._cache.clear()


def test_a_wrong_chain_trips_the_latch_and_refuses_the_read(monkeypatch) -> None:
    """mainnet (0x1) while the deployment expects 80002."""
    monkeypatch.setattr(onchain.urllib.request, "urlopen", _fake_rpc("0x1"))
    assert onchain.duel_status("a" * 32) is None
    assert onchain._chain_id_mismatch is True, "the cross-check did not fire"
    assert onchain._chain_id_checked is True


def test_the_matching_chain_reads_normally(monkeypatch) -> None:
    """CONTROL: without this, "refuses everything" would look like a passing guard."""
    monkeypatch.setattr(onchain.urllib.request, "urlopen", _fake_rpc(hex(80002), status_word=2))
    assert onchain.duel_status("b" * 32) == 2
    assert onchain._chain_id_mismatch is False


def test_an_unreadable_rpc_is_NOT_a_chain_mismatch(monkeypatch) -> None:
    """The distinction the old probe could not make, asserted explicitly.

    A dead endpoint returns None from `duel_status` exactly like a wrong chain
    does. The difference is visible only in the latch — which is why the probe
    asserts the latch, and why this test exists: if someone deletes that
    assertion, this documents what it was for.
    """

    def dead(req, timeout=None):  # noqa: ANN001, ARG001
        raise ConnectionError("rpc is down")

    monkeypatch.setattr(onchain.urllib.request, "urlopen", dead)
    assert onchain.duel_status("c" * 32) is None
    assert onchain._chain_id_mismatch is False, (
        "a dead RPC must not be reported as a chain mismatch — the operator's "
        "fix is different for the two"
    )


def test_a_broken_test_double_is_caught_by_the_latch_assertion(monkeypatch) -> None:
    """The historical bug, reproduced.

    The stub raises `TypeError` on every read (the `str + bytes` bug). `duel_status`
    still returns None — so the OLD assertion passed — but the latch never trips,
    which is what the new assertion checks.
    """

    def str_plus_bytes(req, timeout=None):  # noqa: ANN001, ARG001
        return '{"jsonrpc":"2.0","id":1,"result":"' + "0x1" + b'"}'

    monkeypatch.setattr(onchain.urllib.request, "urlopen", str_plus_bytes)
    assert onchain.duel_status("d" * 32) is None, "None — same observable as a real mismatch"
    assert onchain._chain_id_mismatch is False, "…but nothing was actually checked"


def test_the_probe_asserts_the_latch() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "scripts" / "probe_a5.py").read_text(
        encoding="utf-8"
    )
    assert "onchain._chain_id_mismatch is True" in src, (
        "probe_a5 lost the assertion that distinguishes a tripped cross-check "
        "from an unreadable RPC"
    )
    # And the stub itself must return bytes. Comment lines are excluded on
    # purpose: the file DOCUMENTS the old bug, and a test that cannot tell code
    # from a comment about the code would forbid explaining the fix.
    code = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    assert not any("result + b'\"}'" in ln for ln in code), "the str + bytes stub is back"


def test_the_type_gate_now_covers_scripts() -> None:
    """`mypy` only checked `api/`, which is how the stub survived.

    The `str + bytes` return in probe_a5 is a two-line type error; a gate that
    looks at `api` alone cannot see it. This asserts the config, not the intent.
    """
    from pathlib import Path

    cfg = (Path(__file__).resolve().parents[2] / "mypy.ini").read_text(encoding="utf-8")
    files = [line.split("=", 1)[1].strip() for line in cfg.splitlines() if line.startswith("files")]
    assert files, "mypy.ini has no `files`"
    targets = {part.strip() for part in files[0].split(",")}
    assert "api" in targets
    assert "scripts" in targets, "the type gate stopped covering scripts/"

    verify = (Path(__file__).resolve().parents[2] / "scripts" / "verify.sh").read_text(
        encoding="utf-8"
    )
    assert '-m mypy api\\n' not in verify and '"-m mypy api"' not in verify, (
        "verify.sh still passes `api` explicitly, which overrides `files` in mypy.ini "
        "and silently drops scripts/"
    )
