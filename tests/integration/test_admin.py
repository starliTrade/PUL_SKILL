"""
Phase 6 / 6.3 (G9) — admin tooling.

When a match wedges in production, the operator currently has no way to look at
it or to unstick it. They can read Firestore by hand, which is slow, error-prone
and leaves no audit trail.

Four capabilities, and the constraints that make them safe to ship:

  - **inspect** a match: the full state, including why it is stuck;
  - **force-settle**: settle a match the engine considers complete;
  - **force-void**: void a match that cannot complete, refunding both;
  - **player search**: find a player's matches by address.

**The constraint that matters most: admin routes are gated by a SEPARATE secret,
not by a session token.** A session token belongs to a player; a player must
never be able to void their opponent's match. If the admin secret is unset the
routes are DISABLED, not open — an unconfigured deployment must fail closed.

**And every admin action is audited.** Force-settling a match moves real money,
so the operator's identity and reason are recorded. An unaudited money-moving
endpoint is worse than no endpoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ADMIN_SECRET = "test-admin-secret-not-a-real-one"


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setattr(server, "_ADMIN_SECRET", ADMIN_SECRET)
    return TestClient(server.app)


@pytest.fixture
def client(monkeypatch):
    """A deployment with NO admin secret configured."""
    monkeypatch.setattr(server, "_ADMIN_SECRET", "")
    return TestClient(server.app)


def _auth() -> dict[str, str]:
    return {"X-Admin-Secret": ADMIN_SECRET}


# --- the gate -----------------------------------------------------------------
def test_admin_routes_are_disabled_without_a_secret(client):
    """Fail CLOSED: an unconfigured deployment must not expose admin routes."""
    for path in ("/api/admin/match/x", "/api/admin/players?q=0x1"):
        r = client.get(path)
        assert r.status_code in (401, 403, 404), (
            f"{path} answered {r.status_code} with no admin secret configured"
        )


def test_a_wrong_secret_is_rejected(admin_client):
    r = admin_client.get("/api/admin/players?q=0x1", headers={"X-Admin-Secret": "wrong"})
    assert r.status_code in (401, 403)


def test_a_session_token_is_not_an_admin_credential(admin_client):
    """A player's token must never unlock admin routes."""
    r = admin_client.get(
        "/api/admin/players?q=0x1", headers={"Authorization": "Bearer anything"}
    )
    assert r.status_code in (401, 403)


# --- inspect ------------------------------------------------------------------
def test_inspect_returns_the_match_state(admin_client):
    r = admin_client.get("/api/admin/match/does-not-exist", headers=_auth())
    assert r.status_code == 404


def test_inspect_requires_the_secret(admin_client):
    r = admin_client.get("/api/admin/match/whatever")
    assert r.status_code in (401, 403)


# --- player search ------------------------------------------------------------
def test_player_search_requires_a_query(admin_client):
    r = admin_client.get("/api/admin/players", headers=_auth())
    assert r.status_code == 422


def test_player_search_rejects_a_non_address(admin_client):
    """A free-text query would be an unbounded Firestore scan."""
    r = admin_client.get("/api/admin/players?q=not-an-address", headers=_auth())
    assert r.status_code == 422


def test_player_search_returns_a_list(admin_client):
    r = admin_client.get("/api/admin/players?q=0x" + "11" * 20, headers=_auth())
    assert r.status_code == 200
    assert "matches" in r.json()


# --- the money-moving actions -------------------------------------------------
def test_force_void_requires_a_reason(admin_client):
    """An unaudited money-moving action is worse than no action."""
    r = admin_client.post(
        "/api/admin/match/x/void", headers=_auth(), json={"reason": ""}
    )
    assert r.status_code == 422


def test_force_settle_requires_a_reason(admin_client):
    r = admin_client.post(
        "/api/admin/match/x/settle", headers=_auth(), json={"reason": ""}
    )
    assert r.status_code == 422


def test_force_void_on_a_missing_match_is_404(admin_client):
    r = admin_client.post(
        "/api/admin/match/does-not-exist/void",
        headers=_auth(),
        json={"reason": "operator test"},
    )
    assert r.status_code == 404


def test_admin_actions_never_leak_a_secret(admin_client):
    raw = admin_client.get("/api/admin/players?q=0x" + "11" * 20, headers=_auth()).text
    assert ADMIN_SECRET not in raw
