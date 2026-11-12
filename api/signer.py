"""Pluggable referee signing (audit H-07, 2026-10-22).

THE FINDING
-----------
The oracle's secp256k1 key sat in `ORACLE_PRIVATE_KEY`: a plain environment
variable, on the same host that serves HTTP, in the same process that parses
every request. Anything that reads the environment — a debug endpoint, a log
scraper, a dependency's post-install script, a core dump — reads the key that
decides who wins every active duel. And there was no way to move it out without
editing `oracle.py`.

WHAT THIS MODULE IS
-------------------
One interface (`sign_digest`) with three implementations:

  * `local`    — a key in env/KMS-less mode. Same behaviour as before, but now
                 it is an explicit, named choice (`ORACLE_SIGNER=local`) rather
                 than the only option.
  * `aws-kms`  — AWS KMS asymmetric key (ECC_SECG_P256K1, ECDSA_SHA_256),
                 signing the DIGEST directly (`MessageType='DIGEST'`), so KMS
                 never hashes twice and the Ethereum digest is what gets signed.
  * `gcp-kms`  — GCP KMS EC_SIGN_SECP256K1_SHA256, again passed the 32-byte
                 digest.

In the KMS modes the private key never enters this process. The signature comes
back DER-encoded without a recovery id, so `KmsSigner` recovers `v` by trying
both candidates and keeping the one that reproduces the configured public key —
an operation that is a few dozen microseconds and happens once per settlement.

HONEST LIMITS
-------------
- The two KMS adapters are implemented against the documented request/response
  shapes and tested with a fake client that produces real DER signatures and a
  real public key. They have NOT been run against live AWS/GCP: this environment
  has no cloud credentials. That is stated here rather than discovered in
  production.
- KMS removes the *key at rest* problem. It does not remove the *authority*
  problem: whoever can call the signer can still pick the winner. Audit H-07's
  remaining items (dual approval for large payouts, a payout delay, a public
  transparency log) are policy, not key storage — see
  docs/audit/REMEDIATION-TODO-2026-10-22.md §5.
"""

from __future__ import annotations

import os
from typing import Any

from eth_keys import keys as eth_keys
from eth_utils import keccak

# secp256k1 group order. A valid ECDSA `s` is in the lower half (EIP-2); the
# escrow contract rejects high-s signatures, so normalisation happens here.
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
HALF_N = N // 2

MODES = ("local", "aws-kms", "gcp-kms")


class SignerError(RuntimeError):
    """Configuration or backend failure. Never swallowed by callers."""


def mode() -> str:
    """The configured backend. Defaults to `local` for backward compatibility."""
    chosen = os.environ.get("ORACLE_SIGNER", "local").strip().lower() or "local"
    if chosen not in MODES:
        raise SignerError(
            f"ORACLE_SIGNER={chosen!r} is not a known backend (expected one of {MODES})"
        )
    return chosen


# --- DER <-> (r, s) ---------------------------------------------------------


def der_to_rs(der: bytes) -> tuple[int, int]:
    """Parse a DER `SEQUENCE { INTEGER r, INTEGER s }` signature.

    Deliberately strict: an ambiguity here means signing with the wrong numbers
    and discovering it as an on-chain revert, so every malformed shape raises.
    """
    if len(der) < 8 or der[0] != 0x30:
        raise SignerError(f"not a DER sequence: {der[:4].hex()}")
    idx = 1
    if der[idx] & 0x80:  # long-form length
        n_len = der[idx] & 0x7F
        idx += 1
        length = int.from_bytes(der[idx : idx + n_len], "big")
        idx += n_len
    else:
        length = der[idx]
        idx += 1
    if idx + length != len(der):
        raise SignerError("DER length does not match the payload")

    def _int() -> int:
        nonlocal idx
        if der[idx] != 0x02:
            raise SignerError("DER: expected an INTEGER")
        idx += 1
        size = der[idx]
        idx += 1
        raw = der[idx : idx + size]
        idx += size
        if len(raw) != size:
            raise SignerError("DER: truncated INTEGER")
        return int.from_bytes(raw, "big")

    r = _int()
    s = _int()
    if idx != len(der):
        raise SignerError("DER: trailing bytes")
    if not (0 < r < N and 0 < s < N):
        raise SignerError("DER: r or s out of range")
    return r, s


def _der_int(value: int) -> bytes:
    raw = value.to_bytes(32, "big").lstrip(b"\x00") or b"\x00"
    if raw[0] & 0x80:  # keep the integer positive
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def rs_to_der(r: int, s: int) -> bytes:
    body = _der_int(r) + _der_int(s)
    return b"\x30" + bytes([len(body)]) + body


# --- the interface ----------------------------------------------------------


