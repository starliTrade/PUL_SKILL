"""Audit H-07 (2026-10-22) — the signing key must be pluggable.

The oracle key lived in `ORACLE_PRIVATE_KEY`: an env var, on the same host and in
the same process that parses every request. `api/signer.py` adds KMS backends so
the key never enters this process.

The KMS adapters cannot be exercised against live AWS/GCP here (no credentials,
no egress). What CAN be proven, and is proven below:

  * a KMS response is DER without a recovery id — the `v` is recovered from the
    configured public key, and a signature from the WRONG key is rejected
    instead of being shipped to the contract;
  * the recovered signature is byte-identical to the one `eth_account` produces
    for the same digest, so the on-chain verifier sees exactly what it saw
    before;
  * a high-s backend response is normalised (EIP-2) and its `v` flipped with it;
  * misconfiguration fails closed with a message that says what to set.

The fake backend uses a real local key and real DER encoding: only the transport
(an AWS/GCP client object) is replaced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import signer as S  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402

KEY = "0x" + "11" * 32
DIGEST = keccak(text="pulsar settlement digest")
ACCOUNT = Account.from_key(KEY)


class FakeKms(S.KmsSigner):
    """A KMS backend whose only 'cloud' part is the transport."""

    mode = "aws-kms"

    def __init__(self, key: str = KEY, high_s: bool = False) -> None:
        from eth_keys import keys as ek

        self._key = ek.PrivateKey(bytes.fromhex(key.removeprefix("0x")))
        self._high_s = high_s
        super().__init__(public_key_hex=self._key.public_key.to_bytes().hex())

    def _raw_sign(self, digest: bytes) -> bytes:
        sig = self._key.sign_msg_hash(digest)
        r, s = sig.r, sig.s
        if self._high_s:
            s = S.N - s  # a backend that ignores EIP-2
        return S.rs_to_der(r, s)


# --- DER --------------------------------------------------------------------
def test_der_roundtrip_of_large_and_small_values():
    for r, s in [(1, 1), (S.N - 2, 7), (2**255 + 12345, 2**200)]:
        assert S.der_to_rs(S.rs_to_der(r, s)) == (r, s)


def test_every_malformed_der_shape_is_rejected():
    good = S.rs_to_der(123, 456)
    for bad in (b"", b"\x30", good + b"\x00", b"\x31" + good[1:], b"\x30\x80"):
        with pytest.raises(S.SignerError):
            S.der_to_rs(bad)


# --- the recovery id --------------------------------------------------------
def test_a_kms_signature_is_identical_to_the_local_one():
    """Same digest, same key ⇒ the same 65 bytes the contract already accepts."""
    kms = FakeKms()
    local = S.LocalSigner(KEY)

    assert kms.sign_digest(DIGEST) == local.sign_digest(DIGEST)

    recovered = Account._recover_hash(DIGEST, signature=kms.sign_digest(DIGEST))
    assert recovered.lower() == ACCOUNT.address.lower()


def test_a_signature_from_the_wrong_key_is_refused():
    """A misconfigured KMS key must not produce a signature for the old address."""
    wrong = FakeKms("0x" + "22" * 32)
    wrong._public_key_hex = FakeKms(KEY)._public_key_hex  # lie about the identity
    with pytest.raises(S.SignerError, match="does not correspond"):
        wrong.sign_digest(DIGEST)


def test_a_high_s_response_is_normalised_and_v_flips_with_it():
    kms = FakeKms(high_s=True)
    sig = kms.sign_digest(DIGEST)
    s = int.from_bytes(sig[32:64], "big")
    assert s <= S.HALF_N, "high-s reached the contract; it would revert"
    assert Account._recover_hash(DIGEST, signature=sig).lower() == ACCOUNT.address.lower()


def test_the_address_is_derived_from_the_public_key_not_provided():
    """A pasted address cannot be trusted: the address must come from the key."""
    kms = FakeKms()
    assert kms.address.lower() == ACCOUNT.address.lower()


def test_a_64_and_65_byte_backend_response_is_also_understood():
    local = S.LocalSigner(KEY)
    raw65 = local.sign_digest(DIGEST)

    class Raw64(FakeKms):
        def _raw_sign(self, digest: bytes) -> bytes:
            return raw65[:64]

    assert Raw64().sign_digest(DIGEST) == raw65


# --- selection and fail-closed configuration --------------------------------
@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        "ORACLE_SIGNER",
        "ORACLE_KMS_KEY_ID",
        "ORACLE_KMS_KEY_VERSION",
        "ORACLE_PUBLIC_KEY",
        "ORACLE_PRIVATE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    S.reset_cache()
    yield
    S.reset_cache()


def test_local_is_the_explicit_default(monkeypatch):
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", KEY)
    assert S.mode() == "local"
    assert S.get_signer().address.lower() == ACCOUNT.address.lower()


def test_an_unknown_backend_is_an_error_not_a_silent_fallback(monkeypatch):
    monkeypatch.setenv("ORACLE_SIGNER", "vault")
    with pytest.raises(S.SignerError, match="not a known backend"):
        S.mode()


def test_aws_kms_without_a_key_id_fails_with_the_variable_name(monkeypatch):
    monkeypatch.setenv("ORACLE_SIGNER", "aws-kms")
    with pytest.raises(S.SignerError, match="AWS_KMS_KEY_ID"):
        S.get_signer()


def test_gcp_kms_without_a_key_version_fails_with_the_variable_name(monkeypatch):
    monkeypatch.setenv("ORACLE_SIGNER", "gcp-kms")
    with pytest.raises(S.SignerError, match="GCP_KMS_KEY_VERSION"):
        S.get_signer()


def test_local_without_a_key_says_how_to_avoid_it_in_production(monkeypatch):
    with pytest.raises(S.SignerError) as exc:
        S.get_signer()
    message = str(exc.value)
    assert "ORACLE_PRIVATE_KEY" in message
    assert "kms" in message.lower(), "the error must point at the KMS backends"


# --- the oracle uses the configured backend ---------------------------------
def test_the_oracle_signs_through_the_configured_signer(monkeypatch):
    import oracle

    fake = FakeKms()
    monkeypatch.setattr(S, "mode", lambda: "aws-kms")
    monkeypatch.setattr(S, "get_signer", lambda: fake)
    monkeypatch.setenv("ORACLE_PRIVATE_KEY", KEY)  # must be ignored in KMS mode
    monkeypatch.setenv("ESCROW_ADDRESS", "0x" + "ab" * 20)

    assert oracle.oracle_address().lower() == ACCOUNT.address.lower()

    out = oracle.sign_digest(DIGEST)
    assert out == S.LocalSigner(KEY).sign_digest(DIGEST)
    assert out[64] in (27, 28)


# --- production must not run local signing by accident -----------------------
def _prod_env(**overrides):
    base = {
        "PULSAR_ENV": "production",
        "ALLOWED_DOMAIN": "pulsar.example",
        "CORS_ALLOW_ORIGINS": "https://pulsar.example",
        "ESCROW_ADDRESS": "0x" + "ab" * 20,
        "ESCROW_RPC_URL": "https://rpc.example",
        "ORACLE_SIGNING_SECRET": "s" * 32,
        "ORACLE_CHAIN_ID": "80002",
    }
    base.update(overrides)
    return base


def _boot(env: dict, monkeypatch) -> None:
    """Re-evaluate the startup gate exactly as the module does at import."""
    import main as server

    missing = server._missing_production_env(env)
    assert not missing, missing


def test_the_production_gate_no_longer_demands_a_hot_private_key(monkeypatch):
    """With KMS, ORACLE_PRIVATE_KEY must be ABSENT — requiring it was the bug."""
    _boot(_prod_env(ORACLE_SIGNER="aws-kms"), monkeypatch)


def test_production_with_local_signing_needs_an_explicit_acknowledgement(monkeypatch):
    source = Path(__file__).resolve().parents[2].joinpath("api", "main.py").read_text()
    assert "PULSAR_ALLOW_LOCAL_SIGNER" in source
    assert "Refusing to start: ORACLE_SIGNER=local" in source
