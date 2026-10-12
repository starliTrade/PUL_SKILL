"""
Phase 7 / M1 — `verify_siwe` must check that the signer is the claimed address.

The function recovers the address from the signature and returns it, but never
compares it with the address the MESSAGE claims. Today that is not directly
exploitable — the caller issues the session for the recovered address, so an
attacker who signs with A gets a session for A — but the contract is ambiguous,
and ambiguity in an authentication function is how the next change becomes a
vulnerability.

The invariant that should hold: **the returned address is the signer AND the
message's claimed address.** A statement that claims B and is signed by A must
be rejected, not silently reinterpreted as A.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import auth  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

DOMAIN = "localhost"


def _message(claim_address: str, nonce: str) -> str:
    return (
        f"{DOMAIN} wants you to sign in with your Ethereum account:\n"
        f"{claim_address}\n\n"
        f"Sign in to PULSAR.\n\n"
        f"URI: https://{DOMAIN}\n"
        f"Version: 1\n"
        f"Chain ID: {auth.EXPECTED_CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
    )


def _nonce_for(address: str) -> str:
    return auth.issue_nonce(address, DOMAIN)


# --- the finding --------------------------------------------------------------
def test_a_statement_signed_by_a_different_address_is_rejected():
    """The claimed address must BE the signer."""
    signer = Account.create()
    claimant = Account.create()

    # The nonce is bound to the CLAIMANT, and the message claims the claimant —
    # but the signature is the SIGNER's.
    nonce = _nonce_for(claimant.address)
    message = _message(claimant.address, nonce)
    signed = Account.sign_message(encode_defunct(text=message), private_key=signer.key)

    result = auth.verify_siwe(message, signed.signature.hex(), DOMAIN)

    assert result is None, (
        "a statement claiming one address and signed by another was accepted "
        f"(returned {result!r}) — audit M1"
    )


def test_the_honest_case_still_works():
    """The control: signer == claimant must still authenticate."""
    account = Account.create()
    nonce = _nonce_for(account.address)
    message = _message(account.address, nonce)
    signed = Account.sign_message(encode_defunct(text=message), private_key=account.key)

    result = auth.verify_siwe(message, signed.signature.hex(), DOMAIN)

    assert result == account.address.lower()


def test_the_returned_address_is_the_claimed_one():
    """Whatever is returned must be the address the message names."""
    account = Account.create()
    nonce = _nonce_for(account.address)
    message = _message(account.address, nonce)
    signed = Account.sign_message(encode_defunct(text=message), private_key=account.key)

    result = auth.verify_siwe(message, signed.signature.hex(), DOMAIN)

    assert result == account.address.lower()
