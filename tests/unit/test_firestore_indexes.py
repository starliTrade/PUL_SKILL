"""6.5 — the declared indexes must cover the queries the server actually runs.

The composite index on `(status, settled_at)` is load-bearing: without it
Firestore rejects the re-sign sweep's query, and the sweep is the F-12 prize
rescue. The rejection used to be swallowed, so the failure mode was "prizes
quietly stop being rescued" (audit H9).
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEXES = ROOT / "firestore.indexes.json"
DEPLOYMENT = ROOT / "docs" / "DEPLOYMENT.md"


def _declared() -> list[dict]:
    return json.loads(INDEXES.read_text(encoding="utf-8")).get("indexes", [])


def test_the_index_file_exists_and_parses() -> None:
    assert INDEXES.is_file(), "plan item 6.5 — firestore.indexes.json is missing"
    assert isinstance(_declared(), list)


def test_the_sweep_composite_index_is_declared() -> None:
    wanted = {("status", "ASCENDING"), ("settled_at", "ASCENDING")}
    found = [
        {(f["fieldPath"], f.get("order", "ASCENDING")) for f in idx.get("fields", [])}
        for idx in _declared()
    ]
    assert wanted in found, (
        "the (status, settled_at) composite index is not declared — the re-sign "
        "sweep's query is rejected without it (audit H9)"
    )


def test_nothing_is_excluded_from_automatic_indexing() -> None:
    """`player_live_match` queries a map subfield, which relies on automatic
    single-field indexing."""
    body = json.loads(INDEXES.read_text(encoding="utf-8"))
    assert body.get("fieldOverrides", []) == [], (
        "a field override excludes a field from automatic indexing; the "
        "players.<addr>.address query depends on it being indexed"
    )


def test_the_deployment_doc_explains_the_indexes() -> None:
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert "firestore.indexes.json" in text
    assert re.search(r"composite", text, re.I), "the doc does not mention the composite index"


def test_the_doc_lists_every_query_the_server_runs() -> None:
    """The documented table must cover the queries in api/store.py."""
    import store as store_module

    src = pathlib.Path(store_module.__file__).read_text(encoding="utf-8")
    queried = set(re.findall(r'\.where\(\s*[\'"]([A-Za-z_.]+)[\'"]', src))
    doc = DEPLOYMENT.read_text(encoding="utf-8")
    missing = sorted(f for f in queried if f.split(".")[0] not in doc)
    assert not missing, f"queries the deployment doc does not mention: {missing}"
