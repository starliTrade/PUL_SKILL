"""Audit M-11 — the escrow is versioned, and the server can tell which code it is calling.

The finding: `PulsarEscrow` cannot be upgraded and there is no migration path, so
every behaviour fix means a new deployment while the old one may still owe
somebody money. A proxy was rejected on purpose (see the VERSION comment in the
contract and docs/UPGRADE-PATH.md); the remedy is a versioned contract with an
explicit migration window.

This module pins the three things that make that remedy real rather than a
paragraph in a document:

  1. the numbers — the contract's `VERSION`/`VERSION_CODE` agree with this
     server's `EXPECTED_ESCROW_VERSION`, so the pair cannot drift in a commit
     that forgets one side;
  2. the server actually READS it and reports a mismatch (`/api/health`), which
     is what turns "a stale ESCROW_ADDRESS" from invisible into obvious;
  3. the contract's freeze guards the two DEPOSIT paths only — an exit that
     checked `frozen` would let an operator (or a compromised owner key) hold
     player money hostage, which is a worse finding than the one being fixed.
     That is asserted against the Solidity source, because it is a property of
     the code, not of a Python wrapper.
"""

from __future__ import annotations

import pathlib
import re

import onchain

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "PulsarEscrow.sol"
UPGRADE_DOC = ROOT / "docs" / "UPGRADE-PATH.md"


def _source() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """The body of `function name(...)`, up to the next top-level function."""
    src = _source()
    match = re.search(rf"\n    function {re.escape(name)}\(", src)
    assert match, f"function {name} not found in PulsarEscrow.sol"
    rest = src[match.end() :]
    end = re.search(r"\n    (function|// ---|[A-Za-z].*\()", rest)
    return rest[: end.start()] if end else rest


# --- 1. the numbers -----------------------------------------------------------
def test_contract_publishes_a_version_name_and_code():
    src = _source()
    name = re.search(r'string public constant VERSION = "([^"]+)";', src)
    code = re.search(r"uint256 public constant VERSION_CODE = (\d+);", src)
    assert name, "VERSION constant is missing"
    assert code, "VERSION_CODE constant is missing"
    assert name.group(1) == onchain.EXPECTED_ESCROW_VERSION_NAME
    assert int(code.group(1)) == onchain.EXPECTED_ESCROW_VERSION


def test_version_name_major_matches_version_code():
    # Two identifiers for one fact must not be able to disagree. `VERSION_CODE`
    # is what a contract compares against; the string is what a human reads.
    major = int(onchain.EXPECTED_ESCROW_VERSION_NAME.split(".")[0])
    assert major == onchain.EXPECTED_ESCROW_VERSION


# --- 2. the server reads it ---------------------------------------------------
def test_health_reports_the_escrow_version(monkeypatch):
    from tests.fixtures.fake_rpc import FakeRpc, configure_escrow

    configure_escrow(monkeypatch, FakeRpc())
    import main as server

    version = onchain.escrow_version()
    assert version == {
        "code": onchain.EXPECTED_ESCROW_VERSION,
        "name": onchain.EXPECTED_ESCROW_VERSION_NAME,
        "expected": onchain.EXPECTED_ESCROW_VERSION,
        "compatible": True,
    }
    assert onchain.escrow_version_problem() is None

    body = server.health()
    assert body["escrowVersion"]["compatible"] is True
    assert body["escrowVersionProblem"] is None


def test_a_newer_or_older_contract_is_flagged_not_trusted(monkeypatch):
    from tests.fixtures.fake_rpc import FakeRpc, configure_escrow

    configure_escrow(monkeypatch, FakeRpc(escrow_version_code=3, escrow_version_name="3.0.0"))
    version = onchain.escrow_version()
    assert version["compatible"] is False
    problem = onchain.escrow_version_problem()
    assert problem and "VERSION_CODE=3" in problem
    assert str(onchain.EXPECTED_ESCROW_VERSION) in problem


