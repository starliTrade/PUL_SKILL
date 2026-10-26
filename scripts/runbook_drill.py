"""Rehearse the incident runbook (plan item 11.2).

"Runbook rehearsed" means one thing: an operator who has never seen this system
can FOLLOW THE DOCUMENT and reach the right conclusion. So this drill does not
test the server — it tests the DOCUMENT. It breaks a dependency, then walks
§0's diagnostic table and asserts that each field the runbook names actually
reads the "bad value" the runbook says it will, then walks §1's recovery.

If the runbook says "`rpc.reachable` false" and the field says something else,
the runbook is wrong and an operator would be misled at 3am. That is the failure
this exists to catch.

Usage: .venv/bin/python scripts/runbook_drill.py
Exit:  0 every documented signal behaved as documented, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API = os.environ.get("PULSAR_DRILL_API", "http://127.0.0.1:8000")
ANVIL_PORT = os.environ.get("PULSAR_ANVIL_PORT", "8545")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from foundry_bin import foundry_path_env  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def get(path: str, timeout: float = 15) -> dict:
    req = urllib.request.Request(API + path)
    req.add_header("Host", "127.0.0.1:8000")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read() or b"{}")


def _sign_in() -> str | None:
    """A real SIWE session — an unauthenticated 401 is not a refusal."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    account = Account.create()
    req = urllib.request.Request(
        API + "/api/auth/nonce",
        data=json.dumps({"address": account.address.lower()}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        message = json.loads(res.read())["message"]
    signature = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    req = urllib.request.Request(
        API + "/api/auth/verify",
        data=json.dumps({"message": message, "signature": signature}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            token = json.loads(res.read()).get("token")
    except Exception:  # noqa: BLE001
        return None
    if token is None:
        return None
    # Plan item 11.3/G2: the queue requires a server-recorded attestation.
    req = urllib.request.Request(
        API + "/api/eligibility/confirm",
        data=json.dumps({"ageConfirmed": True}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:  # noqa: BLE001
        return None
    return token


def _pair_a_match() -> str | None:
    """Queue two authenticated players and return the match id."""
    a, b = _sign_in(), _sign_in()
    if not a or not b:
        return None
    for token in (a, b):
        req = urllib.request.Request(
            API + "/api/queue",
            data=json.dumps({"stake": 1, "rttMs": 40}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                view = json.loads(res.read())
        except Exception:  # noqa: BLE001
            return None
        if view.get("status") == "active":
            return view.get("matchId")
    return None


def anvil_up() -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{ANVIL_PORT}",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def stop_anvil() -> None:
    subprocess.run(["pkill", "-f", f"anvil --port {ANVIL_PORT}"], capture_output=True, check=False)


def start_anvil() -> None:
    env = {**os.environ, "PATH": foundry_path_env()}
    subprocess.run(["bash", os.path.join(ROOT, "scripts", "start_anvil.sh"), "--bg"],
                   cwd=ROOT, env=env, capture_output=True, check=False)


def main() -> int:
    print("[drill] §0 — what does the server think is happening?")
    if not anvil_up():
        start_anvil()
        time.sleep(2)
    check("the RPC is up before the drill", anvil_up())

    before = get("/api/health")
    check("§0 `ok` is true on a healthy server", before.get("ok") is True)
    check("§0 `matchStore` is `firestore` (memory = no durability)",
          before.get("matchStore") == "firestore", str(before.get("matchStore")))
    check("§0 `rpc.reachable` is true while the RPC is up",
          (before.get("rpc") or {}).get("reachable") is True)
    check("§0 `escrowConfigured` is true when money is enabled",
          before.get("escrowConfigured") is True)
    check("§0 `tokenDecimals` is a number, not \"unread\"",
          isinstance(before.get("tokenDecimals"), int), str(before.get("tokenDecimals")))

    # --- break it, the way §1 describes --------------------------------------
    print("\n[drill] §1 — the RPC is down or unreachable")
    stop_anvil()
    check("the RPC is down", not anvil_up())

    # §0 says the reachability probe is cooldown-cached; the runbook tells the
    # operator to wait past it rather than conclude the signal is broken.
    time.sleep(7)
    during = get("/api/health")
    check("§0 `ok` stays true — the PROCESS is up, the dependency is not",
          during.get("ok") is True)
    check("§0 `rpc.reachable` reads FALSE, exactly as the table says",
          (during.get("rpc") or {}).get("reachable") is False,
          f"reachable={(during.get('rpc') or {}).get('reachable')}")

    # §1's expected operator-visible effect, quoted from the runbook:
    #   "`/api/round/result` returns the deposit-gate error"
    #   "The deposit gate fails CLOSED — a round cannot be played until the stake
    #    is confirmed on chain."
    #
    # Two corrections to my first attempt, both from reading the document instead
    # of assuming: the refusal is on the ROUND endpoints (the QUEUE is just a
    # queue entry and correctly still accepts), and the request must be
    # AUTHENTICATED — an unauthenticated 401 says "I do not know who you are",
    # not "the gate refused you", and would have been a false green.
    token = _sign_in()
    if token is None:
        check("§1 the deposit gate refuses a round while the RPC is down", False,
              "could not sign in — the drill cannot test the gate without a session")
    else:
        # A REAL match. The first version used a fabricated matchId and got
        # `409 {"detail":"Match not found"}` — a 409, so the check "passed" while
        # testing nothing about the gate. The drill has to reach the gate.
        real_match = _pair_a_match()
        if real_match is None:
            check("§1 the deposit gate refuses a round while the RPC is down", False,
                  "could not create a match to test the gate against")
            real_match = "a" * 32
        try:
            req = urllib.request.Request(
                API + "/api/round/result",
                data=json.dumps({
                    "matchId": real_match, "roundIndex": 0, "measuredMs": 250.0, "resultProof": "",
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            )
            urllib.request.urlopen(req, timeout=20).read()
            check("§1 the deposit gate refuses a round while the RPC is down", False, "it was accepted")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()[:160]
            # The runbook says the response is the DEPOSIT-GATE error. A 404 or a
            # validation error would mean the drill never reached the gate.
            gate_error = "deposit" in body.lower() or "on-chain" in body.lower()
            check(
                "§1 the deposit gate refuses a round while the RPC is down",
                exc.code in (409, 503) and gate_error,
                f"status={exc.code} body={body}",
            )
        except Exception as exc:  # noqa: BLE001
            check("§1 the deposit gate refuses a round while the RPC is down", False, str(exc)[:80])

    # §1 names `tokenDecimals: "unread"` as a symptom. MEASURED: it reads the
    # real value, because a SUCCESSFUL decimals read IS cached and the decimals
    # do not change. "unread" only appears when the RPC was down from the start.
    #
    # So the runbook's symptom is imprecise in a way that matters: an operator
    # following it would see `6`, conclude the RPC is fine, and look elsewhere.
    # The drill records the disagreement instead of hiding it — and the runbook
    # is corrected in the same commit.
    check(
        "§1 tokenDecimals keeps its last good value while the RPC is down (the "
        "runbook says 'unread' — corrected)",
        during.get("tokenDecimals") == 6,
        str(during.get("tokenDecimals")),
    )

    # --- recovery, the way §1 describes --------------------------------------
    print("\n[drill] §1 — recovery")
    start_anvil()
    check("the RPC is back", anvil_up())
    time.sleep(7)
    after = get("/api/health")
    check("§0 `rpc.reachable` is true again", (after.get("rpc") or {}).get("reachable") is True)
    check("§0 `ok` is still true", after.get("ok") is True)

    failed = [name for ok, name in _results if not ok]
    print("\n" + "=" * 60)
    print(f"runbook drill: {len(_results) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("The runbook and the server DISAGREE on:")
        for name in failed:
            print(f"  - {name}")
        print("An operator following the document would be misled.")
        return 1
    print("Every signal the runbook names behaved as the runbook says.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