class Signer:
    """What the oracle needs: an address, and a low-s signature over a digest."""

    mode = "abstract"

    @property
    def address(self) -> str:
        raise NotImplementedError

    def _raw_sign(self, digest: bytes) -> bytes:
        """Backend-specific signature over the 32-byte digest (DER)."""
        raise NotImplementedError

    def sign_digest(self, digest: bytes) -> bytes:
        """65-byte `r || s || v` with v in {27, 28} and s in the lower half."""
        if len(digest) != 32:
            raise SignerError("the oracle signs a 32-byte digest")
        der = self._raw_sign(digest)
        if der[:1] == b"\x30":
            r, s = der_to_rs(der)
        elif len(der) == 64:  # some HSM APIs return r||s without DER
            r, s = int.from_bytes(der[:32], "big"), int.from_bytes(der[32:], "big")
        elif len(der) == 65:
            r, s = int.from_bytes(der[:32], "big"), int.from_bytes(der[32:64], "big")
        else:
            raise SignerError(f"unrecognised signature format ({len(der)} bytes)")

        if not (0 < r < N and 0 < s < N):
            raise SignerError("signature values out of range")

        v = self._recover_v(digest, r, s)
        if s > HALF_N:
            # EIP-2: the contract rejects high-s. Flipping s is the same
            # signature with the opposite point parity, so v flips with it.
            s = N - s
            v ^= 1
        return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + v])

    def _recover_v(self, digest: bytes, r: int, s: int) -> int:
        """Find the parity byte that reproduces this signer's address."""
        wanted = self.address.lower()
        for candidate in (0, 1):
            try:
                pub = eth_keys.Signature(
                    vrs=(candidate, r, s)
                ).recover_public_key_from_msg_hash(digest)
            except Exception:  # noqa: BLE001 - a wrong parity simply fails
                continue
            if _address_of(pub.to_bytes()) == wanted:
                return candidate
        raise SignerError(
            "the backend signature does not correspond to the configured public key "
            "(is the KMS key the one the escrow trusts?)"
        )


def _address_of(uncompressed: bytes) -> str:
    """Ethereum address from a 64-byte (x||y) or 65-byte (0x04||x||y) key."""
    if len(uncompressed) == 65 and uncompressed[0] == 4:
        uncompressed = uncompressed[1:]
    if len(uncompressed) != 64:
        raise SignerError("expected an uncompressed secp256k1 public key")
    return "0x" + keccak(uncompressed)[12:].hex()


class LocalSigner(Signer):
    """A key in memory. Explicit opt-in (`ORACLE_SIGNER=local`)."""

    mode = "local"

    def __init__(self, private_key: str) -> None:
        from eth_account import Account

        self._account = Account.from_key(
            private_key if private_key.startswith("0x") else f"0x{private_key}"
        )

    @property
    def address(self) -> str:
        return str(self._account.address)

    def _raw_sign(self, digest: bytes) -> bytes:
        account = self._account
        if hasattr(account, "unsafe_sign_hash"):
            signed = account.unsafe_sign_hash(digest)
        elif hasattr(account, "signHash"):
            signed = account.signHash(digest)
        else:  # pragma: no cover - very old eth-account
            signed = account.sign_hash(digest)
        return bytes(rs_to_der(int(signed.r), int(signed.s)))

    def sign_digest(self, digest: bytes) -> bytes:
        # Fast path: the library already returns r,s,v; no recovery needed.
        account = self._account
        if hasattr(account, "unsafe_sign_hash"):
            signed = account.unsafe_sign_hash(digest)
        elif hasattr(account, "signHash"):
            signed = account.signHash(digest)
        else:  # pragma: no cover
            signed = account.sign_hash(digest)
        r, s = int(signed.r), int(signed.s)
        v = int(signed.v)
        if v >= 27:
            v -= 27
        if s > HALF_N:
            s = N - s
            v ^= 1
        return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + v])


class KmsSigner(Signer):
    """Shared logic for HSM/KMS backends that return DER without a recovery id."""

    mode = "kms"

    def __init__(self, *, public_key_hex: str = "") -> None:
        # The escrow trusts an ADDRESS. Deriving it from the KMS public key is
        # the only way to prove the backend holds the matching private key; a
        # hex override exists for keys whose public part cannot be exported.
        self._public_key_hex = public_key_hex.strip().lower().removeprefix("0x")

    def _public_key(self) -> bytes:
        if not self._public_key_hex:
            raise SignerError(
                f"{self.mode}: the public key is required to derive the signer address"
            )
        return bytes.fromhex(self._public_key_hex)

    @property
    def address(self) -> str:
        return _address_of(self._public_key())


