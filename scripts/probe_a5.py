"""Audit #5 probe — deposit gate, rate limiting, matchmaking.

Audit #7 addition: production-shape regression guard. The original C1 bug
slipped through because every probe id was 64 hex chars ("ab"*32) — a shape
secrets.token_hex(16) NEVER mints. This probe now drives the gate with a real
32-char id and asserts the sha256-derived on-chain key, plus the new
chain-binding cross-check (wrong-chain RPC → fail-closed).

Run: .venv/bin/python scripts/probe_a5.py
"""
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("ORACLE_SIGNING_SECRET", "probe-secret")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)
os.environ.setdefault("ESCROW_RPC_URL", "http://127.0.0.1:1")  # dead port — fail-closed default

failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


# fastapi import first (TestClient + HTTPException)
import time as _time  # noqa: E402

import match_engine as me  # noqa: E402
import onchain  # noqa: E402
import main as server  # noqa: E402

m = me.Match(match_id="ab" * 32, stake=1.0, created_at=_time.time())
m.players["0x" + "a" * 40] = {"address": "0x" + "a" * 40, "joinedAt": 0}
m.creator = "0x" + "a" * 40
m.status = "active"

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Dead RPC → fail-closed (no crash)
try:
    server._verify_deposits_or_void(m)
    check("dead RPC → fail-closed 409", False)
except HTTPException as e:
    check(f"dead RPC → fail-closed 409 (got {e.status_code})", e.status_code == 409)
check("match untouched by failed gate", m.status == "active")

# Deposit-timeout void: CREATED + old match
m2 = me.Match(match_id="cd" * 32, stake=1.0, created_at=0)
m2.players["0x" + "b" * 40] = {"address": "0x" + "b" * 40, "joinedAt": 0}
m2.creator = "0x" + "b" * 40
m2.status = "active"
m2.created_at = 0  # ancient
import urllib.request  # noqa: E402
import json as _json  # noqa: E402
import hashlib as _hashlib  # noqa: E402


def _rpc_status_payload(status: int) -> str:
    """Mimic matches(bytes32): 10 static words, status is word index 6."""
    words = ["0" * 64 for _ in range(10)]
    words[6] = format(status, "064x")
    return "0x" + "".join(words)


class _FakeCreated:
    """RPC stub returning status=Created (1).

    Audit #7: method-aware — answers eth_chainId with the deployment chain so
    the chain-binding cross-check agrees with the stub (a real RPC would)."""

    status = 1

    def __init__(self, *a, **k) -> None:
        try:
            self._method = _json.loads(a[0].data.decode())["method"]
        except Exception:
            self._method = "eth_call"

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None

    def read(self) -> bytes:
        if self._method == "eth_chainId":
            result = hex(int(os.environ.get("ORACLE_CHAIN_ID", "80002")))
        else:
            result = _rpc_status_payload(self.status)
        body = '{"jsonrpc":"2.0","id":1,"result":"' + result + '"}'
        return body.encode()


orig_urlopen = onchain.urllib.request.urlopen
onchain.urllib.request.urlopen = _FakeCreated
try:
    gate = server._verify_deposits_or_void(m2)
    check("CREATED + timeout → void", isinstance(gate, dict) and gate.get("void") is True and m2.status == "void")
finally:
    onchain.urllib.request.urlopen = orig_urlopen

# ACTIVE passes — method-aware escrow stub with a FULL DuelMatch struct.
# Audit #8 F-03: the gate now reads paymentToken(), decimals() and the whole
# matches(bytes32) struct, so the stub must answer all three like a real RPC,
# and the server match must carry BOTH participants (an ACTIVE on-chain duel
# always has two).
onchain._cache.clear()
onchain._token_decimals = "unread"  # re-read decimals from the stub

_TOKEN_ADDR = "0x" + "0" * 24 + "77" * 20  # full 32-byte word, as a real RPC returns
_TOKEN_DECIMALS = 6
_STAKE_UNITS = 10 ** _TOKEN_DECIMALS  # 1.0 USDT
_SEL_TOKEN = onchain._selector("paymentToken()")
_SEL_DECIMALS = onchain._selector("decimals()")
_SEL_MATCHES = onchain._matches_selector()


