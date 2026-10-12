"""Reusable fake JSON-RPC for the on-chain deposit gate (plan item 0.6).

`api/onchain.py` speaks plain JSON-RPC over `urllib.request.urlopen`. The legacy
probes monkeypatched that with three near-identical, copy-pasted stub classes;
this module is the single implementation they should have shared.

What it models (all of it is exercised by the real gate):
  eth_chainId                -> the deployment chain (chain-binding cross-check)
  eth_call paymentToken()    -> the escrow's token address
  eth_call decimals()        -> the token's decimals
  eth_call matches(bytes32)  -> the 10-word static DuelMatch struct
  eth_getTransactionReceipt  -> receipt with MatchSettled logs

Failure modes are first-class, because the interesting audit findings are all
about what happens when the RPC misbehaves (C2: a transient failure must not
become a sticky `None`; H9/H10: a dead RPC must fail closed without wedging).

Usage:
    rpc = FakeRpc(chain_id=80002, duel=active_duel(p1, p2, 1_000_000))
    rpc.install(monkeypatch)          # patches onchain.urllib.request.urlopen
    rpc.fail_next(2)                  # next 2 calls raise URLError
    rpc.return_malformed("decimals")  # a specific call returns garbage
"""

from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass, field
from typing import Any


# --- ABI helpers --------------------------------------------------------------
# Selectors are computed at runtime from the signature, exactly like onchain.py,
# so a signature change cannot silently desync the fake from the real caller.
def _keccak(data: bytes) -> bytes:
    from Crypto.Hash import keccak

    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def selector(signature: str) -> str:
    return "0x" + _keccak(signature.encode())[:4].hex()


SEL_PAYMENT_TOKEN = selector("paymentToken()")
SEL_DECIMALS = selector("decimals()")
SEL_MATCHES = selector("matches(bytes32)")

STATUS_NONE, STATUS_CREATED, STATUS_ACTIVE, STATUS_SETTLED = 0, 1, 2, 3
STATUS_CANCELLED, STATUS_REFUNDED = 4, 5


def word(value: int) -> str:
    return format(value, "064x")


def addr_word(address: str) -> str:
    """An address as a full 32-byte ABI word (what a real RPC returns)."""
    return "0" * 24 + address.lower().removeprefix("0x")


def match_settled_topic() -> str:
    return "0x" + _keccak(b"MatchSettled(bytes32,address,uint256,uint256)").hex()


@dataclass
class Duel:
    """The on-chain DuelMatch the fake reports for `matches(bytes32)`."""

    status: int = STATUS_ACTIVE
    player1: str = "0x" + "11" * 20
    player2: str = "0x" + "22" * 20
    stake_units: int = 1_000_000  # 1.0 USDT at 6 decimals
    winner: str = "0x" + "00" * 20

    def payload(self) -> str:
        """The 10-word static struct, in the order `onchain._decode_match` reads."""
        return "0x" + "".join(
            [
                "0" * 64,  # matchId
                addr_word(self.player1),  # player1
                addr_word(self.player2),  # player2
                word(self.stake_units),  # stakeAmount
                word(self.stake_units * 2),  # totalPool
                word(0),  # createdAt
                word(self.status),  # status
                addr_word(self.winner),  # winner
                word(0),  # winnerReactionMs
                word(0),  # loserReactionMs
            ]
        )


