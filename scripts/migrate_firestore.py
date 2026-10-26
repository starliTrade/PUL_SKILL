"""Migrate stored Firestore documents to the current schema version.

Plan item 6.11 / G16. Writing `schemaVersion` on new documents is only half of
versioning: documents written BEFORE the field existed have to be brought
forward, or every read pays for a derivation that should have happened once.

Usage:
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 GCLOUD_PROJECT=demo-pulsar \\
        .venv/bin/python scripts/migrate_firestore.py [--dry-run]

It is safe to run repeatedly: a document already at the current version is left
untouched, and a document from a NEWER server is refused rather than rewritten
(rewriting it would destroy fields this code does not understand).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

import store as store_mod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = parser.parse_args()

    try:
        # `import google.cloud.firestore` rather than
        # `from google.cloud import firestore`: `google.cloud` is a namespace
        # package, so the attribute form is a mypy error (`Module "google.cloud"
        # has no attribute "firestore"`) that says nothing about the code. The
        # import still raises ImportError when the package is absent, which is
        # the only thing this block cares about.
        import google.cloud.firestore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"google-cloud-firestore is not installed: {exc}", file=sys.stderr)
        return 2

    project = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT")
    if not os.environ.get("FIRESTORE_EMULATOR_HOST") and not project:
        print("set FIRESTORE_EMULATOR_HOST or FIRESTORE_PROJECT_ID", file=sys.stderr)
        return 2

    client = store_mod._firestore.Client(project=project)
    collection = client.collection(store_mod.COLLECTION)

    migrated = 0
    current = 0
    refused = 0
    for snap in collection.stream():
        data = snap.to_dict() or {}
        version = int(data.get("schemaVersion", 0) or 0)
        if version == store_mod.SCHEMA_VERSION:
            current += 1
            continue
        try:
            upgraded = store_mod.migrate_document(dict(data))
        except store_mod.SchemaVersionError as exc:
            print(f"REFUSED {snap.id}: {exc}", file=sys.stderr)
            refused += 1
            continue
        if args.dry_run:
            print(f"would migrate {snap.id}: v{version} -> v{store_mod.SCHEMA_VERSION}")
        else:
            snap.reference.set(upgraded)
            print(f"migrated {snap.id}: v{version} -> v{store_mod.SCHEMA_VERSION}")
        migrated += 1

    print(
        f"\n{store_mod.COLLECTION}: {migrated} migrated, {current} already current, "
        f"{refused} refused (newer than this server)"
    )
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
