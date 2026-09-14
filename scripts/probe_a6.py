"""Audit #6 quick probe: economy ledger wiring + C1 sha256 convention.

Run: .venv/bin/python scripts/probe_a6.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("ORACLE_SIGNING_SECRET", "probe-a6-secret")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)

import match_engine as me  # noqa: E402
import onchain  # noqa: E402

failures = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        failures.append(name)


# --- C1: sha256 convention shared with client + oracle ------------------------
raw_id = "3f9a1b2c4d5e6f708192a3b4c5d6e7f0"  # 32 chars like secrets.token_hex(16)
key = onchain._match_id_to_bytes32(raw_id)
import hashlib

expected = "0x" + hashlib.sha256(raw_id.encode()).hexdigest()
check("C1: onchain key == sha256(raw id) (client+oracle convention)", key == expected)
check("C1: 64-hex ids pass through unchanged", onchain._match_id_to_bytes32("ab" * 32) == "0x" + "ab" * 32)
# The C1 crash: a 32-char id must NOT raise anymore
try:
    onchain._match_id_to_bytes32(raw_id)
    check("C1: 32-char id no longer raises ValueError", True)
except ValueError:
    check("C1: 32-char id no longer raises ValueError", False)

# duel_status never raises (fail-closed contract, not fail-500)
try:
    onchain.duel_status("unconfigured")  # escrow not configured -> None
    check("C1: duel_status never raises (returns None unconfigured)", True)
except Exception as e:
    check(f"C1: duel_status never raises (got {e})", False)

# --- C4: proof secret derived from the shared secret --------------------------
secret2 = "probe-a6-secret"
derived = hashlib.pbkdf2_hmac(
    "sha256", secret2.encode(), b"pulsar/result-proof/v1", dklen=32, iterations=1
)
check("C4: _PROOF_SECRET is the deterministic HKDF derivation", bytes(me._PROOF_SECRET) == derived)
check("C4: proof secret != raw signing secret", bytes(me._PROOF_SECRET) != secret2.encode())

# --- C2: MAC-verified nonces ---------------------------------------------------
import auth as auth_module  # noqa: E402

good = auth_module.issue_nonce("0x" + "a" * 40, "t.test")
check("C2: server-issued nonce is fresh", auth_module.nonce_is_fresh(good))
check("C2: nonce_window returns a window for a real nonce", auth_module.nonce_window(good) is not None)
forged_payload = auth_module._b64url_hex(f"t.test|{'0x' + 'a' * 40}|999999|deadbeef".encode())
check("C2: self-forged nonce FAILS nonce_window (MAC)", auth_module.nonce_window(forged_payload + ".0" * 64) is None)
check("C2: self-forged nonce fails freshness", not auth_module.nonce_is_fresh(forged_payload + ".0" * 64))
check("C2: tampered MAC fails", auth_module.nonce_window(good[:-4] + "beef") is None)

# --- main.py wiring -------------------------------------------------------------
import main as server  # noqa: E402

check("claim endpoint registered", any(r.path == "/api/match/{match_id}/claim" for r in server.app.routes))
check("record_settlement wired into settle path", "economy.record_settlement" in open("api/main.py").read())
check("RL_VERIFY_MAX defined", server.RL_VERIFY_MAX >= 20)
check("RL_ROUND_MAX defined", server.RL_ROUND_MAX >= 40)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
