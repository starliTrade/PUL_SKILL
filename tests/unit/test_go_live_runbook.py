"""The go-live runbook must be followable, or it is decoration.

`docs/GO-LIVE-RUNBOOK.md` tells a human what to do ON THEIR MACHINE, where no
test in this repository can reach. That makes it the most fragile document in the
project: a renamed script, a moved endpoint or a version bump turns it into a set
of commands that fail at the worst possible moment (the first real day).

So the parts that CAN be checked mechanically are checked here:
  * every script/path it tells you to run exists and is executable;
  * every endpoint it names is served;
  * every test count it quotes is a number this repository can produce;
  * it does not pretend the browser/E2E/Amoy work has been done here.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "GO-LIVE-RUNBOOK.md"

sys.path.insert(0, str(ROOT / "api"))


def _text() -> str:
    assert DOC.is_file(), "docs/GO-LIVE-RUNBOOK.md is missing"
    return DOC.read_text(encoding="utf-8")


def test_every_path_it_names_exists() -> None:
    text = _text()
    # `bash scripts/x.sh`, `scripts/x.py`, `python scripts/x.py`
    referenced = set(re.findall(r"\b(scripts/[A-Za-z0-9_\-]+\.(?:sh|py))", text))
    referenced |= set(re.findall(r"\b(contracts/script/[A-Za-z0-9_\-]+\.sol)", text))
    referenced |= set(re.findall(r"\b(docs/[A-Za-z0-9_\-]+\.md)", text))
    assert referenced, "the runbook names no scripts at all — wrong file?"
    missing = sorted(p for p in referenced if not (ROOT / p).exists())
    assert not missing, f"the runbook names paths that do not exist: {missing}"


def test_the_scripts_it_invokes_with_bash_are_executable() -> None:
    for path in set(re.findall(r"bash (scripts/[A-Za-z0-9_\-]+\.sh)", _text())):
        target = ROOT / path
        assert target.stat().st_mode & 0o111, f"{path} is named with `bash` but not executable"


def test_every_endpoint_it_names_is_served() -> None:
    import main as server

    documented = set(re.findall(r"/api/[A-Za-z0-9_/{}\-]+", _text()))
    documented = {d.rstrip(".,;") for d in documented}
    routes = {getattr(r, "path", "") for r in server.app.routes}

    def exists(path: str) -> bool:
        pattern = re.compile("^" + re.sub(r"\{[^}]+\}", r"\\{[^}]+\\}", path) + "$")
        return any(pattern.match(r) for r in routes)

    missing = sorted(p for p in documented if not exists(p))
    assert not missing, f"the runbook names endpoints the server does not serve: {missing}"


def test_it_says_what_was_NOT_verified_here() -> None:
    """The one thing that must never drift: the honesty about the environment."""
    text = _text()
    assert "انجام نشده" in text
    assert "Amoy" in text
    assert "Playwright" in text
    # It must not claim a browser run happened in this repository.
    assert "npx playwright install" in text


def test_it_carries_the_production_required_variables() -> None:
    """A runbook that omits a required env var produces a server that refuses to
    boot, and the operator reads that as 'the build is broken'."""
    text = _text()
    for var in (
        "PULSAR_ENV",
        "PULSAR_MATCH_STORE",
        "ESCROW_ADDRESS",
        "ORACLE_CHAIN_ID",
        "ORACLE_SIGNING_SECRET",
        "ALLOWED_DOMAIN",
        "ALLOWED_HOSTS",
        "CORS_ALLOW_ORIGINS",
        "PULSAR_ALLOW_LOCAL_SIGNER",
    ):
        assert var in text, f"{var} is required in production but the runbook omits it"


def test_the_counts_it_quotes_are_the_ones_this_repo_produces() -> None:
    """Quoted test counts go stale silently; keep them in the same shape as the
    measured table in README (which scripts/test_counts.py regenerates)."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    vitest_readme = re.search(r"Frontend \(vitest\) \| (\d+) tests", readme)
    pytest_readme = re.search(r"Server \(pytest\) \| (\d+) passed", readme)
    assert vitest_readme and pytest_readme, "README lost its measured table"

    doc = _text()
    assert vitest_readme.group(1) in doc, "runbook quotes a vitest count README disagrees with"
    assert pytest_readme.group(1) in doc, "runbook quotes a pytest count README disagrees with"
