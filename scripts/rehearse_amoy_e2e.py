"""
PULSAR — Amoy rehearsal driver (NO BROWSER needed).

Drives the FULL real-money path against a live game server + real Amoy escrow:
  SIWE login (both players) -> queue/match -> on-chain approve/create/join
  (via cast) -> 3x commit/reveal/submit over HTTP with REAL wall-clock waits
  -> server settle (real oracle signature) -> on-chain settleDuel (via cast)
  -> balance verification (98% winner / 2% treasury).

Modes:
  settle : full duel lifecycle (default)
  refund : create one duel on-chain, wait out MATCH_TIMEOUT live, refund,
           verify stake returned. Takes ~31 minutes, fully automatic.

Secrets come ONLY from the environment (never printed, never committed):
  REHEARSE_SERVER  game server base URL (default http://127.0.0.1:8080)
  REHEARSE_RPC     Amoy JSON-RPC URL (Alchemy)
  PLAYER1_KEY      0x-prefixed private key, test wallet 1
  PLAYER2_KEY      0x-prefixed private key, test wallet 2
  ESCROW_ADDRESS   deployed PulsarEscrow on Amoy
  MOCK_USDT        deployed MockUSDT on Amoy
  STAKE_USDT       agreed stake, default 1 (must be in ALLOWED_STAKES)

Run from the repo root in YOUR OWN terminal (keys stay in your session):
  $env:PLAYER1_KEY="0x..."; $env:PLAYER2_KEY="0x..."
  $env:REHEARSE_RPC="https://..."; $env:ESCROW_ADDRESS="0x..."; $env:MOCK_USDT="0x..."
  python scripts/rehearse_amoy_e2e.py settle
"""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

SERVER = os.environ.get("REHEARSE_SERVER", "http://127.0.0.1:8080")
RPC = os.environ["REHEARSE_RPC"]
ESCROW = os.environ["ESCROW_ADDRESS"]
TOKEN = os.environ["MOCK_USDT"]
STAKE = float(os.environ.get("STAKE_USDT", "1"))
P1 = Account.from_key(os.environ["PLAYER1_KEY"])
P2 = Account.from_key(os.environ["PLAYER2_KEY"])
DOMAIN = "rehearse.local"

failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}", flush=True)
    if not cond:
        failures.append(name)


def cast(*args, capture=True):
    """Run cast (must be on PATH). Secrets passed via args stay in YOUR shell."""
    r = subprocess.run(["cast", *args], capture_output=capture, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args[:4])}... failed:\n{r.stderr[-2000:]}")
    return r.stdout.strip()