@dataclass
class FakeRpc:
    """A configurable JSON-RPC endpoint for the deposit gate."""

    chain_id: int = 80002
    token_address: str = "0x" + "77" * 20
    token_decimals: int = 6
    duel: Duel = field(default_factory=Duel)
    receipt: dict[str, Any] | None = None

    # failure injection
    fail_next_calls: int = 0
    malformed: set[str] = field(default_factory=set)
    malformed_selectors: set[str] = field(default_factory=set)
    calls: list[dict[str, Any]] = field(default_factory=list)

    # -- failure injection -----------------------------------------------------
    def fail_next(self, count: int = 1) -> None:
        """Make the next `count` RPC calls raise (simulates a network blip)."""
        self.fail_next_calls = count

    def return_malformed(self, method: str) -> None:
        """Break a whole JSON-RPC METHOD (e.g. every `eth_call`).

        Coarse on purpose: breaking every `eth_call` also breaks the duel read,
        so the gate short-circuits at "duel unreadable" before it ever reaches
        the code under test. Use `break_call` when the point is to break ONE
        contract call while the rest of the chain stays healthy.
        """
        self.malformed.add(method)

    def break_call(self, selector: str) -> None:
        """Break one ABI call (e.g. only `decimals()`) and leave the rest intact.

        This is the injection the C2 baseline needs: the duel must stay readable
        (status ACTIVE, matching stake and players) while `decimals()` alone is
        unreadable — otherwise the test passes for the wrong reason.
        """
        self.malformed_selectors.add(selector)

    # -- dispatch --------------------------------------------------------------
    def _result_for(self, method: str, params: list[Any]) -> Any:
        if method in self.malformed:
            return "0xdeadbeef"  # wrong shape on purpose

        if method == "eth_chainId":
            return hex(self.chain_id)

        if method == "eth_call":
            data = (params[0] or {}).get("data", "")
            for broken in self.malformed_selectors:
                if data.startswith(broken):
                    return "0xdeadbeef"  # wrong shape on purpose
            if data.startswith(SEL_PAYMENT_TOKEN):
                return "0x" + addr_word(self.token_address)
            if data.startswith(SEL_DECIMALS):
                return "0x" + word(self.token_decimals)
            if data.startswith(SEL_MATCHES):
                return self.duel.payload()
            return "0x"

        if method == "eth_getTransactionReceipt":
            return self.receipt

        return None

    def handle(self, request_body: bytes) -> bytes:
        try:
            request = json.loads(request_body.decode())
        except Exception:
            request = {"method": "eth_call", "params": []}
        method = request.get("method", "")
        params = request.get("params", []) or []
        self.calls.append({"method": method, "params": params})

        if self.fail_next_calls > 0:
            self.fail_next_calls -= 1
            raise urllib.error.URLError("simulated RPC outage")

        result = self._result_for(method, params)
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()

    def calls_to(self, method: str) -> int:
        return sum(1 for c in self.calls if c["method"] == method)

    # -- installation ----------------------------------------------------------
    def install(self, monkeypatch, module: Any = None) -> FakeRpc:
        """Patch `urllib.request.urlopen` for the onchain module."""
        if module is None:
            import onchain as module  # noqa: PLC0415

        fake = self

        class _Response:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None:
                return None

        def _urlopen(req, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            body = req.data if getattr(req, "data", None) else b"{}"
            return _Response(fake.handle(body))

        monkeypatch.setattr(module.urllib.request, "urlopen", _urlopen)
        return self


def configure_escrow(monkeypatch, rpc: FakeRpc, escrow_address: str = "0x" + "ab" * 20) -> FakeRpc:
    """Point the server's escrow config at the fake and reset its caches.

    `onchain` caches the chain check, the token decimals and per-match duel
    state at module level, so a test that installs a fake must start from a
    clean slate or it will silently read the previous test's answer.
    """
    import os

    import onchain

    monkeypatch.setenv("ESCROW_ADDRESS", escrow_address)
    monkeypatch.setenv("ESCROW_RPC_URL", "http://fake-rpc.invalid")
    monkeypatch.setenv("ORACLE_CHAIN_ID", str(rpc.chain_id))

    onchain._cache.clear()
    onchain._token_decimals = "unread"
    onchain._chain_id_checked = False
    onchain._chain_id_mismatch = False
    onchain._chain_mismatch_until = 0.0
    assert os.environ["ESCROW_ADDRESS"] == escrow_address
    return rpc.install(monkeypatch)
