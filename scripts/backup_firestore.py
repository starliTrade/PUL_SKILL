"""Export and restore the match collection (plan item 11.2).

A backup you have never restored is a hope, not a backup. This script does both
halves and the test beside it proves the round trip on real documents.

Usage:
    # export
    ... .venv/bin/python scripts/backup_firestore.py export /tmp/pulsar-backup.json
    # restore (into a collection, refusing to clobber by default)
    ... .venv/bin/python scripts/backup_firestore.py restore /tmp/pulsar-backup.json

Restore is deliberately NOT silent: it reports how many documents it wrote and
refuses to overwrite an existing document unless `--force` is given, because the
one thing worse than no backup is a restore that quietly replaced live data with
a stale copy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

import store as store_mod  # noqa: E402


def _client():  # type: ignore[no-untyped-def]
    project = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT")
    return store_mod._firestore.Client(project=project)


def export(path: str) -> int:
    client = _client()
    docs = {}
    for snap in client.collection(store_mod.COLLECTION).stream():
        docs[snap.id] = snap.to_dict() or {}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"collection": store_mod.COLLECTION, "schemaVersion": store_mod.SCHEMA_VERSION, "documents": docs}, fh, indent=2, sort_keys=True)
    print(f"exported {len(docs)} documents from {store_mod.COLLECTION} to {path}")
    return 0


def restore(path: str, force: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    docs = payload.get("documents") or {}
    client = _client()
    collection = client.collection(store_mod.COLLECTION)

    written = 0
    skipped = 0
    for doc_id, data in docs.items():
        ref = collection.document(doc_id)
        if not force and ref.get().exists:
            skipped += 1
            continue
        # Migrate on the way in: a backup taken before a schema change must not
        # reintroduce documents the current code refuses to read.
        ref.set(store_mod.migrate_document(dict(data)))
        written += 1

    print(
        f"restored {written} documents into {store_mod.COLLECTION}"
        + (f", skipped {skipped} that already existed (use --force to overwrite)" if skipped else "")
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export")
    p_export.add_argument("path")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("path")
    p_restore.add_argument("--force", action="store_true", help="overwrite existing documents")
    args = parser.parse_args()

    if args.command == "export":
        return export(args.path)
    return restore(args.path, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
