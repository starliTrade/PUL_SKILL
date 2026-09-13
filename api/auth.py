"""
PULSAR P1 — Authentication (SIWE / EIP-4361) for the authoritative game server.

Trust model:
- A wallet signature over an EIP-4361 message is the ONLY identity proof.
- Nonces are stateless HMACs bound to the address and a 5-minute time window,
  which prevents cross-origin and stale-message replay. Upgrade path: a
  single-use nonce table in Redis/Firestore.
- Session tokens are compact HMAC-signed payloads (address + expiry), so the
  API stays stateless behind any number of workers.
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
# on (the client builds it with CHAIN.chainId — Amoy 80002 by default). A
# message signed for a different chain is rejected instead of silently
# accepted, so a mainnet-phished statement can never authenticate here.
EXPECTED_CHAIN_ID = int(os.environ.get("ORACLE_CHAIN_ID", "80002"))

# Audit-#3 fix: nonce single-use replay protection. The rolling-window nonce
# alone allowed one signature to authenticate repeatedly for up to 10 minutes
# (two adjacent windows). Each nonce now burns exactly once.
_used_nonces: set[str] = set()
_used_nonces_order: list[str] = []
_USED_NONCE_MAX = 4096


def _burn_nonce(nonce: str) -> None:
    if nonce in _used_nonces:
        return
    _used_nonces.add(nonce)
    _used_nonces_order.append(nonce)
    while len(_used_nonces_order) > _USED_NONCE_MAX:
        _used_nonces_order.pop(0)
        _used_nonces.discard(_used_nonces_order[0] if _used_nonces_order else "")


def nonce_is_used(nonce: str) -> bool:
    return nonce in _used_nonces

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


def issue_nonce(address: str, domain: str) -> str:
    """Stateless, domain- and address-bound nonce with a rolling time window.
    A random component keeps successive issuances unique, so single-use
    enforcement can never self-DoS a legitimate re-authentication inside the
    same window."""
    window = int(time.time() // NONCE_WINDOW_SECONDS)
    payload = f"siwe|{domain.lower()}|{address.lower()}|{window}|{secrets.token_hex(8)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{window:x}-{digest}"


def nonce_is_fresh(nonce: str) -> bool:
    try:
        window_hex, _ = nonce.split("-", 1)
        window = int(window_hex, 16)
    except (ValueError, AttributeError):
        return False
    current = int(time.time() // NONCE_WINDOW_SECONDS)
    return window in (current, current - 1)  # tolerate one window of skew


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
        if ":" in line and not line.startswith("0x"):
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
    malformed message, wrong domain, expired, stale nonce, or bad signature.
    """
    fields = parse_siwe(message)
    if fields is None:
        return None
    if fields.domain.lower() != expected_domain.lower():
        return None
    if not nonce_is_fresh(fields.nonce):
        return None
    if nonce_is_used(fields.nonce):
        return None  # replayed signature — each nonce authenticates exactly once
    if fields.chain_id is not None and fields.chain_id != EXPECTED_CHAIN_ID:
        return None  # statement bound to a different chain than this server
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
