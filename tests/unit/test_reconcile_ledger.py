"""Audit H-14 — the ledger must be checkable against what it recorded.

`/api/health` says "a write failed". It cannot say "player X is credited 4 wins
and the recorded settlements contain 6". This is the second number, computed by
a pure function, with no write path at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_ledger as R  # noqa: E402

A = "0x" + "11" * 20
B = "0x" + "22" * 20


def _doc(winner="", players=None):
    return {"players": players or [A, B], "winner": winner, "settlementId": "x"}


def test_counters_follow_the_same_definition_the_engine_uses():
    docs = [_doc(A), _doc(A), _doc(B), _doc("")]  # A, A, B, void
    got = R.expected_counters(docs)

    assert got[A] == {"totalMatches": 4, "wins": 2, "losses": 1, "voids": 1}
    assert got[B] == {"totalMatches": 4, "wins": 1, "losses": 2, "voids": 1}


def test_a_missing_user_document_is_zero_not_an_exception():
    drift = R.compare(R.expected_counters([_doc(A)]), {})
    assert drift and drift[0]["address"] == A
    assert drift[0]["drift"]["wins"] == {"ledger": 0, "matches": 1}


def test_a_correct_ledger_reports_no_drift():
    expected = R.expected_counters([_doc(A), _doc(B)])
    actual = {
        A: {"totalMatches": 2, "wins": 1, "losses": 1, "voids": 0},
        B: {"totalMatches": 2, "wins": 1, "losses": 1, "voids": 0},
    }
    assert R.compare(expected, actual) == []


def test_drift_names_the_field_and_both_numbers():
    expected = R.expected_counters([_doc(A), _doc(A)])
    actual = {A: {"totalMatches": 2, "wins": 1, "losses": 0, "voids": 0}}
    drift = R.compare(expected, actual)

    rows = {row["address"]: row["drift"] for row in drift}
    assert rows[A] == {"wins": {"ledger": 1, "matches": 2}}
    # B is reported too — it never had a ledger document at all.
    assert rows[B]["totalMatches"] == {"ledger": 0, "matches": 2}


def test_the_tool_has_no_write_path():
    """A 'repair' mode on money-adjacent counters is a second bug (see module)."""
    source = Path(R.__file__).read_text(encoding="utf-8")
    for forbidden in (".set(", ".update(", ".delete(", ".add(", "batch("):
        assert forbidden not in source, f"reconciliation must stay read-only, found {forbidden}"
