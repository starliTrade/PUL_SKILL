"""The claim verifier — the one function that decides if an on-chain claim is real.

Audit H-26 (2026-10-23), found while measuring coverage for the money path:
`onchain.verify_settlement_tx` had **zero** direct tests. The only places that
touched the claim flow — `tests/integration/test_claim_and_queue.py` — replaced
it with `lambda *a, **k: True`:

    monkeypatch.setattr(server.onchain, "verify_settlement_tx", lambda *a, **k: True)

So the tests proved "given a verified claim, the ledger records it", while the
verification itself was assumed. That function decides whether a player's
`txHash` really settled THIS match, for THIS claimer, against THIS escrow. If it
were wrong in either direction the consequences are opposite and both bad:

  * too permissive → a fabricated transaction hash pays a claim;
  * too strict → a player who really won cannot claim, and the only remaining
    path is a refund that pays both of them.

Everything below drives the REAL function through the shared `FakeRpc`, including
the event-log layout the contract emits.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT))

import onchain  # noqa: E402
from tests.fixtures.fake_rpc import FakeRpc  # noqa: E402

ESCROW = "0x" + "ee" * 20
OTHER = "0x" + "dd" * 20
MATCH = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # 32 chars, like a server id
CLAIMER = "0x" + "11" * 20
TX = "0x" + "ab" * 32


def _topic(address: str) -> str:
    return "0x" + address.lower().removeprefix("0x").rjust(64, "0")


def _event_topic() -> str:
    return "0x" + onchain._keccak(b"MatchSettled(bytes32,address,uint256,uint256)").hex()


def _receipt(
    *,
    status: str = "0x1",
    to: str = ESCROW,
    log_address: str = ESCROW,
    match_id: str = MATCH,
    claimer: str = CLAIMER,
) -> dict[str, Any]:
    return {
        "status": status,
        "to": to,
        "logs": [
            {
                "address": log_address,
                "topics": [
                    _event_topic(),
                    "0x" + onchain._match_id_to_bytes32(match_id).removeprefix("0x"),
                    _topic(claimer),
                    "0x" + "00" * 32,  # prize (not part of the check)
                ],
                "data": "0x",
            }
        ],
    }


def _reset_caches() -> None:
    """Every cache in `onchain` that could carry a previous test's answer.

    `onchain` caches the escrow version, the RPC reachability and the chain time;
    `_cache` holds the deposit-gate verdicts. A test that changes the chain id or
    the escrow address must clear all of them or it asserts against the previous
    fixture.
    """
    onchain.reset_escrow_version_cache()
    onchain.reset_chain_now_cache()
    onchain._rpc_reachable_cache = None  # noqa: SLF001
    onchain._cache.clear()  # noqa: SLF001
    # The chain-binding latch (audit #8 F-16) remembers an observed chain id.
    onchain._chain_id_checked = False  # noqa: SLF001
    onchain._chain_id_mismatch = False  # noqa: SLF001
    onchain._chain_mismatch_until = 0.0  # noqa: SLF001


@pytest.fixture
def rpc(monkeypatch: pytest.MonkeyPatch) -> FakeRpc:
    fake = FakeRpc(chain_id=80002, receipt=_receipt())
    fake.install(monkeypatch)
    monkeypatch.setenv("ESCROW_ADDRESS", ESCROW)
    monkeypatch.setenv("ESCROW_RPC_URL", "http://fake-rpc")
    monkeypatch.setenv("ORACLE_CHAIN_ID", "80002")
    _reset_caches()
    yield fake
    _reset_caches()


# --- the honest claim ---------------------------------------------------------


def test_a_real_settlement_receipt_is_accepted(rpc: FakeRpc) -> None:
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is True


def test_the_match_key_is_the_one_the_fixture_derives_independently() -> None:
    """`tests/fixtures/chain.py` documents that its derivation must equal the
    server's. If it drifts, every on-chain test silently reads a different duel
    than production would."""
    from tests.fixtures.chain import match_id_bytes

    mine = bytes.fromhex(onchain._match_id_to_bytes32(MATCH).removeprefix("0x"))
    assert mine == match_id_bytes(MATCH)


# --- the dishonest ones -------------------------------------------------------


def test_a_reverted_transaction_is_refused(rpc: FakeRpc) -> None:
    rpc.receipt = _receipt(status="0x0")
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_transaction_to_another_contract_is_refused(rpc: FakeRpc) -> None:
    """Any successful tx has a receipt; only one to OUR escrow proves anything."""
    rpc.receipt = _receipt(to=OTHER)
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_an_event_from_another_contract_is_refused(rpc: FakeRpc) -> None:
    """A log is only evidence if the address that emitted it is the escrow."""
    rpc.receipt = _receipt(log_address=OTHER)
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_settlement_for_a_different_match_is_refused(rpc: FakeRpc) -> None:
    """Replaying a real settlement tx against another duel's id must fail."""
    rpc.receipt = _receipt(match_id="ffffffffffffffffffffffffffffffff")
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_settlement_paid_to_someone_else_is_refused(rpc: FakeRpc) -> None:
    """The winner in the event must be the claimer — otherwise anyone could claim
    the prize of a duel they merely watched."""
    rpc.receipt = _receipt(claimer="0x" + "22" * 20)
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_receipt_without_the_event_is_refused(rpc: FakeRpc) -> None:
    rpc.receipt = {"status": "0x1", "to": ESCROW, "logs": []}
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_log_with_truncated_topics_is_refused(rpc: FakeRpc) -> None:
    rpc.receipt = {
        "status": "0x1",
        "to": ESCROW,
        "logs": [{"address": ESCROW, "topics": [_event_topic()], "data": "0x"}],
    }
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_malformed_hash_never_reaches_the_rpc(rpc: FakeRpc) -> None:
    assert onchain.verify_settlement_tx("0x1234", MATCH, CLAIMER) is False
    assert onchain.verify_settlement_tx("", MATCH, CLAIMER) is False
    assert onchain.verify_settlement_tx("ab" * 32, MATCH, CLAIMER) is False
    assert not [c for c in rpc.calls if c["method"] == "eth_getTransactionReceipt"]


# --- failure modes are CLOSED -------------------------------------------------


def test_an_unreadable_receipt_is_refused_not_assumed(rpc: FakeRpc) -> None:
    rpc.receipt = None
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_an_rpc_outage_is_refused(rpc: FakeRpc) -> None:
    rpc.fail_next(3)
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_a_wrong_chain_is_refused(rpc: FakeRpc) -> None:
    """The signature chain and the RPC chain must agree, or the receipt is from a
    different network (a testnet settlement claimed on mainnet)."""
    rpc.chain_id = 1
    _reset_caches()
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_an_unconfigured_escrow_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    monkeypatch.setenv("ESCROW_RPC_URL", "http://fake-rpc")
    _reset_caches()
    assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False


def test_the_verifier_never_raises(rpc: FakeRpc) -> None:
    """A claim endpoint that 500s on a malformed receipt is a denial of service
    against the winner's prize."""
    for receipt in (
        {"status": "0x1", "to": ESCROW, "logs": "not-a-list"},
        {"status": "0x1", "to": ESCROW, "logs": [None]},
        {"status": "0x1", "to": ESCROW, "logs": [{"topics": None}]},
    ):
        rpc.receipt = receipt  # type: ignore[assignment]
        assert onchain.verify_settlement_tx(TX, MATCH, CLAIMER) is False
