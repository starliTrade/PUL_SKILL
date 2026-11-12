"""H-24 — a shared per-IP budget must not be walked into by the harness.

H-22 taught the live suites to honour `Retry-After`. That was necessary and not
sufficient. Measured on 2026-10-23:

    eligibility suite: 6 handshakes per run   (5 tests, one signs in twice)
    ranked flow:       2 handshakes per run
    server:            RL_AUTH_MAX = 10 nonce handshakes per minute per IP

Two runs inside a minute therefore collided, and a full `pytest` run — which runs
both files — walked into the ceiling on its own. Observed failure: `1 failed, 626
passed`, with `assert None is not None` in the eligibility suite.

Retrying a global budget is the wrong tool: it converted a shared counter into a
waiting room (a run took 60 s while a test slept out the window). The suites do
not need six identities; they need two states and two fixed keys. Minting each
once per process drops a full run to four handshakes, which leaves room for a
second run in the same minute.

Nothing is weakened: the token is still a real SIWE session, the server still
verifies it on every request, and the limiter still refuses when the budget is
genuinely exceeded.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.fixtures.live_api import mint_once, reset_sessions  # noqa: E402


def test_the_mint_runs_once_per_key() -> None:
    reset_sessions()
    calls: list[str] = []

    def _mint() -> str:
        calls.append("mint")
        return "token"

    assert mint_once("a", _mint) == "token"
    assert mint_once("a", _mint) == "token"
    assert len(calls) == 1, "a second call re-minted a session and spent budget"


def test_distinct_keys_get_distinct_sessions() -> None:
    reset_sessions()
    assert mint_once("attested", lambda: "t1") == "t1"
    assert mint_once("unattested", lambda: "t2") == "t2"


def test_reset_forgets_everything() -> None:
    reset_sessions()
    mint_once("a", lambda: "one")
    reset_sessions()
    assert mint_once("a", lambda: "two") == "two"


def test_the_live_suites_cache_instead_of_signing_in_per_test() -> None:
    eligibility = (ROOT / "tests/integration/test_eligibility_gate.py").read_text(encoding="utf-8")
    ranked = (ROOT / "tests/integration/test_ranked_flow_e2e.py").read_text(encoding="utf-8")
    for text, name in ((eligibility, "eligibility"), (ranked, "ranked")):
        assert "mint_once(" in text, f"{name} still mints a session per test"


def test_the_handshake_budget_of_a_full_run_fits_the_server_limit() -> None:
    """Four handshakes against a cap of ten: two runs per minute still fit.

    This is the arithmetic that makes the fix a fix rather than a longer wait.
    """
    import re

    main_src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    cap = int(re.search(r"RL_AUTH_MAX = (\d+)", main_src).group(1))
    needed = 2 + 2  # eligibility: attested + unattested; ranked: two fixed keys
    assert needed <= cap // 2, f"{needed} handshakes per run vs a cap of {cap} per minute"