def _addr_word(addr: str) -> str:
    return "0" * 24 + addr[2:].lower()


def _struct_payload(status: int, p1: str, p2: str, stake_units: int) -> str:
    """Encode the 10-word static DuelMatch struct (layout per _decode_match)."""
    words = [
        "0" * 64,  # matchId
        _addr_word(p1),  # player1
        _addr_word(p2),  # player2
        format(stake_units, "064x"),  # stakeAmount
        format(stake_units * 2, "064x"),  # totalPool
        "0" * 64,  # createdAt
        format(status, "064x"),  # status
        "0" * 64,  # winner
        "0" * 64,
        "0" * 64,
    ]
    return "0x" + "".join(words)


class _FakeEscrowRPC:
    """Answers eth_chainId, paymentToken(), decimals() and matches(bytes32)."""

    status = 2
    p1 = "0x" + "c" * 40
    p2 = "0x" + "f" * 40
    stake_units = _STAKE_UNITS
    calls: list = []

    def __init__(self, *a, **k) -> None:
        try:
            req = _json.loads(a[0].data.decode())
            self._method = req.get("method", "eth_call")
            try:
                self._calldata = req["params"][0]["data"]
            except Exception:
                self._calldata = ""  # eth_chainId and friends carry no calldata
        except Exception:
            self._method, self._calldata = "eth_call", ""
        _FakeEscrowRPC.calls.append(self._calldata)

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None

    def read(self) -> bytes:
        if self._method == "eth_chainId":
            result = hex(int(os.environ.get("ORACLE_CHAIN_ID", "80002")))
        elif self._calldata.startswith(_SEL_TOKEN):
            result = _TOKEN_ADDR
        elif self._calldata.startswith(_SEL_DECIMALS):
            result = format(_TOKEN_DECIMALS, "064x")
        else:  # matches(bytes32)
            result = _struct_payload(self.status, self.p1, self.p2, self.stake_units)
        return ('{"jsonrpc":"2.0","id":1,"result":"' + result + '"}').encode()


def _active_match(mid: str, creator: str, joiner: str) -> Any:
    m = me.Match(match_id=mid, stake=1.0, created_at=_time.time())
    for p in (creator, joiner):
        m.players[p] = {"address": p, "joinedAt": 0}
    m.creator = creator
    m.status = "active"
    return m


onchain.urllib.request.urlopen = _FakeEscrowRPC
try:
    m3 = _active_match("ef" * 32, _FakeEscrowRPC.p1, _FakeEscrowRPC.p2)
    check("ACTIVE (matching struct) → play on", server._verify_deposits_or_void(m3) is None)

    # F-03 regression: creator locks a dust stake while the UI promises 1.96
    _FakeEscrowRPC.stake_units = 1
    onchain._cache.clear()
    gate = server._verify_deposits_or_void(m3)
    check(
        "ACTIVE but dust stake → void (F-03)",
        isinstance(gate, dict) and gate.get("void") is True and m3.status == "void",
    )

    # F-03 regression: deposited from wallet W2, playing as W1
    m3.status = "active"
    _FakeEscrowRPC.stake_units = _STAKE_UNITS
    _FakeEscrowRPC.p2 = "0x" + "9" * 40
    onchain._cache.clear()
    gate = server._verify_deposits_or_void(m3)
    check(
        "ACTIVE but wrong participants → void (F-03)",
        isinstance(gate, dict) and gate.get("void") is True and m3.status == "void",
    )
finally:
    onchain.urllib.request.urlopen = orig_urlopen
    onchain._cache.clear()

# --- AUDIT #7 REGRESSION GUARD: production id shape through an ACTIVE gate ---
onchain._cache.clear()
onchain._chain_id_checked = False
onchain._chain_id_mismatch = False
onchain._token_decimals = "unread"  # re-read from the stub after it is swapped in
os.environ["ESCROW_ADDRESS"] = "0x" + "ab" * 20

