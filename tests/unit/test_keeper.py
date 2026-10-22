"""Audit C-03 (2026-10-22) — the keeper that settles and refunds for the player.

Nothing in the product ever called `settleDuel` except the winner's browser tab.
A player who closed the tab lost the prize; a stranded duel kept both stakes in
escrow until someone refunded with their own gas.

These tests cover the parts that can be proven without a chain: the ABI
encoding (a wrong tuple order is an on-chain revert), the decision logic (never
send a transaction that must revert), and the re-sign boundary.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import keeper  # noqa: E402
from eth_abi import decode as abi_decode  # noqa: E402
from eth_utils import keccak  # noqa: E402

MATCH = "ab" * 32
WINNER = "0x" + "22" * 20
PROOF = {
    "matchId": MATCH,
    "winner": WINNER,
    "winnerTimeMs": 210,
    "loserTimeMs": 240,
    "nonce": 7,
    "deadline": 1_700_000_600,
    "signature": "0x" + "33" * 65,
}


class _Match:
    def __init__(self, match_id=MATCH, status="settled", envelope=None, started=1_000):
        self.match_id = match_id
        self.status = status
        self.signed_settlement = envelope
        self.started_at = started


def test_settle_call_matches_the_contract_selector_and_layout():
    data = keeper.encode_settle(PROOF)
    assert data[:4] == keccak(text=keeper.SETTLE_SIG)[:4]

    (struct,) = abi_decode(keeper.SETTLE_TYPES, data[4:])
    assert struct[0] == bytes.fromhex(MATCH)
    assert struct[1] == WINNER
    assert struct[2:] == (210, 240, 7, 1_700_000_600, bytes.fromhex("33" * 65))


def test_refund_call_is_a_single_bytes32():
    data = keeper.encode_refund(MATCH)
    assert data[:4] == keccak(text=keeper.REFUND_SIG)[:4]
    (mid,) = abi_decode(["bytes32"], data[4:])
    assert mid == bytes.fromhex(MATCH)


def test_a_settlement_is_sent_only_while_the_duel_is_active():
    actions = keeper.plan(
        [_Match(envelope=PROOF)],
        [],
        lambda _mid: keeper.STATUS_SETTLED,
        now=1_000,
        refund_horizon=lambda _m: 0,
    )
    assert actions == [], "the keeper would have re-settled a settled duel"


def test_an_active_duel_with_a_settlement_is_settled():
    actions = keeper.plan(
        [_Match(envelope=PROOF)],
        [],
        lambda _mid: keeper.STATUS_ACTIVE,
        now=1_000,
        refund_horizon=lambda _m: 0,
    )
    assert [a["action"] for a in actions] == ["settle"]


def test_an_unreadable_chain_is_skipped_loudly_not_guessed():
    actions = keeper.plan(
        [_Match(envelope=PROOF)],
        [],
        lambda _mid: None,
        now=1_000,
        refund_horizon=lambda _m: 0,
    )
    assert actions[0]["action"] == "skip"


def test_an_expired_match_is_refunded():
    m = _Match(status="active", started=1_000)
    actions = keeper.plan(
        [],
        [m],
        lambda _mid: keeper.STATUS_ACTIVE,
        now=10_000,
        refund_horizon=lambda _m: 5_000,
    )
    assert [a["action"] for a in actions] == ["refund"]


def test_a_match_inside_its_play_window_is_left_alone():
    m = _Match(status="active", started=1_000)
    actions = keeper.plan(
        [],
        [m],
        lambda _mid: keeper.STATUS_ACTIVE,
        now=1_000,
        refund_horizon=lambda _m: 5_000,
    )
    assert actions == []


def test_a_refund_is_not_sent_for_a_duel_already_refunded():
    m = _Match(status="active", started=1_000)
    actions = keeper.plan(
        [],
        [m],
        lambda _mid: keeper.STATUS_REFUNDED,
        now=10_000,
        refund_horizon=lambda _m: 5_000,
    )
    assert actions == []


def test_a_stale_envelope_is_detected_before_the_deadline_passes():
    assert keeper.envelope_is_stale({"deadline": 1_000 + 60}, 1_000) is True
    assert keeper.envelope_is_stale({"deadline": 1_000 + 900}, 1_000) is False


# --- the send path, without a network ---------------------------------------
def test_a_transaction_is_signed_and_broadcast(monkeypatch):
    """Sign + encode + broadcast, with the RPC replaced by a recorder.

    A wrong nonce/chainId/calldata produces a transaction that either reverts
    or is rejected; this pins the shape of what actually leaves the process.
    """
    import json as _json
    import rlp
    from eth_utils import to_bytes

    sent: list[dict] = []

    def fake_rpc(payload):
        method = payload["method"]
        sent.append(payload)
        return {
            "eth_chainId": hex(80002),
            "eth_getTransactionCount": hex(3),
            "eth_gasPrice": hex(30_000_000_000),
            "eth_estimateGas": hex(200_000),
            "eth_sendRawTransaction": "0x" + "99" * 32,
        }[method]

    monkeypatch.setattr(keeper, "_rpc", fake_rpc)
    monkeypatch.setenv("ESCROW_ADDRESS", "0x" + "ab" * 20)

    key = "0x" + "11" * 32
    tx_hash = keeper.send_call(keeper.encode_settle(PROOF), key=key)
    assert tx_hash == "0x" + "99" * 32

    raw = sent[-1]["params"][0]
    decoded = rlp.decode(to_bytes(hexstr=raw))
    # [nonce, gasPrice, gas, to, value, data, v, r, s] for a legacy (EIP-155) tx
    assert len(decoded) == 9
    assert int.from_bytes(decoded[0], "big") == 3
    assert decoded[3].hex() == "ab" * 20
    assert decoded[5][:4] == keccak(text=keeper.SETTLE_SIG)[:4], (
        "the calldata sent on-chain is not the settleDuel call"
    )
    assert int.from_bytes(decoded[6], "big") == 80002 * 2 + 35, "wrong chain id"


def test_run_once_dry_run_sends_nothing(monkeypatch, capsys):
    class _Store:
        def sweep_stale_settlements(self):
            return [_Match(envelope=PROOF)]

        def recent_matches(self, limit=500):
            return []

    monkeypatch.setattr(keeper, "_store", lambda: _Store())
    monkeypatch.setattr(keeper.onchain, "duel_status", lambda *_a, **_k: keeper.STATUS_ACTIVE)
    monkeypatch.setattr(keeper.onchain, "chain_now", lambda: 1_000_000)
    monkeypatch.setattr(
        keeper, "send_call", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("sent!"))
    )
    assert keeper.run_once(execute=False) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "settleDuel" in out
