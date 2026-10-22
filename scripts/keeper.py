#!/usr/bin/env python3
"""PULSAR keeper — permissionless settlement and refund on behalf of the duel (audit C-03).

THE HOLE THIS CLOSES
--------------------
`settleDuel` and `refundTimeoutMatch` are permissionless on-chain, but the only
thing that ever called them was the WINNER'S browser tab, in the same session,
with the winner's own gas. A player who closed the tab, had no POL for gas, or
lost connectivity simply lost the prize: the signature expires, the refund
horizon passes, and the stake waits in escrow. The ledger still recorded a win,
so the stats lied too.

WHAT THIS DOES
--------------
Every pass, it:
  1. SETTLE — for every settled match whose envelope the chain still considers
     Active, submit `settleDuel(proof)`. Because it is permissionless, the prize
     goes to the winner: the keeper only pays gas.
  2. REFUND — for every match past `activation + MATCH_TIMEOUT + REFUND_GRACE`
     that is still Created/Active on-chain, submit `refundTimeoutMatch`, so
     neither stake is stranded.

It REFUSES to send a transaction it can predict will revert: it reads the duel's
on-chain status first and skips anything already Settled/Refunded/Cancelled.
Re-running is therefore always safe, and a lost race with a player's own
submission is not an error.

SAFETY MODEL
------------
- `--dry-run` is the DEFAULT. It prints exactly what it would send.
- The keeper wallet is funded with gas only; it never receives player money.
- It holds the oracle key ONLY if you run it with `ORACLE_PRIVATE_KEY` set
  (mode `--resign local`). Prefer `--resign off` when the API is alive (the API
  re-signs as part of its own sweep) — that keeps the signing key in one place.
- Every rejection is logged with the match id and the reason; nothing is silent.

USAGE
-----
    # cron every minute
    python scripts/keeper.py --once --execute

    # or a long-lived container
    python scripts/keeper.py --interval 30 --execute

    # inspect without sending
    python scripts/keeper.py --once --dry-run

ENV
---
    ESCROW_RPC_URL       JSON-RPC endpoint (Amoy or mainnet)   [required]
    ESCROW_ADDRESS       deployed PulsarEscrow                 [required]
    KEEPER_PRIVATE_KEY   funded gas wallet                     [for --execute]
    ORACLE_PRIVATE_KEY   only for --resign local
    PULSAR_MATCH_STORE / FIRESTORE_*  the store the API uses

This script is NOT wallet-custodial and NOT a substitute for monitoring: if it
stops, players can still settle or refund themselves (the contract permits it).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "api"))

from eth_abi import encode as abi_encode  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import keccak, to_checksum_address  # noqa: E402

import onchain  # noqa: E402

# Contract status enum (PulsarEscrow.MatchStatus).
STATUS_NONE = 0
STATUS_CREATED = 1
STATUS_ACTIVE = 2
STATUS_SETTLED = 3
STATUS_CANCELLED = 4
STATUS_REFUNDED = 5

SETTLE_SIG = "settleDuel((bytes32,address,uint256,uint256,uint256,uint256,bytes))"
REFUND_SIG = "refundTimeoutMatch(bytes32)"
SETTLE_TYPES = ["(bytes32,address,uint256,uint256,uint256,uint256,bytes)"]

# A proof must reach the chain before its deadline. Re-sign when less than this
# is left, so the transaction is not mined after expiry.
REFRESH_MARGIN_SECONDS = 180

# == PulsarEscrow.REFUND_GRACE. Kept next to MATCH_TIMEOUT_SECONDS rather than
# duplicated as a literal at the call site, so a contract change has one place
# to land (the same mistake main.py made with the refund horizon).
REFUND_GRACE_SECONDS = 10 * 60


def selector(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def match_id_bytes32(match_id: str) -> bytes:
    """Same id the client and the server sign against (single conversion)."""
    return bytes.fromhex(onchain._match_id_to_bytes32(match_id).removeprefix("0x"))


def encode_settle(proof: dict[str, Any]) -> bytes:
    """ABI-encode `settleDuel(SettlementProof)`."""
    struct = (
        match_id_bytes32(str(proof["matchId"])),
        str(proof["winner"]),
        int(proof["winnerTimeMs"]),
        int(proof["loserTimeMs"]),
        int(proof["nonce"]),
        int(proof["deadline"]),
        bytes.fromhex(str(proof["signature"]).removeprefix("0x")),
    )
    return selector(SETTLE_SIG) + abi_encode(SETTLE_TYPES, [struct])


def encode_refund(match_id: str) -> bytes:
    return selector(REFUND_SIG) + abi_encode(["bytes32"], [match_id_bytes32(match_id)])


# --- planning (pure; the whole decision logic is testable without a chain) ---


def plan(
    settled: Sequence[Any],
    others: Sequence[Any],
    status_of: Callable[[str], int | None],
    now: int,
    refund_horizon: Callable[[Any], int],
) -> list[dict[str, Any]]:
    """Decide what to do. Pure: no I/O, no clock, no key.

    `settled`  — matches the store says are settled (they carry an envelope)
    `others`   — every other recent match, candidates for refund
    `status_of`— match id -> on-chain status (None when it cannot be read)
    """
    actions: list[dict[str, Any]] = []

    for m in settled:
        status = status_of(m.match_id)
        if status is None:
            actions.append({"action": "skip", "match": m, "reason": "chain status unreadable"})
            continue
        if status != STATUS_ACTIVE:
            # Already settled by the winner, refunded, or never activated.
            continue
        actions.append({"action": "settle", "match": m, "status": status})

    for m in others:
        if getattr(m, "status", "") not in ("active", "waiting"):
            continue
        horizon = refund_horizon(m)
        if now < horizon:
            continue
        status = status_of(m.match_id)
        if status is None:
            actions.append({"action": "skip", "match": m, "reason": "chain status unreadable"})
            continue
        if status not in (STATUS_CREATED, STATUS_ACTIVE):
            continue
        actions.append({"action": "refund", "match": m, "status": status})

    return actions


def envelope_is_stale(proof: dict[str, Any], now: int) -> bool:
    return int(proof.get("deadline", 0) or 0) - now <= REFRESH_MARGIN_SECONDS


# --- chain access -----------------------------------------------------------


def _rpc(payload: dict[str, Any]) -> Any:
    url = os.environ.get("ESCROW_RPC_URL", "").strip()
    if not url:
        raise RuntimeError("ESCROW_RPC_URL is not set")
    body = {}
    import json

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - configured RPC
        data = json.loads(resp.read().decode())
    if "error" in data:
        raise RuntimeError(f"rpc error: {data['error']}")
    return data.get("result")


def _hex_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(str(value), 16) if isinstance(value, str) else int(value)


def send_call(data: bytes, *, key: str, gas_fallback: int = 350_000) -> str:
    """Sign and broadcast one transaction. Returns the tx hash."""
    account = Account.from_key(key if key.startswith("0x") else f"0x{key}")
    from_address = account.address  # type: ignore[attr-defined]
    # eth_account rejects a lower-case address ("invalid field: to") — it
    # requires EIP-55 checksum casing. The contract address comes from env in
    # whatever case the operator pasted, so normalise it here.
    to = to_checksum_address(os.environ["ESCROW_ADDRESS"].strip())
    chain_id = _hex_int(_rpc({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}))
    nonce = _hex_int(
        _rpc(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "eth_getTransactionCount",
                "params": [from_address, "pending"],
            }
        )
    )
    gas_price = _hex_int(_rpc({"jsonrpc": "2.0", "id": 3, "method": "eth_gasPrice", "params": []}))
    try:
        gas = _hex_int(
            _rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "eth_estimateGas",
                    "params": [
                        {
                            "from": from_address,
                            "to": to,
                            "data": "0x" + data.hex(),
                        }
                    ],
                }
            ),
            default=gas_fallback,
        )
        gas = max(gas, 60_000)
    except Exception:  # noqa: BLE001 - estimation is advisory
        gas = gas_fallback

    tx = {
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": int(gas * 1.2),
        "to": to,
        "value": 0,
        "data": "0x" + data.hex(),
        "chainId": chain_id,
    }
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return str(
        _rpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "eth_sendRawTransaction",
                "params": ["0x" + bytes(raw).hex()],
            }
        )
    )


def _store() -> Any:
    import store as store_module

    return store_module.create_store()


def _refund_horizon(match: Any) -> int:
    """When the contract lets anyone refund, in chain time.

    Anchored on ACTIVATION (audit H20 in the contract): a duel that paired late
    still gets its full play window. Falls back to creation time.
    """
    import match_engine

    started = getattr(match, "started_at", None) or getattr(match, "created_at", None)
    base = int(started or 0)
    activated = onchain.duel_activated_at(match.match_id)
    if activated:
        base = max(base, int(activated))
    return base + match_engine.MATCH_TIMEOUT_SECONDS + REFUND_GRACE_SECONDS


def run_once(*, execute: bool) -> int:
    """One pass. Returns the number of transactions sent."""
    import match_engine
    import oracle

    store = _store()
    chain_now = int(onchain.chain_now() or time.time())
    settled = store.sweep_stale_settlements()
    try:
        others = store.recent_matches(limit=500)
    except Exception:  # noqa: BLE001 - memory backend has no listing
        others = []

    actions = plan(settled, others, onchain.duel_status, chain_now, _refund_horizon)
    sent = 0
    key = os.environ.get("KEEPER_PRIVATE_KEY", "").strip()

    for item in actions:
        match = item["match"]
        if item["action"] == "skip":
            print(f"[keeper] skip {match.match_id}: {item['reason']}", file=sys.stderr)
            continue

        if item["action"] == "settle":
            proof = match.signed_settlement or {}
            if envelope_is_stale(proof, chain_now):
                if not os.environ.get("ORACLE_PRIVATE_KEY", "").strip():
                    print(
                        f"[keeper] {match.match_id}: settlement proof expires in "
                        f"{int(proof.get('deadline', 0)) - chain_now}s and this keep"
                        "er cannot re-sign (ORACLE_PRIVATE_KEY unset) — the API's "
                        "sweep must refresh it",
                        file=sys.stderr,
                    )
                    continue
                record = match_engine.settlement_record_for_resign(match)
                proof = oracle.sign_settlement(record, matchish=match)
            data = encode_settle(proof)
            label = f"settleDuel({match.match_id}) winner={proof.get('winner')}"
        else:  # refund
            data = encode_refund(match.match_id)
            label = f"refundTimeoutMatch({match.match_id})"

        if not execute:
            print(f"[keeper] DRY-RUN would send {label} ({len(data) - 4} bytes of calldata)")
            continue
        if not key:
            print("[keeper] --execute needs KEEPER_PRIVATE_KEY", file=sys.stderr)
            continue
        try:
            tx_hash = send_call(data, key=key)
            sent += 1
            print(f"[keeper] sent {label} tx={tx_hash}")
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] FAILED {label}: {exc}", file=sys.stderr)
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PULSAR keeper (settle + refund)")
    parser.add_argument("--once", action="store_true", help="single pass, then exit")
    parser.add_argument("--interval", type=int, default=0, help="seconds between passes")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually broadcast (default is a dry run that only prints)",
    )
    args = parser.parse_args(argv)
    execute = bool(args.execute)
    if args.once or args.interval <= 0:
        return 0 if run_once(execute=execute) >= 0 else 1
    while True:
        try:
            run_once(execute=execute)
        except Exception as exc:  # noqa: BLE001 - a keeper must survive a bad pass
            print(f"[keeper] pass failed: {exc}", file=sys.stderr)
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
