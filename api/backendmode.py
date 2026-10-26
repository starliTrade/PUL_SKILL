"""Which durable backends this process is ALLOWED to talk to (audit H-18).

Three modules build their own Firestore client from the environment:

    api/abuse.py, api/eligibility.py, api/limits.py

Each one treats "`FIRESTORE_EMULATOR_HOST` is set OR a project id is known" as
"Firestore is configured", and constructs a client. That is the same mistake as
H-17 (`configured` read as `working`), one layer up, and it has a concrete cost:

    PULSAR_MATCH_STORE=memory bash scripts/start_e2e_stack.sh

put the match store in memory as intended, but left the emulator host in the
environment. The eligibility and abuse gates then built a client pointed at an
emulator that did not exist — inside this sandbox there is no JRE, so it never
could — and every request through them blocked for the client's full 60-second
retry policy before failing. `pytest tests/integration/test_eligibility_gate.py`
died with a bare `TimeoutError` from a socket read: a missing dependency wearing
the costume of a broken test.

`PULSAR_MATCH_STORE=memory` is an explicit operator statement that this process
must not depend on Firestore. It cannot be honoured by one module and ignored by
three others.

`api/economy.py` is not affected: it resolves the client through
`store.durable_db()`, which is already None in memory mode. That is the pattern
these three should follow; until they do, they share this predicate.
"""

from __future__ import annotations

import os


def explicit_memory_store() -> bool:
    """True when the operator chose the memory backend on purpose."""
    return os.environ.get("PULSAR_MATCH_STORE", "").strip().lower() == "memory"


def firestore_may_be_used() -> bool:
    """Whether this process is allowed to build a Firestore client.

    Deliberately a NEGATIVE and conservative test: in memory mode it is False no
    matter what endpoint variables linger in the environment.
    """
    if explicit_memory_store():
        return False
    return bool(
        os.environ.get("FIRESTORE_EMULATOR_HOST")
        or os.environ.get("FIRESTORE_PROJECT_ID")
        or os.environ.get("GCLOUD_PROJECT")
    )
