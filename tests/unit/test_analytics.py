"""Product analytics (plan item 11.3 / G17).

The design decision these tests defend is that the numbers are COMPUTED from the
server's own match records, not COLLECTED from the browser. That buys no third
party, no cookies, no client script and no PII — and the last one is a property,
so it is asserted rather than promised.
"""
from __future__ import annotations

import json
import re

import analytics

from api.store import Match


class _Round:
    def __init__(self, ms):
        self.result_ms = ms


class _Store:
    def __init__(self, matches):
        self._matches = matches

    def recent_matches(self, limit=2000):  # noqa: ANN001, ANN201
        return self._matches[:limit]


def _duel(stake=1.0, status="settled", winner="0xaa", times=(210.0, 260.0)):
    m = Match(match_id="a" * 32, stake=stake, created_at=1.0)
    m.players = {"0xaa": {"address": "0xaa"}, "0xbb": {"address": "0xbb"}}
    m.creator, m.joiner = "0xaa", "0xbb"
    m.status = status
    m.winner = winner
    m.rounds = {"0xaa": {0: _Round(times[0])}, "0xbb": {0: _Round(times[1])}}
    return m


def test_the_funnel_reports_rates_and_names_the_worst_step() -> None:
    counts = {
        "/api/auth/nonce": 100,
        "/api/auth/verify": 40,
        "/api/queue": 20,
        "/api/match/{match_id}/settle": 10,
    }
    f = analytics._funnel(counts)
    assert f["arrived"] == 100 and f["connected"] == 40
    assert f["connectRate"] == 0.4
    assert f["playRate"] == 0.5
    assert f["stakeRate"] == 0.5
    # 40/100 is the worst, so "connect" is where people are lost.
    assert f["worstStep"] == "connect"
    # And it says out loud that these are requests, not people.
    assert "not unique people" in f["note"]


def test_a_funnel_with_no_traffic_does_not_divide_by_zero() -> None:
    f = analytics._funnel({})
    assert f["arrived"] == 0
    assert f["connectRate"] is None and f["playRate"] is None and f["stakeRate"] is None


def test_win_loss_counts_duels_and_winners() -> None:
    out = analytics._from_matches([_duel(winner="0xaa"), _duel(winner="0xaa"), _duel(winner="0xbb")])
    wl = out["winLoss"]
    assert wl["settled"] == 3
    assert wl["distinctWinners"] == 2
    assert wl["mostWinsByOnePlayer"] == 2
    assert wl["duelsPerWinner"] == 1.5


def test_reactions_report_percentiles() -> None:
    matches = [_duel(times=(100.0 + i, 300.0 + i)) for i in range(10)]
    r = analytics._from_matches(matches)["reactions"]
    assert r["samples"] == 20
    assert r["minMs"] == 100.0
    assert 100.0 <= r["p50Ms"] <= 310.0
    assert r["p95Ms"] >= r["p50Ms"]


def test_abandonment_counts_started_but_unfinished_duels() -> None:
    out = analytics._from_matches([_duel(status="settled"), _duel(status="active"), _duel(status="void")])
    a = out["abandonment"]
    assert a["started"] == 3
    assert a["finished"] == 2  # settled + void are terminal; active is not
    assert a["rate"] == round(1 - 2 / 3, 4)


def test_per_stake_groups_by_tier() -> None:
    out = analytics._from_matches([_duel(stake=1.0), _duel(stake=1.0), _duel(stake=5.0)])
    assert out["perStake"]["1"]["settled"] == 2
    assert out["perStake"]["5"]["settled"] == 1


def test_the_snapshot_stores_NO_PII() -> None:
    """The property the whole design exists for.

    No address, no name, nothing that identifies a person — anywhere in the
    payload. Asserted by scanning the serialised output for anything
    address-shaped, because a promise is not a property.
    """
    matches = [_duel(winner="0xaa"), _duel(winner="0xbb"), _duel(status="active")]
    payload = analytics.snapshot(_Store(matches), {"/api/auth/nonce": 10})
    blob = json.dumps(payload)

    assert not re.search(r"0x[0-9a-fA-F]{6,}", blob), f"an address leaked into analytics: {blob[:300]}"
    for forbidden in ("0xaa", "0xbb", "address", "player", "winner\""):
        assert forbidden not in blob, f"{forbidden!r} must not appear in the analytics payload"

    # And it says so itself, so an operator reading the output knows.
    assert payload["privacy"]["storesPii"] is False
    assert payload["privacy"]["thirdParty"] is False
    assert payload["privacy"]["cookies"] is False


def test_a_store_failure_is_reported_not_faked_as_zero() -> None:
    """Zero duels and "we could not read the store" are different answers."""

    class _Broken:
        def recent_matches(self, limit=2000):  # noqa: ANN001, ANN201
            raise RuntimeError("firestore down")

    out = analytics.snapshot(_Broken(), {})
    assert out["available"] is False
    assert out["reason"] == "RuntimeError"
    assert "winLoss" not in out