raw_prod_id = "9f2c41a7b8d3e5061728394a5b6c7d8e"  # secrets.token_hex(16)-shaped
_FakeEscrowRPC.p1 = "0x" + "e" * 40
_FakeEscrowRPC.p2 = "0x" + "8" * 40
_FakeEscrowRPC.stake_units = _STAKE_UNITS
m_prod = _active_match(raw_prod_id, _FakeEscrowRPC.p1, _FakeEscrowRPC.p2)

onchain.urllib.request.urlopen = _FakeEscrowRPC
try:
    _FakeEscrowRPC.calls = []
    check("PROD-SHAPE 32-char id → ACTIVE gate passes", server._verify_deposits_or_void(m_prod) is None)
    expected_key = "0x" + _hashlib.sha256(raw_prod_id.encode()).hexdigest()
    matches_calls = [c for c in _FakeEscrowRPC.calls if c.startswith(_SEL_MATCHES)]
    cd = matches_calls[0] if matches_calls else ""
    check(
        "gate queried sha256(matchId) as the on-chain key",
        bool(cd) and cd.endswith(expected_key[2:]) and len(cd) == 10 + 64,
    )
finally:
    onchain.urllib.request.urlopen = orig_urlopen
    onchain._cache.clear()


class _FakeWrongChain(_FakeCreated):
    """RPC answering eth_chainId with mainnet (0x1) while deployment expects
    80002 — every read must fail CLOSED."""

    def read(self) -> bytes:
        if self._method == "eth_chainId":
            result = "0x1"
        else:
            result = _rpc_status_payload(2)
        return '{"jsonrpc":"2.0","id":1,"result":"' + result + '"}'.encode()


onchain._chain_id_checked = False
onchain._chain_id_mismatch = False
onchain.urllib.request.urlopen = _FakeWrongChain
try:
    check("chain mismatch → duel_status fails closed (None)", onchain.duel_status(raw_prod_id) is None)
    try:
        server._verify_deposits_or_void(m_prod)
        check("gate on mismatched chain → 409, never a crash", False)
    except HTTPException as e:
        check("gate on mismatched chain → 409, never a crash", e.status_code == 409)
finally:
    onchain.urllib.request.urlopen = orig_urlopen
    onchain._chain_id_checked = False
    onchain._chain_id_mismatch = False
    onchain._cache.clear()

# --- Rate limiter (memory mode) ----------------------------------------------
os.environ.pop("ESCROW_ADDRESS", None)
server._rl_window.clear()
client = TestClient(server.app)
codes = []
for _ in range(server.RL_AUTH_MAX + 3):
    r = client.post("/api/auth/nonce", json={"address": "0x" + "d" * 40}, headers={"host": "t.test"})
    codes.append(r.status_code)
check(f"auth rate limit kicks in (codes tail: {codes[-4:]})", 429 in codes and codes[-1] == 429)

# --- Matchmaking still works with the gate inactive ---------------------------
server._rl_window.clear()
from eth_account import Account  # noqa: E402

acct = Account.create()
token_acct = Account.create()
from eth_account.messages import encode_defunct  # noqa: E402


def session(acct) -> tuple[str, str]:
    addr = acct.address.lower()
    r = client.post("/api/auth/nonce", json={"address": addr}, headers={"host": "t.test"})
    assert r.status_code == 200, r.text
    nonce = r.json()["nonce"]
    msg = server._siwe_message(addr, nonce, "t.test")
    sig = acct.sign_message(encode_defunct(text=msg)).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    r = client.post("/api/auth/verify", json={"message": msg, "signature": sig}, headers={"host": "t.test"})
    assert r.status_code == 200, r.text
    return r.json()["token"], addr


t1, a1 = session(acct)
r = client.post("/api/queue", json={"stake": 1.0}, headers={"host": "t.test", "Authorization": f"Bearer {t1}"})
check(f"queue works (gate inactive) — {r.status_code}", r.status_code == 200)
check("youAreCreator on first enqueue", r.json().get("youAreCreator") is True)

t2, a2 = session(token_acct)
r2 = client.post("/api/queue", json={"stake": 1.0}, headers={"host": "t.test", "Authorization": f"Bearer {t2}"})
check(f"second player matched — {r2.status_code}", r2.status_code == 200)
check("joiner role exposed", r2.json().get("youAreJoiner") is True and r2.json().get("youAreCreator") is False)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
