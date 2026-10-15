"""Server-side eligibility attestation (plan item 11.3 / G2).

The client has an eligibility gate, and its own comment admits the problem:
"Consent is one localStorage key, so clearing storage bypasses it." A gate a
player can remove with a devtools command is not a gate — and for a game holding
real money, an age gate that only exists in the browser is a compliance claim the
server cannot back up.

So the attestation is recorded SERVER-SIDE, against the authenticated address, in
the same durable store as everything else. The staked entry point requires it;
free play does not, because free play involves no money and no risk.

This is an ATTESTATION, not verification. Proving a person's age needs KYC
(plan item G1), which is a separate decision with a separate provider. What this
guarantees is narrower and still worth having: **the server refuses to let an
unattested session enter staked play**, so the browser is no longer the only thing
standing between a minor and a real-money duel.
"""
from __future__ import annotations

import os
from typing import Any

import timebase

COLLECTION = "pulsar_eligibility"
_ATTESTATION_VERSION = 1


class EligibilityError(RuntimeError):
    """The session has not attested eligibility for staked play."""


# ONE client for the process lifetime.
#
# Audit 2026-10-15: the first version created a client on EVERY call, and
# constructing a Firestore client costs ~3 seconds — so every gated request paid
# it and unrelated tests started timing out. `store.py` had already learned this
# ("ONE FirestoreStore for the process lifetime"); this module had not.
_CLIENT: Any = None
_CLIENT_RESOLVED = False


def _firestore_client() -> Any:
    """The Firestore client, or None when it is not configured."""
    global _CLIENT, _CLIENT_RESOLVED
    if _CLIENT_RESOLVED:
        return _CLIENT
    _CLIENT_RESOLVED = True
    try:
        from google.cloud import firestore as _firestore  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    project = os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT")
    if not os.environ.get("FIRESTORE_EMULATOR_HOST") and not project:
        return None
    try:
        _CLIENT = _firestore.Client(project=project)
    except Exception:  # noqa: BLE001
        _CLIENT = None
    return _CLIENT


# Process-local fallback, so the gate works in memory mode too. It is a FALLBACK:
# when Firestore is configured the durable record is the source of truth, and a
# restart must not silently un-attest everyone.
_memory: dict[str, float] = {}


def record(address: str, *, confirmed_at: float | None = None) -> float:
    """Record that `address` attested eligibility. Idempotent."""
    addr = address.lower()
    stamp = float(confirmed_at if confirmed_at is not None else timebase.now())
    client = _firestore_client()
    if client is not None:
        client.collection(COLLECTION).document(addr).set(
            {"address": addr, "confirmedAt": stamp, "version": _ATTESTATION_VERSION}
        )
    _memory[addr] = stamp
    return stamp


def attested(address: str) -> bool:
    """True when `address` has attested eligibility for staked play."""
    addr = address.lower()
    client = _firestore_client()
    if client is not None:
        try:
            if client.collection(COLLECTION).document(addr).get().exists:
                return True
        except Exception:  # noqa: BLE001
            # A store outage must not OPEN the gate. Fall through to the local
            # record, which can only ever say yes for someone who attested in
            # this process.
            pass
    return addr in _memory


def require(address: str) -> None:
    """Raise `EligibilityError` unless `address` may play for money."""
    if not attested(address):
        raise EligibilityError(
            "Eligibility has not been confirmed for this account. Confirm you are "
            "of legal age for real-money play, or use Free Training."
        )
