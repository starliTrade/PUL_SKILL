"""
PULSAR P1 — Authentication (SIWE / EIP-4361) for the authoritative game server.

Trust model:
- A wallet signature over an EIP-4361 message is the ONLY identity proof.
- Nonces are HMAC-signed by this server (keyed with ORACLE_SIGNING_SECRET) and
  carry a random component, so the verifier can prove a nonce was actually
  ISSUED here — a self-forged nonce can never authenticate. Single-use
  enforcement burns each nonce exactly once (correct eviction).
- Session tokens are compact HMAC-signed payloads (address + expiry + jti),
  so the API stays stateless behind any number of workers.

Audit #8 F-02: nonce burns were per-process with an LRU cap — a flood of
self-logins could evict a victim's burned nonce and REPLAY their SIWE
signature. Burns are now PERSISTED to Firestore (atomic create = replay
detector) whenever the durable store is on, with the in-process set kept as
the memory-mode fallback ONLY. The previous-window grace is gone: a nonce is
valid only in the window it was issued in (skew is handled by issuing, not by
accepting stale nonces).

Audit #8 F-06: sessions carry a jti and check a revocation set (also
Firestore-backed in durable mode), so a leaked token can be killed by the
owner/operator instead of surviving its full TTL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import timebase
from eth_account import Account
from eth_account.messages import encode_defunct

SESSION_TTL_SECONDS = 60 * 60 * 2           # audit #8 F-06: 2h (was 24h — a
                                            # stolen token used to live a day)
NONCE_WINDOW_SECONDS = 60 * 5               # 5-minute validity window

# Audit-#3 fix: the SIWE statement must carry the chain the app actually runs
# on. A statement bound to a different chain — or one WITHOUT a chain binding
# — is rejected, so a mainnet-phished or chainless statement can never
# authenticate here.
EXPECTED_CHAIN_ID = int(os.environ.get("ORACLE_CHAIN_ID", "80002"))

# Audit-#3 fix: nonce single-use replay protection. Each nonce burns exactly
# once, on first successful verification.
#
# Audit M17: FastAPI runs sync endpoints in a THREADPOOL, so these sets are
# mutated concurrently. A bare `set.add` happens to be atomic under CPython's
# GIL, but the check-then-act sequences here (membership test + add + order-list
# append + count-map update) are not — two threads could interleave and leave
# the count map disagreeing with the order list, which corrupts eviction.
# Every mutation now runs under this lock.
_AUTH_LOCK = threading.Lock()

_used_nonces: set[str] = set()
# Audit M4: how many times each nonce appears in _used_nonces_order, so eviction
# is O(1) instead of scanning the order list.
_used_nonce_counts: dict[str, int] = {}
_used_nonces_order: list[str] = []
_USED_NONCE_MAX = 4096  # memory-mode fallback cap ONLY (see F-02 comment)

# Audit #8 F-06: session revocation set (jti -> burned). Memory fallback only;
# durable mode persists revocations to Firestore so they survive restarts
# and are visible to every replica.
_revoked_jtis: set[str] = set()
_revoked_jtis_order: list[str] = []
_REVOKED_JTI_MAX = 8192

_API_SECRET = os.environ.get("ORACLE_SIGNING_SECRET", "")
if not _API_SECRET:
    raise RuntimeError(
        "ORACLE_SIGNING_SECRET is required. Set it in the environment before "
        "starting the game server."
    )
_API_SECRET_BYTES = _API_SECRET.encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _from_b64url(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _hmac_hex(payload: str) -> str:
    return hmac.new(_API_SECRET_BYTES, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64url_hex(data: bytes) -> str:
    return _b64url(data).replace("+", "-").replace("/", "_").replace("=", "")


def _from_b64url_any(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text.replace("-", "+").replace("_", "/") + padding)


# --- Nonces: server-issued, server-verifiable, single-use ---------------------

def issue_nonce(address: str, domain: str) -> str:
    """HMAC-signed nonce bound to (domain, address, window) + a random part.

    Format: b64url(domain|address|window|random) + '.' + b64url(HMAC-SHA256).
    The verifier recomputes the MAC — only nonces actually issued by THIS
    server can ever verify, so a client-minted nonce is dead on arrival.
    The random component keeps successive issuances unique so single-use
    enforcement can never self-DoS a legitimate re-authentication.
    """
    window = int(timebase.now() // NONCE_WINDOW_SECONDS)
    body = f"{domain.lower()}|{address.lower()}|{window}|{secrets.token_hex(8)}"
    payload = _b64url_hex(body.encode("utf-8"))
    return f"{payload}.{_hmac_hex(payload)}"


def _window_of(nonce: str) -> int | None:
    """Window number from a well-formed nonce payload (MAC unchecked)."""
    try:
        payload, _mac = nonce.split(".", 1)
        return int(_from_b64url_any(payload).decode("utf-8").split("|")[2])
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def _durable_backend() -> Any | None:
    """The Firestore client from the store, or None in memory mode.

    Late-imported to avoid a circular import (store imports match_engine,
    main imports both).
    """
    try:
        import store as _store  # local import avoids a circular import

        fs = getattr(_store, "_fs_store", None)
        if fs is not None:
            return fs.db
    except Exception:
        pass
    return None


# Audit M3: how long into a new window a nonce issued in the PREVIOUS one is
# still accepted. Without this, a nonce issued in the last seconds of a window
# fails if it is verified in the next one — a random login failure with no cause
# the user can act on. The BURN is what prevents replay; the window is only a
# staleness bound, so this costs nothing.
NONCE_BOUNDARY_GRACE_SECONDS = 30


def _fresh_window(window: int | None) -> bool:
    """Is this nonce's issuance window still acceptable?

    Audit #8 F-02 shrank this from "up to 10 minutes" to the issuance window,
    which is right. Audit M3 adds back a BOUNDED grace for the previous window:
    the boundary was a coin flip, and the replay protection is the burn, not the
    window.
    """
    if window is None:
        return False
    now = int(timebase.now())
    current = now // NONCE_WINDOW_SECONDS
    if window == current:
        return True
    if window == current - 1:
        # Only for the first NONCE_BOUNDARY_GRACE_SECONDS of the new window.
        return (now % NONCE_WINDOW_SECONDS) <= NONCE_BOUNDARY_GRACE_SECONDS
    return False


def nonce_is_fresh(nonce: str) -> bool:
    """Well-formed, MAC-VALID, and within the issuance window.

    Audit #6 C2: freshness now INCLUDES the HMAC check (via nonce_window).
    The previous implementation parsed the payload and checked only the
    window — a client could mint ``b64url(domain|addr|window|rand) + '.' +
    anything`` and it authenticated. MAC verification lives in nonce_window.
    """
    return _fresh_window(nonce_window(nonce))


def nonce_is_used(nonce: str) -> bool:
    return nonce in _used_nonces


def nonce_window(nonce: str) -> int | None:
    """The issuance window of a well-formed nonce (MAC-checked), else None."""
    try:
        payload, mac = nonce.split(".", 1)
        if not hmac.compare_digest(_hmac_hex(payload), mac):
            return None
        body = _from_b64url_any(payload).decode("utf-8")
        return int(body.split("|")[2])
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def _burn_nonce(nonce: str) -> bool:
    """Burn a nonce exactly once. Returns True on FIRST burn, False on replay.

    Audit #8 F-02: durable mode persists the burn as a Firestore CREATE —
    create fails when the doc already exists, which is an atomic replay
    detector shared by every replica (the in-process LRU could be flooded
    out by 4096 self-logins, un-burning a victim's nonce). Memory mode keeps
    the old set but the LRU cap only ever evicts entries that are already
    well past their expiry window, so eviction can no longer revive a
    live nonce.
    """
    if nonce in _used_nonces:
        return False
    db = _durable_backend()
    if db is not None:
        try:
            # TTL the doc at ~2 windows so the collection self-cleans.
            doc = db.collection("auth_nonce_burns").document(
                hashlib.sha256(nonce.encode("utf-8")).hexdigest()
            )
            doc.create(
                {
                    "burnedAt": int(timebase.now()),
                    "expiresAt": int(timebase.now()) + 2 * NONCE_WINDOW_SECONDS,
                }
            )
        except Exception as exc:
            # Audit M2: create() raises when the document EXISTS → replay. Any
            # OTHER exception is an outage, and reporting it as a replay makes
            # an outage look like an attack. Still fail CLOSED — an unverifiable
            # burn cannot authenticate — but record and log the difference.
            if _is_already_exists(exc):
                return False
            _note_burn_error(exc)
            return False
        # Reflect in the local set too (fast-path rejection on this replica).
        _remember_used(nonce)
        return True
    # Memory mode: still correct per-process (window is 5 min; the LRU cap is
    # only reachable at 4096 verifications per 5 minutes per process, and a
    # nonce evicted then is long expired anyway — freshness is re-checked on
    # every verify, so a revived nonce still fails _fresh_window).
    _remember_used(nonce)
    return True


_burn_errors = 0


def nonce_burn_errors() -> int:
    """How many burns failed for a reason OTHER than a replay (audit M2)."""
    return _burn_errors


def _note_burn_error(exc: BaseException) -> None:
    global _burn_errors
    _burn_errors += 1
    _log_burn_error(exc)


def _log_burn_error(exc: BaseException) -> None:
    print(
        f"[auth] nonce burn failed (NOT a replay — an outage): {exc!r}",
        file=sys.stderr,
    )


def _is_already_exists(exc: BaseException) -> bool:
    """True when the exception means the document already existed.

    Matched by name rather than by importing the Firestore exception class, so
    this module keeps working when the durable backend is absent.
    """
    name = type(exc).__name__
    if name in ("AlreadyExists", "Conflict"):
        return True
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    return str(code).lower() in ("already_exists", "6", "409")


def _remember_used(nonce: str) -> None:
    """Remember a burned nonce, evicting the oldest past the cap.

    Audit M4: eviction used `any(n == evicted for n in _used_nonces_order)` — an
    O(n) scan of the whole order list on EVERY eviction, on the authentication
    path. Past the cap that is ~4096 comparisons per verification. A count map
    makes it O(1).
    """
    with _AUTH_LOCK:
        if nonce in _used_nonces:
            return
        _used_nonces.add(nonce)
        _used_nonces_order.append(nonce)
        _used_nonce_counts[nonce] = _used_nonce_counts.get(nonce, 0) + 1
        while len(_used_nonces_order) > _USED_NONCE_MAX:
            evicted = _used_nonces_order.pop(0)
            remaining = _used_nonce_counts.get(evicted, 0) - 1
            if remaining > 0:
                _used_nonce_counts[evicted] = remaining
            else:
                _used_nonce_counts.pop(evicted, None)
                _used_nonces.discard(evicted)


def revoke_session(jti: str) -> None:
    """Audit #8 F-06: burn a session token by its jti (logout / compromise)."""
    if not jti:
        return
    db = _durable_backend()
    if db is not None:
        try:
            db.collection("auth_revocations").document(
                hashlib.sha256(jti.encode("utf-8")).hexdigest()
            ).create({"revokedAt": int(timebase.now())})
        except Exception:
            pass  # already revoked
        return
    # Audit M17: same threadpool hazard as `_remember_used`.
    with _AUTH_LOCK:
        _revoked_jtis.add(jti)
        _revoked_jtis_order.append(jti)
        while len(_revoked_jtis_order) > _REVOKED_JTI_MAX:
            _revoked_jtis.discard(_revoked_jtis_order.pop(0))


def _jti_is_revoked(jti: str) -> bool:
    if not jti:
        return False
    db = _durable_backend()
    if db is not None:
        try:
            return db.collection("auth_revocations").document(
                hashlib.sha256(jti.encode("utf-8")).hexdigest()
            ).get().exists
        except Exception:
            pass  # backend hiccup → fall back to the in-process set
    return jti in _revoked_jtis


@dataclass
class SiweFields:
    address: str
    domain: str
    nonce: str
    issued_at: str
    expiration_time: str
    chain_id: int | None


def parse_siwe(message: str) -> SiweFields | None:
    lines = message.strip().splitlines()
    if len(lines) < 3 or "wants you to sign in" not in lines[0]:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        # The address line (0x… + 40 hex) must never be mistaken for a
        # "Key: value" field — the old parser silently swallowed it, so a
        # message with its Nonce line after the address could smuggle a
        # nonce that differed from the one in the header block.
        if line.startswith("0x") and len(line) >= 40 and all(
            c in "0123456789abcdefABCDEFx" for c in line
        ):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    domain = lines[0].split(" ", 1)[0].strip()
    address = lines[1].strip()
    return SiweFields(
        address=address,
        domain=domain,
        nonce=fields.get("Nonce", ""),
        issued_at=fields.get("Issued At", ""),
        expiration_time=fields.get("Expiration Time", ""),
        chain_id=int(fields["Chain ID"]) if fields.get("Chain ID", "").isdigit() else None,
    )


def verify_siwe(message: str, signature: str, expected_domain: str) -> str | None:
    """
    Returns the lowercase verified address, or None if anything fails:
    malformed message, wrong domain, expired, stale/forged/replayed nonce,
    wrong-or-missing chain binding, or bad signature.
    """
    fields = parse_siwe(message)
    if fields is None:
        return None
    if fields.domain.lower() != expected_domain.lower():
        return None
    # Chain binding is MANDATORY: a statement without "Chain ID:" is not
    # bound to any network, so it cannot be trusted as a chain-scoped login.
    if fields.chain_id != EXPECTED_CHAIN_ID:
        return None
    # Audit #6 C2 — MAC FIRST: the nonce must carry a valid HMAC from THIS
    # server before anything else about it matters. The old code parsed the
    # payload and compared only domain/address; the MAC never was checked, so
    # a self-forged nonce authenticated (the old comment claimed otherwise).
    # nonce_window() returns None unless the MAC verifies; freshness then uses
    # the ISSUED window, which also makes the canonical-message recompute in
    # main.py deterministic and correct.
    window = nonce_window(fields.nonce)
    if window is None or not _fresh_window(window):
        return None  # forged / malformed / stale
    try:
        payload, _mac = fields.nonce.split(".", 1)
        body = _from_b64url_any(payload).decode("utf-8")
        dom, addr, _w, _rand = body.split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if dom != expected_domain.lower() or addr != fields.address.lower():
        return None
    try:
        if fields.expiration_time:
            from datetime import datetime

            expiry = datetime.fromisoformat(fields.expiration_time.replace("Z", "+00:00"))
            if datetime.now(UTC) >= expiry:
                return None
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except Exception:
        return None
    address = getattr(recovered, "address", recovered)
    verified = str(address).lower() or None
    # Audit M1: the recovered signer must BE the address the message claims.
    # Returning the signer for a statement that names someone else is not
    # directly exploitable today (the caller uses the return value), but the
    # contract was ambiguous — and ambiguity in an authentication function is
    # how the next change becomes a vulnerability.
    if verified and verified != fields.address.lower():
        return None
    if verified:
        # Audit #8 F-02: the burn IS the replay check now — _burn_nonce
        # returns False when the nonce was already consumed (durable create
        # fails on an existing doc; the memory set rejects instantly). A
        # replayed signature can never mint a second session.
        if not _burn_nonce(fields.nonce):
            return None
    return verified


def issue_session(address: str) -> str:
    # Audit #8 F-06: every session carries a unique jti so it can be revoked.
    exp = int(timebase.now()) + SESSION_TTL_SECONDS
    payload = json.dumps(
        {"a": address.lower(), "e": exp, "j": secrets.token_hex(16)},
        separators=(",", ":"),
    )
    body = _b64url(payload.encode("utf-8"))
    return f"{body}.{_hmac_hex(body)}"


def session_jti(token: str) -> str | None:
    """The jti of a VALID session token, or None (audit H22).

    `verify_session` returns only the address, so the caller had no way to name
    the session it wanted to revoke — which is why `revoke_session` was dead
    code. This verifies the same HMAC and expiry before handing the jti out.
    """
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_hmac_hex(body), sig):
        return None
    try:
        payload = json.loads(_from_b64url(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("e", 0)) < timebase.now():
        return None
    return str(payload.get("j", "")) or None


def verify_session(token: str) -> str | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_hmac_hex(body), sig):
        return None
    try:
        payload = json.loads(_from_b64url(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Audit M5: the payload's TYPES were trusted. `int(payload["e"])` on a
    # string, null or list raises OUTSIDE this try, so a malformed token became
    # a 500 — a crash on the authentication path is also a denial of service.
    expiry = payload.get("e")
    if not isinstance(expiry, int) or isinstance(expiry, bool):
        return None
    if expiry < timebase.now():
        return None
    address = payload.get("a")
    if not isinstance(address, str) or not address:
        return None
    # Audit #8 F-06: revoked (logged-out / compromised) sessions are dead.
    if _jti_is_revoked(str(payload.get("j", ""))):
        return None
    return address.lower()
