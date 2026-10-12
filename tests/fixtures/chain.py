"""Local EVM chain fixture: anvil + the deployed escrow (plan item 0.8).

Phase 3 changes `contracts/PulsarEscrow.sol`, and phase 11 rehearses the money
path. Neither can be verified by unit tests: the settlement digest, the EIP-191
preimage and the `DuelMatch` struct layout are a THREE-way contract between
`api/oracle.py`, `api/onchain.py` and the Solidity source. Only a real EVM
proves all three still agree — and a mismatch is silent until a settlement
reverts on-chain with real money locked.

Start the chain first:
    scripts/start_anvil.sh --bg

Then:
    pytest -m chain

Everything here talks to anvil over plain JSON-RPC with `eth_account` +
`eth_abi`, so the tests need no web3 dependency.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak

MANIFEST = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "deployments" / "local.json"

GAS_LIMIT = 1_500_000
GAS_PRICE = 30_000_000_000  # anvil's minimum is well below this; keeps it deterministic


def sel(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


SEL_FAUCET = sel("faucet(address,uint256)")
SEL_APPROVE = sel("approve(address,uint256)")
SEL_ALLOWANCE = sel("allowance(address,address)")
SEL_BALANCE_OF = sel("balanceOf(address)")
SEL_CREATE_DUEL = sel("createDuel(bytes32,uint256)")
SEL_JOIN_DUEL = sel("joinDuel(bytes32)")
SEL_SETTLE_DUEL = sel(
    "settleDuel((bytes32,address,uint256,uint256,uint256,uint256,bytes))"
)
SEL_REFUND = sel("refundTimeoutMatch(bytes32)")
SEL_MATCHES = sel("matches(bytes32)")
SEL_PAYMENT_TOKEN = sel("paymentToken()")
SEL_ORACLE_SIGNER = sel("oracleSigner()")

MATCH_STATUS = {
    0: "None",
    1: "Created",
    2: "Active",
    3: "Settled",
    4: "Cancelled",
    5: "Refunded",
}


class ChainUnavailable(RuntimeError):
    pass


@dataclass
class DuelState:
    match_id: str
    player1: str
    player2: str
    stake_amount: int
    total_pool: int
    created_at: int
    status: int
    winner: str
    winner_reaction_ms: int
    loser_reaction_ms: int

    @property
    def status_name(self) -> str:
        return MATCH_STATUS.get(self.status, f"?{self.status}")


class LocalChain:
    """A thin, synchronous JSON-RPC client for the local test chain."""

    def __init__(self, manifest: pathlib.Path = MANIFEST) -> None:
        if not manifest.exists():
            raise ChainUnavailable(
                f"no deployment manifest at {manifest} — run scripts/start_anvil.sh --bg"
            )
        self.manifest = json.loads(manifest.read_text())
        self.rpc_url: str = self.manifest["rpcUrl"]
        self.chain_id: int = int(self.manifest["chainId"])
        self.token: str = self.manifest["token"]
        self.escrow: str = self.manifest["escrow"]
        self.treasury: str = self.manifest["treasury"]
        self.oracle: str = self.manifest["oracle"]
        self._nonces: dict[str, int] = {}

    # -- raw rpc ---------------------------------------------------------------
    def rpc(self, method: str, params: list[Any] | None = None) -> Any:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        ).encode()
        req = urllib.request.Request(
            self.rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError) as exc:
            raise ChainUnavailable(f"anvil unreachable at {self.rpc_url}: {exc}") from exc
        if body.get("error"):
            raise RuntimeError(f"{method} failed: {body['error']}")
        return body.get("result")

    def is_up(self) -> bool:
        try:
            return int(self.rpc("eth_chainId"), 16) == self.chain_id
        except Exception:
            return False

    # -- transactions ----------------------------------------------------------
    def _next_nonce(self, sender: str) -> int:
        """The pending nonce for `sender`, read fresh from the node.

        A cached counter is faster but drifts the moment anything else sends
        from the same account (a re-deploy, another fixture, a parallel test),
        and the failure mode is an opaque "nonce too low" deep inside a test.
        anvil is local, so a fresh read per transaction is cheap and correct.
        """
        return int(self.rpc("eth_getTransactionCount", [sender, "pending"]), 16)

    def send(self, private_key: str, to: str, data: str, value: int = 0) -> str:
        account = Account.from_key(private_key)
        sender = account.address

        # No retry loop on purpose: a retry after a "nonce too low" error can
        # double-send when the first transaction actually landed, which shows up
        # as a mysterious extra balance change in an unrelated test. A fresh
        # nonce read per transaction is enough for a single-writer test chain.
        tx = {
            "nonce": self._next_nonce(sender),
            "to": to,
            "value": value,
            "gas": GAS_LIMIT,
            "gasPrice": GAS_PRICE,
            "chainId": self.chain_id,
            "data": data,
        }
        signed = account.sign_transaction(tx)
        raw = signed.raw_transaction.hex()
        raw = raw if raw.startswith("0x") else "0x" + raw
        tx_hash = self.rpc("eth_sendRawTransaction", [raw])
        receipt = self.wait(tx_hash)
        if int(receipt.get("status", "0x0"), 16) != 1:
            raise RuntimeError(f"tx reverted: {tx_hash}")
        return tx_hash

    def wait(self, tx_hash: str, tries: int = 60) -> dict[str, Any]:
        import time

        for _ in range(tries):
            receipt = self.rpc("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                return receipt
            time.sleep(0.1)
        raise RuntimeError(f"tx not mined: {tx_hash}")

    def call(self, to: str, data: str) -> str:
        return self.rpc("eth_call", [{"to": to, "data": data}, "latest"])

    # -- gas -------------------------------------------------------------------
    def fund_eth(self, to: str, amount_wei: int = 10**18) -> str:
        """Send native gas tokens from the deployer (anvil's funded account)."""
        return self.send(self.manifest["deployer"]["privateKey"], to, "0x", value=amount_wei)

    # -- token -----------------------------------------------------------------
    def faucet(self, to: str, amount_units: int) -> str:
        return self.send(
            self.manifest["deployer"]["privateKey"],
            self.token,
            SEL_FAUCET + abi_encode(["address", "uint256"], [to, amount_units]).hex(),
        )

    def balance_of(self, address: str) -> int:
        ret = self.call(self.token, SEL_BALANCE_OF + abi_encode(["address"], [address]).hex())
        return int(ret, 16)

    def approve(self, private_key: str, spender: str, amount_units: int) -> str:
        return self.send(
            private_key,
            self.token,
            SEL_APPROVE + abi_encode(["address", "uint256"], [spender, amount_units]).hex(),
        )

    def allowance(self, owner: str, spender: str) -> int:
        ret = self.call(
            self.token, SEL_ALLOWANCE + abi_encode(["address", "address"], [owner, spender]).hex()
        )
        return int(ret, 16)

    # -- escrow ----------------------------------------------------------------
    def create_duel(self, private_key: str, match_id: bytes, stake_units: int) -> str:
        return self.send(
            private_key,
            self.escrow,
            SEL_CREATE_DUEL + abi_encode(["bytes32", "uint256"], [match_id, stake_units]).hex(),
        )

    def join_duel(self, private_key: str, match_id: bytes) -> str:
        return self.send(
            private_key, self.escrow, SEL_JOIN_DUEL + abi_encode(["bytes32"], [match_id]).hex()
        )

    def settle_duel(
        self,
        private_key: str,
        match_id: bytes,
        winner: str,
        winner_ms: int,
        loser_ms: int,
        nonce: int,
        deadline: int,
        signature: bytes,
    ) -> str:
        encoded = abi_encode(
            ["(bytes32,address,uint256,uint256,uint256,uint256,bytes)"],
            [(match_id, winner, winner_ms, loser_ms, nonce, deadline, signature)],
        ).hex()
        return self.send(private_key, self.escrow, SEL_SETTLE_DUEL + encoded)

    def refund(self, private_key: str, match_id: bytes) -> str:
        return self.send(
            private_key, self.escrow, SEL_REFUND + abi_encode(["bytes32"], [match_id]).hex()
        )

    def duel_state(self, match_id: bytes) -> DuelState:
        ret = self.call(self.escrow, SEL_MATCHES + match_id.hex())
        data = ret.removeprefix("0x")
        words = [int(data[i * 64 : (i + 1) * 64], 16) for i in range(10)]
        addr = lambda w: "0x" + f"{w & ((1 << 160) - 1):040x}"  # noqa: E731
        return DuelState(
            match_id="0x" + f"{words[0]:064x}",
            player1=addr(words[1]),
            player2=addr(words[2]),
            stake_amount=words[3],
            total_pool=words[4],
            created_at=words[5],
            status=words[6],
            winner=addr(words[7]),
            winner_reaction_ms=words[8],
            loser_reaction_ms=words[9],
        )

    def escrow_payment_token(self) -> str:
        return "0x" + self.call(self.escrow, SEL_PAYMENT_TOKEN)[-40:]

    def escrow_oracle_signer(self) -> str:
        return "0x" + self.call(self.escrow, SEL_ORACLE_SIGNER)[-40:]

    # -- time ------------------------------------------------------------------
    def increase_time(self, seconds: int) -> None:
        self.rpc("evm_increaseTime", [seconds])
        self.rpc("evm_mine", [])

    def mine(self) -> None:
        self.rpc("evm_mine", [])


def match_id_bytes(raw: str) -> bytes:
    """The bytes32 key the escrow stores a duel under, from a server match id.

    Must equal `onchain._match_id_to_bytes32` and `oracle._match_id_bytes32` —
    a drift here is exactly the class of bug the pin tests exist to catch.
    """
    import hashlib

    clean = raw.lower().removeprefix("0x")
    if len(clean) == 64 and all(c in "0123456789abcdef" for c in clean):
        return bytes.fromhex(clean)
    return hashlib.sha256(raw.encode()).digest()
