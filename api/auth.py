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
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct

SESSION_TTL_SECONDS = 60 * 60 * 24          # 24h
NONCE_WINDOW_SECONDS = 60 * 5               # 5-minute validity window

# Audit-#3 fix: the SIWE statement must carry the chain the app actually runs
# on (the client builds it with CHAIN.chainId — Amoy 80002 by default). A
# message signed for a different chain is rejected instead of silently
# accepted, so a mainnet-phished statement can never authenticate here.
EXPECTED_CHAIN_ID = int(os.environ.get("ORACLE_CHAIN_ID", "80002"))

# Local fallback for callers that do not inject the durable nonce consumer.
# The HTTP API injects DurableMatchStore.consume_auth_nonce(), which makes
# consumption atomic across Firestore-backed replicas.
_used_nonces: dict[str, float] = {}
_used_nonces_lock = threading.Lock()
_USED_NONCE_MAX = 4096


def _burn_nonce(nonce: str) -> bool:
    """Atomically consume a nonce in the single-process fallback store."""
    now = time.time()
    with _used_nonces_lock:
        for value, expires_at in list(_used_nonces.items()):
            if expires_at <= now:
                _used_nonces.pop(value, None)
        if nonce in _used_nonces:
            return False
        if len(_used_nonces) >= _USED_NONCE_MAX:
            oldest = min(_used_nonces, key=_used_nonces.get)
            _used_nonces.pop(oldest, None)
        _used_nonces[nonce] = now + NONCE_WINDOW_SECONDS
        return True


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
    """Issue an authenticated, EIP-4361-compatible alphanumeric nonce.

    The hex payload binds issue time, entropy, wallet, and domain. Its HMAC
    proves the nonce came from this server without retaining issuance state.
    """
    payload = json.dumps(
        {
            "a": address.lower(),
            "d": domain.lower(),
            "iat": int(time.time()),
            "r": secrets.token_hex(16),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8").hex()
    return f"{payload}{_hmac_hex(f'siwe-nonce|{payload}')}"


def nonce_is_fresh(nonce: str, address: str = "", domain: str = "") -> bool:
    try:
        if len(nonce) < 66 or not re.fullmatch(r"[0-9a-fA-F]+", nonce):
            return False
        payload_hex, supplied_mac = nonce[:-64], nonce[-64:]
        if not hmac.compare_digest(
            _hmac_hex(f"siwe-nonce|{payload_hex}"), supplied_mac.lower()
        ):
            return False
        claims = json.loads(bytes.fromhex(payload_hex).decode("utf-8"))
        issued_at = int(claims["iat"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    now = int(time.time())
    if issued_at > now + 30 or now - issued_at > NONCE_WINDOW_SECONDS:
        return False
    if address and str(claims.get("a", "")).lower() != address.lower():
        return False
    if domain and str(claims.get("d", "")).lower() != domain.lower():
        return False
    return True


@dataclass
class SiweFields:
    address: str
    domain: str
    nonce: str
    issued_at: str
    expiration_time: str
    chain_id: int | None
    uri: str
    version: str


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
        uri=fields.get("URI", ""),
        version=fields.get("Version", ""),
    )


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def verify_siwe(
    message: str,
    signature: str,
    expected_domain: str,
    consume_nonce: Callable[[str], bool] | None = None,
) -> str | None:
    """
    Returns the lowercase verified address, or None if anything fails:
    malformed message, wrong domain, expired, stale nonce, or bad signature.
    """
    fields = parse_siwe(message)
    if fields is None:
        return None
    if fields.domain.lower() != expected_domain.lower():
        return None
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", fields.address):
        return None
    if not nonce_is_fresh(fields.nonce, fields.address, expected_domain):
        return None
    if fields.chain_id != EXPECTED_CHAIN_ID or fields.version != "1":
        return None
    uri = urlparse(fields.uri)
    if (
        uri.scheme != "https"
        or uri.netloc.lower() != expected_domain.lower()
        or uri.path not in ("", "/")
        or uri.params
        or uri.query
        or uri.fragment
    ):
        return None
    now = datetime.now(timezone.utc)
    issued_at = _parse_time(fields.issued_at)
    expiration = _parse_time(fields.expiration_time)
    if issued_at is None or expiration is None:
        return None
    if issued_at > now + timedelta(seconds=60) or now >= expiration or expiration <= issued_at:
        return None
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except Exception:
        return None
    address = getattr(recovered, "address", recovered)
    verified = str(address).lower() or None
    if verified != fields.address.lower():
        return None
    consumer = consume_nonce or _burn_nonce
    if not consumer(fields.nonce):
        return None
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