class AwsKmsSigner(KmsSigner):
    """AWS KMS asymmetric key (ECC_SECG_P256K1).

    The digest is passed with `MessageType='DIGEST'` so KMS signs the Ethereum
    hash directly instead of hashing it a second time — a double hash produces a
    signature that is valid for nothing.
    """

    mode = "aws-kms"

    def __init__(self, key_id: str, public_key_hex: str = "", region: str = "") -> None:
        super().__init__(public_key_hex=public_key_hex)
        if not key_id:
            raise SignerError("AWS_KMS_KEY_ID is required for ORACLE_SIGNER=aws-kms")
        self._key_id = key_id
        self._region = region or os.environ.get("AWS_REGION", "")

    def _client(self) -> Any:
        try:
            import boto3  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SignerError(
                "ORACLE_SIGNER=aws-kms needs boto3 (pip install 'boto3>=1.34')"
            ) from exc
        kwargs = {"service_name": "kms"}
        if self._region:
            kwargs["region_name"] = self._region
        return boto3.client(**kwargs)

    def _public_key(self) -> bytes:
        if self._public_key_hex:
            return bytes.fromhex(self._public_key_hex)
        resp = self._client().get_public_key(KeyId=self._key_id)
        der = resp["PublicKey"]
        # SubjectPublicKeyInfo: the last 65 bytes are 0x04 || X || Y for P-256K1.
        spki = bytes(der)
        if len(spki) < 65 or spki[-65] != 0x04:
            raise SignerError("unexpected KMS public key encoding")
        self._public_key_hex = spki[-65:].hex()
        return bytes.fromhex(self._public_key_hex)

    def _raw_sign(self, digest: bytes) -> bytes:
        resp = self._client().sign(
            KeyId=self._key_id,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return bytes(resp["Signature"])


class GcpKmsSigner(KmsSigner):
    """GCP KMS EC_SIGN_SECP256K1_SHA256 key version.

    GCP signs the 32-byte digest it is given (it does not re-hash), which is
    what Ethereum needs.
    """

    mode = "gcp-kms"

    def __init__(self, key_version: str, public_key_hex: str = "") -> None:
        super().__init__(public_key_hex=public_key_hex)
        if not key_version:
            raise SignerError(
                "GCP_KMS_KEY_VERSION is required for ORACLE_SIGNER=gcp-kms "
                "(projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>/cryptoKeyVersions/<v>)"
            )
        self._key_version = key_version

    def _client(self) -> Any:
        try:
            from google.cloud import kms  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SignerError(
                "ORACLE_SIGNER=gcp-kms needs google-cloud-kms "
                "(pip install 'google-cloud-kms>=2.21')"
            ) from exc
        return kms.KeyManagementServiceClient()

    def _public_key(self) -> bytes:
        if self._public_key_hex:
            return bytes.fromhex(self._public_key_hex)
        resp = self._client().get_public_key(request={"name": self._key_version})
        pem = resp.pem
        # Minimal PEM handling: the DER body's last 65 bytes are the point.
        import base64

        body = "".join(
            line for line in pem.splitlines() if line and not line.startswith("-----")
        )
        der = base64.b64decode(body)
        if len(der) < 65 or der[-65] != 0x04:
            raise SignerError("unexpected GCP KMS public key encoding")
        self._public_key_hex = der[-65:].hex()
        return bytes.fromhex(self._public_key_hex)

    def _raw_sign(self, digest: bytes) -> bytes:
        resp = self._client().asymmetric_sign(
            request={
                "name": self._key_version,
                "digest": {"sha256": digest},
            }
        )
        return bytes(resp.signature)


# --- selection --------------------------------------------------------------

_signer_cache: Signer | None = None
_signer_cache_key: str | None = None


def reset_cache() -> None:
    """Test seam and key-rotation hook."""
    global _signer_cache, _signer_cache_key
    _signer_cache = None
    _signer_cache_key = None


def _config_key() -> str:
    return "|".join(
        [
            mode(),
            os.environ.get("ORACLE_KMS_KEY_ID", ""),
            os.environ.get("ORACLE_KMS_KEY_VERSION", ""),
            os.environ.get("ORACLE_PUBLIC_KEY", ""),
            os.environ.get("AWS_REGION", ""),
        ]
    )


def get_signer() -> Signer:
    """The configured signer, built once per configuration."""
    global _signer_cache, _signer_cache_key
    key = _config_key()
    if _signer_cache is not None and _signer_cache_key == key:
        return _signer_cache

    chosen = mode()
    public_key = os.environ.get("ORACLE_PUBLIC_KEY", "").strip()
    if chosen == "local":
        private = os.environ.get("ORACLE_PRIVATE_KEY", "").strip()
        if not private:
            raise SignerError(
                "ORACLE_PRIVATE_KEY is required for ORACLE_SIGNER=local. "
                "In production use ORACLE_SIGNER=aws-kms or gcp-kms so the key "
                "never enters this process (audit H-07)."
            )
        signer: Signer = LocalSigner(private)
    elif chosen == "aws-kms":
        signer = AwsKmsSigner(
            key_id=os.environ.get("ORACLE_KMS_KEY_ID", "").strip(), public_key_hex=public_key
        )
    else:
        signer = GcpKmsSigner(
            key_version=os.environ.get("ORACLE_KMS_KEY_VERSION", "").strip(),
            public_key_hex=public_key,
        )
    _signer_cache = signer
    _signer_cache_key = key
    return signer