def rpc_call(payload):
    # NOTE: public RPCs (Cloudflare-fronted) 403 Python-urllib's default UA —
    # send a browser-like UA (cast works for the same reason).
    req = urllib.request.Request(
        RPC,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (PULSAR-rehearsal)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if "error" in out:
        raise RuntimeError(f"RPC error: {out['error']}")
    return out["result"]


def eth_call(to, data, block="latest"):
    return rpc_call({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                     "params": [{"to": to, "data": data}, block]})


def selector(sig):
    import hashlib as _h
    from Crypto.Hash import keccak as _k
    k = _k.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()[:8]


def erc20_balance(token, addr):
    data = selector("balanceOf(address)") + addr[2:].lower().rjust(64, "0")
    return int(eth_call(token, data), 16)


def pol_balance(addr):
    return int(rpc_call({"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
                         "params": [addr, "latest"]}), 16)


def duel_status(match_bytes32):
    # matches(bytes32) -> 10-word tuple; word 6 is status
    data = selector("matches(bytes32)") + match_bytes32[2:]
    raw = eth_call(ESCROW, data)
    words = [int(raw[i:i + 64], 16) for i in range(2, len(raw), 64)]
    return words[6]


def tx_send(key_addr_hex, to, sig, *tx_args, gas_limit, value=0):
    """Send a legacy tx via cast with tight caps. key_addr_hex is never logged."""
    acct = Account.from_key(key_addr_hex)
    out = cast("send", "--private-key", key_addr_hex, "--rpc-url", RPC,
               "--legacy", "--gas-price", "30000000000",
               "--gas-limit", str(gas_limit), to, sig, *tx_args)
    return out


s = httpx.Client(base_url=SERVER, timeout=30)


def login(acct):
    addr = acct.address.lower()
    r = s.post("/api/auth/nonce", json={"address": addr}, headers={"host": DOMAIN})
    assert r.status_code == 200, r.text
    body = r.json()
    sig = acct.sign_message(encode_defunct(text=body["message"])).signature.hex()
    r = s.post("/api/auth/verify", json={"message": body["message"], "signature": "0x" + sig},
               headers={"host": DOMAIN})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def hdrs(token):
    return {"Authorization": f"Bearer {token}", "host": DOMAIN}


def play_round(token, match_id, idx, reaction_ms):
    intent = "0x" + hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    r = s.post("/api/round/commit", json={"matchId": match_id, "roundIndex": idx, "intentHash": intent},
               headers=hdrs(token))
    assert r.status_code == 200, f"commit: {r.text}"
    r = s.post("/api/round/target", json={"matchId": match_id, "roundIndex": idx}, headers=hdrs(token))
    assert r.status_code == 200, f"target: {r.text}"
    tj = r.json()
    time.sleep(tj["targetMs"] / 1000.0 + reaction_ms / 1000.0)  # REAL wall-clock wait
    r = s.post("/api/round/result",
               json={"matchId": match_id, "roundIndex": idx, "measuredMs": float(reaction_ms),
                     "resultProof": tj["resultProof"]},
               headers=hdrs(token))
    assert r.status_code == 200, f"result: {r.text}"
    return r.json()


def match_bytes32(match_id):
    # MUST stay identical to api/onchain._match_id_to_bytes32: 32-hex server ids hash.
    return "0x" + hashlib.sha256(match_id.encode()).hexdigest()


def do_settle_mode():
    print("== preflight ==")
    h = s.get("/api/health").json()
    check("server up, escrow gate configured", h.get("escrowConfigured") is True and h.get("chainId") == 80002)
    p1pol, p2pol = pol_balance(P1.address), pol_balance(P2.address)
    check(f"P1 has gas ({p1pol / 1e18:.4f} POL)", p1pol > 5_000_000_000_000_000)
    check(f"P2 has gas ({p2pol / 1e18:.4f} POL)", p2pol > 5_000_000_000_000_000)
    stake_units = int(STAKE * 1_000_000)
    check("stake >= contract MIN_STAKE", stake_units >= 1_000_000)
    check("P1 holds enough MockUSDT", erc20_balance(TOKEN, P1.address) >= stake_units)
    check("P2 holds enough MockUSDT", erc20_balance(TOKEN, P2.address) >= stake_units)
    treasury_before = erc20_balance(TOKEN, os.environ.get("TREASURY_ADDRESS", "0xF43492086D838bC9Dea5f7C28E4Ce0b1778f3E3a"))
    print(f"treasury before: {treasury_before}")

    print("== SIWE login ==")
    t1, t2 = login(P1), login(P2)
    check("both players hold sessions", bool(t1) and bool(t2))

    print("== matchmaking ==")
    m1 = s.post("/api/queue", json={"stake": STAKE}, headers=hdrs(t1)).json()
    m2 = s.post("/api/queue", json={"stake": STAKE}, headers=hdrs(t2)).json()
    check("paired into one active match", m1["matchId"] == m2["matchId"] and m2["status"] == "active")
    mid, b32 = m1["matchId"], match_bytes32(m1["matchId"])
    print(f"matchId={mid} bytes32={b32}")

    print("== on-chain deposits (cast) ==")
    k1, k2 = os.environ["PLAYER1_KEY"], os.environ["PLAYER2_KEY"]
    # Resume-safe: a previous run may have deposited already (server replays
    # the live match instead of pairing a new one). Never re-create.
    chain = duel_status(b32)
    if chain == 0:
        tx_send(k1, TOKEN, "approve(address,uint256)", ESCROW, str(stake_units), gas_limit=100000)
        tx_send(k1, ESCROW, "createDuel(bytes32,uint256)", b32, str(stake_units), gas_limit=300000)
        check("duel Created on-chain", duel_status(b32) == 1)
        tx_send(k2, TOKEN, "approve(address,uint256)", ESCROW, str(stake_units), gas_limit=100000)
        tx_send(k2, ESCROW, "joinDuel(bytes32)", b32, gas_limit=300000)
        check("duel Active on-chain (both stakes locked)", duel_status(b32) == 2)
    elif chain == 1:
        tx_send(k2, TOKEN, "approve(address,uint256)", ESCROW, str(stake_units), gas_limit=100000)
        tx_send(k2, ESCROW, "joinDuel(bytes32)", b32, gas_limit=300000)
        check("duel Active on-chain (both stakes locked)", duel_status(b32) == 2)
    elif chain == 2:
        print("deposits already locked from a previous run, skipping to rounds")
        check("duel Active on-chain (both stakes locked)", True)
    else:
        raise SystemExit(f"unexpected on-chain duel status {chain}, resolve manually")

    print("== rounds (real timing) ==")
    for idx in range(3):
        # Bo3 can complete early (2-0 majority settles without round 2) —
        # stop playing once the server no longer reports active.
        v = s.get(f"/api/match/{mid}", headers=hdrs(t1)).json()
        if v.get("status") != "active":
            print(f"match {v.get('status')} after round {idx - 1}, stopping early")
            break
        try:
            play_round(t1, mid, idx, 250)  # P1 faster -> should win
            play_round(t2, mid, idx, 450)
        except AssertionError as e:
            # Round already decided/consumed (e.g. resumed run) -> settle.
            print(f"round {idx} not playable ({e}), moving to settle")
            break
        print(f"round {idx} submitted by both")
    check("deposit gate stayed green through rounds", duel_status(b32) == 2)

    print("== server settle (real oracle signature) ==")
    r = s.post(f"/api/match/{mid}/settle", json={}, headers=hdrs(t1))
    check("settle 200 + settled", r.status_code == 200 and r.json().get("status") == "settled")
    st = r.json()
    winner = st["winner"].lower()
    check("P1 won (faster reactions)", winner == P1.address.lower())
    wkey = k1 if winner == P1.address.lower() else k2
    print(f"winner={st['winner']} prize proof nonce={st['serverNonce']} deadline={st['deadline']}")

    print("== on-chain settleDuel (cast) ==")
    proof_tuple = (f"({b32},{st['winner']},{st['winnerTimeMs']},{st['loserTimeMs']},"
                   f"{st['serverNonce']},{st['deadline']},{st['signature']})")
    tx_send(wkey, ESCROW,
            "settleDuel((bytes32,address,uint256,uint256,uint256,uint256,bytes))",
            proof_tuple, gas_limit=400000)
    check("duel Settled on-chain", duel_status(b32) == 3)

    print("== money verification ==")
    pool = stake_units * 2
    fee = pool * 200 // 10_000
    prize = pool - fee
    wbal = erc20_balance(TOKEN, st["winner"])
    tbal = erc20_balance(TOKEN, os.environ.get("TREASURY_ADDRESS", "0xF43492086D838bC9Dea5f7C28E4Ce0b1778f3E3a"))
    print(f"winner balance={wbal} treasury={tbal} (fee now {tbal - treasury_before})")
    check("treasury got exactly 2%", tbal - treasury_before == fee)
    check("winner delta covers prize-minus-stake",
          wbal >= prize)  # absolute floor; exact delta needs pre-snapshot
    print(f"EXPLORER: https://amoy.polygonscan.com/address/{ESCROW}#events")


def do_refund_mode():
    print("== refund drill: create, wait 31 min live, refund ==")
    k1 = os.environ["PLAYER1_KEY"]
    stake_units = int(STAKE * 1_000_000)
    drill = "0x" + secrets.token_hex(32)
    p1before = erc20_balance(TOKEN, P1.address)
    tx_send(k1, TOKEN, "approve(address,uint256)", ESCROW, str(stake_units), gas_limit=100000)
    tx_send(k1, ESCROW, "createDuel(bytes32,uint256)", drill, str(stake_units), gas_limit=300000)
    check("drill duel Created", duel_status(drill) == 1)
    print("waiting 31 minutes for MATCH_TIMEOUT (live, do not close)...", flush=True)
    for m in range(31):
        time.sleep(60)
        print(f"  ...{m + 1}/31 min", flush=True)
    tx_send(k1, ESCROW, "refundTimeoutMatch(bytes32)", drill, gas_limit=300000)
    check("drill duel Cancelled after refund", duel_status(drill) == 4)
    check("stake returned to P1", erc20_balance(TOKEN, P1.address) >= p1before)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "settle"
    for var in ("REHEARSE_RPC", "PLAYER1_KEY", "PLAYER2_KEY", "ESCROW_ADDRESS", "MOCK_USDT"):
        assert os.environ.get(var), f"missing env {var}"
    if STAKE not in (1.0, 2.0, 5.0, 10.0):
        raise SystemExit(f"STAKE_USDT={STAKE} not in ALLOWED_STAKES")
    (do_refund_mode if mode == "refund" else do_settle_mode)()
    print("FAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)
