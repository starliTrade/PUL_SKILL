"""Audit M-10 (2026-10-22) — every admin decision leaves a record.

The admin surface is gated by one shared secret. Before this, force-void and
force-settle printed a line to stderr (lost on restart, not queryable) and
ban/unban/review wrote NOTHING at all. A leaked secret could change the outcome
of a duel and no one could reconstruct who did it or why.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("ESCROW_ADDRESS", "0x" + "ab" * 20)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import auditlog  # noqa: E402
import main as server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HDR = {"X-Admin-Secret": "s3cret"}


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    monkeypatch.setattr(server, "_ADMIN_SECRET", "s3cret", raising=False)
    monkeypatch.setattr(auditlog, "_memory", [])
    monkeypatch.setattr(auditlog, "_client", lambda: None)
    yield


def test_a_ban_is_recorded_with_target_and_reason(monkeypatch):
    import abuse

    monkeypatch.setattr(abuse, "ban", lambda *a, **k: {"ok": True, "address": a[0]})
    r = TestClient(server.app).post(
        "/api/admin/ban",
        json={"address": "0x" + "11" * 20, "seconds": 600, "reason": "abuse"},
        headers=HDR,
    )
    assert r.status_code == 200, r.text

    entry = auditlog._memory[-1]
    assert entry["action"] == "player.ban"
    assert entry["target"] == "0x" + "11" * 20
    assert "abuse" in entry["detail"]
    assert entry["id"], "an audit entry without an id cannot be referenced"


def test_the_trail_is_readable_through_the_api():
    auditlog.record("match.force_void", target="a" * 32, detail="operator mistake")
    body = TestClient(server.app).get("/api/admin/audit", headers=HDR).json()

    assert body["count"] >= 1
    assert body["entries"][-1]["action"] == "match.force_void"


def test_the_trail_needs_the_admin_secret():
    assert TestClient(server.app).get("/api/admin/audit").status_code == 403


def test_the_trail_is_newest_first(monkeypatch):
    auditlog.record("first")
    auditlog.record("second")
    rows = auditlog.recent(10)
    assert [r["action"] for r in rows] == ["second", "first"]


def test_a_failed_durable_write_is_counted_not_lost(monkeypatch):
    class _Broken:
        def collection(self, _name):
            raise OSError("firestore down")

    monkeypatch.setattr(auditlog, "_client", lambda: _Broken())
    auditlog.record("match.force_settle", target="b" * 32)

    health = auditlog.health()
    assert health["failures"] == 1
    assert "firestore down" in health["lastError"]
    # The in-memory copy survives, so the decision is still auditable.
    assert auditlog._memory[-1]["target"] == "b" * 32
