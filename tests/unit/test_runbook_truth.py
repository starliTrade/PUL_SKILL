"""6.6 — the incident runbook must not name endpoints that do not exist.

A runbook is only useful if an operator can follow it at 3am. A path that was
renamed in the code and not in the document sends them to a 404 during an
incident, which is worse than no runbook.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "INCIDENT-RUNBOOK.md"


def test_the_runbook_exists() -> None:
    assert RUNBOOK.is_file(), "plan item 6.6 — the incident runbook is missing"


def test_every_endpoint_it_names_exists() -> None:
    import main as server

    documented = set(re.findall(r"/api/[A-Za-z0-9_{}/\-]+", RUNBOOK.read_text(encoding="utf-8")))
    assert documented, "the runbook names no endpoints — is it the right file?"

    routes = {getattr(r, "path", "") for r in server.app.routes}

    def exists(path: str) -> bool:
        # `/api/admin/match/{matchId}` in prose vs `{match_id}` in the route.
        pattern = re.compile("^" + re.sub(r"\{[^}]+\}", r"\\{[^}]+\\}", path) + "$")
        return any(pattern.match(r) for r in routes)

    missing = sorted(p for p in documented if not exists(p))
    assert not missing, f"the runbook names endpoints the server does not serve: {missing}"


def test_the_timing_it_states_matches_the_code() -> None:
    """The refund horizon is the number an operator quotes to players."""
    import match_engine as engine

    text = RUNBOOK.read_text(encoding="utf-8")
    assert "40 minutes" in text
    # 30 min MATCH_TIMEOUT + 10 min REFUND_GRACE.
    assert engine.MATCH_TIMEOUT_SECONDS == 30 * 60
    assert "30 min" in text and "10 min" in text


@pytest.mark.parametrize(
    "needle", ["/api/health", "/api/metrics", "X-Admin-Secret", "PULSAR_ADMIN_SECRET"]
)
def test_it_covers_the_operator_surface(needle: str) -> None:
    assert needle in RUNBOOK.read_text(encoding="utf-8")
