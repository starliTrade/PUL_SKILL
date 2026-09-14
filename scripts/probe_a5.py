"""Audit #5 sanity probe — deposit gate + rate limiter + matchmaking.

Run: .venv/bin/python scripts/probe_a5.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("ORACLE_SIGNING_SECRET", "probe-secret")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

from fastapi.testclient import TestClient  # noqa: E402

import main as server  # noqa: E402

failures = []


def check(name: str, cond: bool) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


check("main imports with the new gate + limiter", hasattr(server, "_verify_deposits_or_void"))

# --- Deposit gate: unconfigured escrow = inactive ----------------------------
import onchain  # noqa: E402

os.environ.pop("ESCROW_ADDRESS", None)
check("gate inactive when escrow unconfigured", onchain.escrow_configured() is False)

# Gate against a fake active match with escrow configured but unreachable RPC
os.environ["ESCROW_ADDRESS"] = "0x" + "ab" * 20
os.environ["ESCROW_RPC_URL"] = "http://127.0.0.1:1"  # dead port → fail-closed
onchain._cache.clear()

import match_engine as me  # noqa: E402

import time as _time  # noqa: E402

m = me.Match(match_id="ab" * 32, stake=1.0, created_at=_time.time())
m.players["0x" + "a" * 40] = {"address": "0x" + "a" * 40, "joinedAt": 0}
m.creator = "0x" + "a" * 40
m.status = "active"

from fastapi import HTTPException  # noqa: E402

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


def _rpc_status_payload(status: int) -> str:
    """Mimic matches(bytes32): 10 static words, status is word index 6."""
    words = ["0" * 64 for _ in range(10)]
    words[6] = format(status, "064x")
    return "0x" + "".join(words)


class _FakeCreated:
    """RPC stub returning status=Created (1)."""

    def __init__(self, *a, **k) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None

    def read(self) -> bytes:
        body = '{"jsonrpc":"2.0","id":1,"result":"' + _rpc_status_payload(1) + '"}'
        return body.encode()


orig_urlopen = onchain.urllib.request.urlopen
onchain.urllib.request.urlopen = _FakeCreated
try:
    gate = server._verify_deposits_or_void(m2)
    check("CREATED + timeout → void", isinstance(gate, dict) and gate.get("void") is True and m2.status == "void")
finally:
    onchain.urllib.request.urlopen = orig_urlopen

# ACTIVE passes
onchain._cache.clear()


class _FakeActive(_FakeCreated):
    def read(self) -> bytes:
        body = '{"jsonrpc":"2.0","id":1,"result":"' + _rpc_status_payload(2) + '"}'
        return body.encode()


onchain.urllib.request.urlopen = _FakeActive
try:
    m3 = me.Match(match_id="ef" * 32, stake=1.0, created_at=_time.time())
    m3.players["0x" + "c" * 40] = {"address": "0x" + "c" * 40, "joinedAt": 0}
    m3.creator = "0x" + "c" * 40
    m3.status = "active"
    check("ACTIVE → play on", server._verify_deposits_or_void(m3) is None)
finally:
    onchain.urllib.request.urlopen = orig_urlopen
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
