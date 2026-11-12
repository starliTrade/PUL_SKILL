"""Audit C-02a (2026-10-22) — statistical detection of non-human play.

The server's hard floor stops 60 ms "reactions" and the server-observed time
stops a client from *claiming* a fast time it did not achieve. Neither stops a
real script that answers in 110 ms: it is honestly fast. What gives it away is
the SHAPE of the series — humans cluster far above the floor, vary by 15–25 %
between rounds, and do not repeat a value to 0.1 ms.

This module DETECTS and surfaces; it never voids a match or moves money. The
tests below pin both halves: the score, and the promise that a low sample count
cannot produce a flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import integrity  # noqa: E402

HUMAN = [212.0, 245.0, 267.0, 231.0, 198.0, 276.0, 240.0, 222.0]
SCRIPT = [112.0, 108.0, 115.0, 110.0, 109.0, 113.0, 111.0, 110.0]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(integrity, "_memory", {})
    monkeypatch.setattr(integrity, "_reviews", [])
    monkeypatch.setattr(integrity, "_client", lambda: None)


def test_a_human_series_scores_zero():
    out = integrity.score(HUMAN)
    assert out["suspicion"] == 0.0
    assert out["reasons"] == []


def test_a_metronomic_floor_hugging_series_is_flagged():
    out = integrity.score(SCRIPT)
    assert out["suspicion"] >= integrity.FLAG_AT
    assert out["enoughEvidence"] is True
    text = " ".join(out["reasons"])
    assert "floor" in text


def test_a_fast_but_variable_human_is_not_flagged():
    # 150-220ms: quick, but the spread is human. This player must never be
    # penalised for being good at the game.
    out = integrity.score([150.0, 219.0, 168.0, 205.0, 177.0, 232.0, 161.0, 194.0])
    assert out["suspicion"] < integrity.FLAG_AT


def test_too_few_samples_is_never_a_judgement():
    out = integrity.score([110.0, 111.0, 109.0])
    assert out["suspicion"] == 0.0
    assert out["enoughEvidence"] is False
    assert out["reasons"] == []


def test_observe_accumulates_a_rolling_window_and_flags():
    for t in SCRIPT:
        out = integrity.observe("0x" + "11" * 20, [t], "a" * 32)
    assert out["flagged"] is True
    assert len(integrity._memory["0x" + "11" * 20]) == len(SCRIPT)
    assert len(integrity.open_reviews()) == 1


def test_the_window_does_not_grow_without_bound():
    for i in range(integrity.MAX_SAMPLES + 15):
        integrity.observe("0x" + "11" * 20, [200.0 + (i % 40)], "")
    assert len(integrity._memory["0x" + "11" * 20]) == integrity.MAX_SAMPLES


def test_a_review_can_be_dismissed():
    integrity.observe("0x" + "11" * 20, SCRIPT, "a" * 32)
    assert integrity.resolve("0x" + "11" * 20, "dismissed", "known fast player")
    assert integrity.open_reviews() == []


def test_a_bad_status_is_rejected():
    with pytest.raises(ValueError):
        integrity.resolve("x", "banished")


# --- wiring: /api/health, and the admin queue behind its secret -------------
def test_health_reports_the_scorer_state():
    import main as server
    from fastapi.testclient import TestClient

    body = TestClient(server.app).get("/api/health").json()
    assert "integrity" in body
    assert body["integrity"]["minSamples"] == integrity.MIN_SAMPLES


def test_the_review_queue_needs_the_admin_secret(monkeypatch):
    import main as server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "_ADMIN_SECRET", "s3cret", raising=False)
    client = TestClient(server.app)
    assert client.get("/api/admin/review").status_code == 403

    integrity.observe("0x" + "11" * 20, SCRIPT, "a" * 32)
    r = client.get("/api/admin/review", headers={"X-Admin-Secret": "s3cret"})
    assert r.status_code == 200
    assert r.json()["open"] == 1

    entry = r.json()["entries"][0]
    # The evidence an operator needs to decide, not just a number.
    assert entry["reasons"] and entry["times"]
    done = client.post(
        f"/api/admin/review/{entry['address']}",
        json={"status": "dismissed", "note": "checked the replay"},
        headers={"X-Admin-Secret": "s3cret"},
    )
    assert done.status_code == 200
    assert client.get("/api/admin/review", headers={"X-Admin-Secret": "s3cret"}).json()["open"] == 0


def test_an_unknown_review_is_a_404(monkeypatch):
    import main as server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "_ADMIN_SECRET", "s3cret", raising=False)
    r = TestClient(server.app).post(
        "/api/admin/review/nope",
        json={"status": "resolved"},
        headers={"X-Admin-Secret": "s3cret"},
    )
    assert r.status_code == 404