def test_an_escrow_that_publishes_no_version_is_flagged(monkeypatch):
    # A pre-2.0 deployment is the honest migration case: the address is a real
    # escrow, it just runs code this server was not written against.
    from tests.fixtures.fake_rpc import FakeRpc, configure_escrow

    configure_escrow(monkeypatch, FakeRpc(publishes_version=False))
    version = onchain.escrow_version()
    assert version["code"] is None and version["name"] is None
    assert version["compatible"] is False
    problem = onchain.escrow_version_problem()
    assert problem and "does not publish VERSION()" in problem


def test_version_problem_is_silent_when_no_escrow_is_configured(monkeypatch):
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    monkeypatch.delenv("ESCROW_RPC_URL", raising=False)
    assert onchain.escrow_version() is None
    assert onchain.escrow_version_problem() is None


def test_a_transient_rpc_failure_is_not_cached_forever(monkeypatch):
    # The C2 lesson, applied here: a 5-second blip must not make every later
    # health read claim the contract is the wrong one until a restart.
    from tests.fixtures.fake_rpc import FakeRpc, configure_escrow

    rpc = configure_escrow(monkeypatch, FakeRpc())
    rpc.fail_next(2)  # the two version reads fail
    assert onchain.escrow_version()["compatible"] is False
    assert onchain.escrow_version_problem() is not None

    # Retry cooldown elapsed -> the next read succeeds and the answer is cached.
    later = onchain.timebase.now() + onchain._ESCROW_VERSION_RETRY_SECONDS + 1
    monkeypatch.setattr(onchain.timebase, "now", lambda: later)
    assert onchain.escrow_version()["compatible"] is True
    assert onchain.escrow_version_problem() is None

    # And a success is memoised: it does not touch the RPC again.
    calls_before = rpc.calls_to("eth_call")
    assert onchain.escrow_version()["compatible"] is True
    assert rpc.calls_to("eth_call") == calls_before


def test_a_hostile_version_string_is_not_reflected(monkeypatch):
    # /api/health is public and unauthenticated; a contract must not be able to
    # push junk through it.
    from tests.fixtures.fake_rpc import FakeRpc, configure_escrow

    configure_escrow(monkeypatch, FakeRpc(escrow_version_name="x" * 200))
    assert onchain.escrow_version()["name"] is None


# --- 3. freeze guards deposits only ------------------------------------------
def test_freeze_guards_the_two_deposit_paths_and_nothing_else():
    for name in ("createDuel", "joinDuel"):
        assert 'require(!frozen, "Escrow frozen")' in _function_body(name), name

    for name in ("settleDuel", "refundTimeoutMatch", "withdraw", "sweepResidual"):
        assert "frozen" not in _function_body(name).split("require(frozen")[0], (
            f"{name} must not be gated on `frozen` — an exit that can be paused "
            "lets an operator hold player money"
        )
        assert "Escrow frozen" not in _function_body(name)

    # `sweepResidual` is the one function that REQUIRES the freeze: it may only
    # move surplus during a migration window.
    assert 'require(frozen, "Not frozen")' in _function_body("sweepResidual")


def test_total_locked_is_maintained_on_every_path():
    src = _source()
    for expected in (
        "totalLocked += received;",  # createDuel
        "totalLocked -= amount;",  # _pay (delivered) and withdraw
    ):
        assert expected in src
    # Two increments (create + join) and two decrements (pay + withdraw).
    assert src.count("totalLocked += received;") == 2
    assert src.count("totalLocked -= amount;") == 2


# --- 4. the migration procedure is written down -------------------------------
def test_the_upgrade_path_is_documented():
    assert UPGRADE_DOC.exists(), "docs/UPGRADE-PATH.md is missing"
    doc = UPGRADE_DOC.read_text(encoding="utf-8")
    for required in (
        "freeze",
        "unfreeze",
        "totalLocked",
        "residualBalance",
        "sweepResidual",
        "VERSION_CODE",
        "ESCROW_ADDRESS",
    ):
        assert required in doc, f"UPGRADE-PATH.md never mentions {required}"


def test_the_upgrade_path_names_the_rejected_alternative():
    # A document that only says "we chose X" is not a decision record. The
    # proxy was a real option with real advantages, and the reasoning for
    # rejecting it belongs next to the procedure.
    doc = UPGRADE_DOC.read_text(encoding="utf-8")
    assert "proxy" in doc.lower()
    assert "storage" in doc.lower()
