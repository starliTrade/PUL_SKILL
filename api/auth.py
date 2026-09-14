"""
PULSAR P1 — Authentication (SIWE / EIP-4361) for the authoritative game server.

Trust model:
- A wallet signature over an EIP-4361 message is the ONLY identity proof.
- Nonces are HMAC-signed by this server (keyed with ORACLE_SIGNING_SECRET) and
  carry a random component, so the verifier can prove a nonce was actually
  ISSUED here — a self-forged nonce can never authenticate. Single-use
  enforcement burns each nonce exactly once (correct eviction).
- Session tokens are compact HMAC-signed payloads (address + expiry), so the
  API stays stateless behind any number of workers. Replay protection across
  replicas is the nonce-burn set; hardening to Firestore-backed burns is the
  multi-replica upgrade path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct

SESSION_TTL_SECONDS = 60 * 60 * 24          # 24h
NONCE_WINDOW_SECONDS = 60 * 5               # 5-minute validity window

# Audit-#3 fix: the SIWE statement must carry the chain the app actually runs
# on. A statement bound to a different chain — or one WITHOUT a chain binding
# — is rejected, so a mainnet-phished or chainless statement can never
# authenticate here.
EXPECTED_CHAIN_ID = int(os.environ.get("ORACLE_CHAIN_ID", "80002"))

# Audit-#3 fix: nonce single-use replay protection. Each nonce burns exactly
# once, on first successful verification.
_used_nonces: set[str] = set()
_used_nonces_order: list[str] = []
_USED_NONCE_MAX = 4096

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
    window = int(time.time() // NONCE_WINDOW_SECONDS)
    body = f"{domain.lower()}|{address.lower()}|{window}|{secrets.token_hex(8)}"
    payload = _b64url_hex(body.encode("utf-8"))
    return f"{payload}.{_hmac_hex(payload)}"


def nonce_is_fresh(nonce: str) -> bool:
    try:
        payload, mac = nonce.split(".", 1)
        body = _from_b64url_any(payload).decode("utf-8")
        parts = body.split("|")
        if len(parts) != 4:
            return False
        window = int(parts[2])
    except (ValueError, AttributeError, UnicodeDecodeError):
        return False
    current = int(time.time() // NONCE_WINDOW_SECONDS)
    return window in (current, current - 1)  # tolerate one window of skew


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


def _burn_nonce(nonce: str) -> None:
    if nonce in _used_nonces:
        return
    _used_nonces.add(nonce)
    _used_nonces_order.append(nonce)
    while len(_used_nonces_order) > _USED_NONCE_MAX:
        evicted = _used_nonces_order.pop(0)
        if not any(n == evicted for n in _used_nonces_order):
            _used_nonces.discard(evicted)


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
    if not fields.nonce or not nonce_is_fresh(fields.nonce):
        return None
    if nonce_is_used(fields.nonce):
        return None  # replayed signature — each nonce authenticates exactly once
    # The nonce must have been issued by THIS server for THIS domain+address
    # window. A self-forged or reused-from-elsewhere nonce fails the MAC.
    try:
        payload, mac = fields.nonce.split(".", 1)
        body = _from_b64url_any(payload).decode("utf-8")
        dom, addr, _window, _rand = body.split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if dom != expected_domain.lower() or addr != fields.address.lower():
        return None
    try:
        if fields.expiration_time:
            from datetime import datetime, timezone

            expiry = datetime.fromisoformat(fields.expiration_time.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= expiry:
                return None
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except Exception:
        return None
    address = getattr(recovered, "address", recovered)
    verified = str(address).lower() or None
    if verified:
        _burn_nonce(fields.nonce)
    return verified


def issue_session(address: str) -> str:
    exp = int(time.time()) + SESSION_TTL_SECONDS
    payload = json.dumps({"a": address.lower(), "e": exp}, separators=(",", ":"))
    body = _b64url(payload.encode("utf-8"))
    return f"{body}.{_hmac_hex(body)}"


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
    if int(payload.get("e", 0)) < time.time():
        return None
    return str(payload.get("a")) or None
