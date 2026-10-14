"""Backup and restore of the match collection (plan item 11.2).

A backup you have never restored is a hope, not a backup. This drives the real
scripts against the real emulator: seed documents, export, WIPE, restore, and
assert the data came back — including a legacy document, which must be migrated
on the way IN so a pre-schema-change backup cannot reintroduce documents the
current code refuses to read.

Skips without an emulator, like the other Firestore integration tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EMULATOR = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
PROJECT = os.environ.get("GCLOUD_PROJECT") or os.environ.get("FIRESTORE_PROJECT_ID") or "demo-pulsar"

pytestmark = pytest.mark.skipif(
    not EMULATOR, reason="FIRESTORE_EMULATOR_HOST not set — start the emulator"
)


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "FIRESTORE_EMULATOR_HOST": EMULATOR,
        "GCLOUD_PROJECT": PROJECT,
        "ORACLE_SIGNING_SECRET": os.environ.get("ORACLE_SIGNING_SECRET", "test-secret-not-for-prod"),
        "ESCROW_ADDRESS": os.environ.get("ESCROW_ADDRESS", "0x" + "ab" * 20),
        "ORACLE_CHAIN_ID": os.environ.get("ORACLE_CHAIN_ID", "31337"),
    }
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout
    )


def _client():  # type: ignore[no-untyped-def]
    sys.path.insert(0, os.path.join(ROOT, "api"))
    import store as st  # noqa: PLC0415

    return st, st._firestore.Client(project=PROJECT)


def test_a_backup_round_trip_restores_every_document(tmp_path) -> None:
    st, client = _client()
    col = client.collection(st.COLLECTION)

    seeded = {
        "bk-current": {"match_id": "1" * 32, "stake": 1.0, "created_at": 1.0,
                       "players": {"0xaa": {"address": "0xaa", "joinedAt": 1.0}},
                       "status": "waiting", "rounds": {}, "schemaVersion": st.SCHEMA_VERSION},
        # A document as the OLD code wrote it: no version, no creator.
        "bk-legacy": {"match_id": "2" * 32, "stake": 5.0, "created_at": 2.0,
                      "players": {"0xbb": {"address": "0xbb", "joinedAt": 1.0}},
                      "status": "waiting", "rounds": {}},
    }
    for doc_id, data in seeded.items():
        col.document(doc_id).set(data)

    backup = tmp_path / "backup.json"

    out = _run(["scripts/backup_firestore.py", "export", str(backup)])
    assert out.returncode == 0, out.stderr
    assert backup.exists()

    # WIPE — the point of a restore is that the data is gone.
    for snap in col.stream():
        snap.reference.delete()
    assert list(col.stream()) == []

    out = _run(["scripts/backup_firestore.py", "restore", str(backup)])
    assert out.returncode == 0, out.stderr

    restored = {snap.id: snap.to_dict() for snap in col.stream()}
    assert set(restored) >= set(seeded), f"missing after restore: {set(seeded) - set(restored)}"

    # The legacy document must come back MIGRATED, so the current code can read
    # it — a restore that reintroduces unreadable documents is not a restore.
    legacy = restored["bk-legacy"]
    assert legacy["schemaVersion"] == st.SCHEMA_VERSION
    assert legacy["creator"] == "0xbb"
    st._match_from_doc(legacy)  # must not raise

    # And the backup file itself records which schema it was taken under.
    payload = json.loads(backup.read_text())
    assert payload["schemaVersion"] == st.SCHEMA_VERSION
    assert payload["collection"] == st.COLLECTION

    for doc_id in seeded:
        col.document(doc_id).delete()


def test_restore_refuses_to_clobber_without_force(tmp_path) -> None:
    """The one thing worse than no backup is a restore that quietly replaced live data."""
    st, client = _client()
    col = client.collection(st.COLLECTION)

    col.document("clobber-probe").set({"match_id": "9" * 32, "stake": 1.0, "created_at": 1.0})
    backup = tmp_path / "b.json"
    out = _run(["scripts/backup_firestore.py", "export", str(backup)])
    assert out.returncode == 0, out.stderr

    # The document now differs from the backup.
    col.document("clobber-probe").set({"match_id": "9" * 32, "stake": 99.0, "created_at": 1.0})

    out = _run(["scripts/backup_firestore.py", "restore", str(backup)])
    assert out.returncode == 0, out.stderr
    # Assert the BEHAVIOUR, not a count: the collection may hold documents from
    # other tests, and a count would make this test depend on their leftovers.
    assert "skipped" in out.stdout, out.stdout
    assert col.document("clobber-probe").get().to_dict()["stake"] == 99.0, (
        "an existing document must not be overwritten without --force"
    )

    col.document("clobber-probe").delete()
