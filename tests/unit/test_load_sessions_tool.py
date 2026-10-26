"""Audit L-06 — the session-minting tool the load run depends on.

`scripts/load_sessions.py` exists because 1000 real SIWE handshakes are not
possible against a server that allows 30 verifications per minute per IP. It
mints tokens through the SAME `auth.issue_session` the handshake uses, so a token
it produces is indistinguishable from a signed-in player's — and every request
still passes the server's own verification.

These tests pin that (a) the tool refuses to run without the signing secret,
(b) the tokens it writes really verify, and (c) the addresses are distinct —
sharing them would measure the per-address rate limiter instead of the queue.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

SECRET = "0x" + "11" * 32


def _run(tmp_path: Path, *args: str, secret: str | None = SECRET):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "api")}
    env.pop("ORACLE_SIGNING_SECRET", None)
    if secret:
        env["ORACLE_SIGNING_SECRET"] = secret
    return subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "load_sessions.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )


def test_it_refuses_to_run_without_the_signing_secret(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--count", "3", "--out", str(tmp_path / "t.json"), secret=None)
    assert proc.returncode == 2
    assert "ORACLE_SIGNING_SECRET" in proc.stderr


def test_the_tokens_it_writes_actually_verify(tmp_path: Path) -> None:
    """Verified in a SUBPROCESS, on purpose.

    `auth` reads ORACLE_SIGNING_SECRET once at import, so an in-process check
    would pass or fail depending on which test imported `auth` first — it passed
    alone and failed in the full suite. The server that will accept these tokens
    is a different process with the secret in its environment; that is what this
    reproduces.
    """
    out = tmp_path / "tokens.json"
    proc = _run(tmp_path, "--count", "25", "--out", str(out))
    assert proc.returncode == 0, proc.stderr

    rows = json.loads(out.read_text())
    assert len(rows) == 25

    checker = (
        "import json,sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "import auth\n"
        "rows = json.load(open(sys.argv[1]))\n"
        "bad = [(r['address'], auth.verify_session(r['token'])) for r in rows]\n"
        "wrong = [b for b in bad if b[1] != b[0].lower()]\n"
        "print(json.dumps({'wrong': wrong}))\n"
    )
    env = {**os.environ, "ORACLE_SIGNING_SECRET": SECRET}
    verify = subprocess.run(  # noqa: S603
        [sys.executable, "-c", checker, str(out), str(ROOT / "api")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout.strip().splitlines()[-1])["wrong"] == []


def test_every_player_gets_a_distinct_address(tmp_path: Path) -> None:
    out = tmp_path / "tokens.json"
    assert _run(tmp_path, "--count", "50", "--out", str(out)).returncode == 0
    rows = json.loads(out.read_text())
    addresses = [r["address"] for r in rows]
    assert len(set(addresses)) == 50
    # Without this, 1000 virtual users share a handful of tokens and the run
    # measures /api/queue's 40/minute per-address limit instead of the queue.
    assert len({r["token"] for r in rows}) == 50


def test_the_output_is_deterministic_so_two_runs_compare(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _run(tmp_path, "--count", "5", "--out", str(a))
    _run(tmp_path, "--count", "5", "--out", str(b))
    # Same addresses (seeded RNG); tokens differ by design (fresh jti each time).
    assert [r["address"] for r in json.loads(a.read_text())] == [
        r["address"] for r in json.loads(b.read_text())
    ]
