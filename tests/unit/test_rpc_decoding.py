"""The two decoders that stand between a contract's answer and a server decision.

Ranked gap #3 in `docs/COVERAGE-REPORT.md`: `onchain._decode_string`'s exception
path, `escrow_version_problem`'s "unreadable" branch, and
`_escrow_token_address`'s short-answer branch. None of them was reached by any
test, and all three are on the money path — they decide whether the escrow is
considered compatible and whether `decimals()` is even attempted.

What is at stake, concretely:

* `VERSION()` is a dynamic `string`. A contract can answer with a well-formed
  ABI string, with garbage, with a truncated one, or with bytes that are not
  UTF-8. The server must map every one of those to `None` — never to a
  half-decoded name, and never to an exception that turns `/api/health` into a
  500. `/api/health` is public and unauthenticated, so a hostile payload must
  also not be *reflected* back (that part is already pinned in
  `test_contract_version.py`; here the decoder itself is exercised).
* `paymentToken()` is an `address`. A truncated answer (a proxy that has not
  been initialised, a mock in a staging deployment) must not be read as an
  address; `token_decimals()` must fail closed and then NOT hammer the RPC while
  its cooldown runs.

The cooldown assertion is the interesting one: it is a *rate* property, so it
is asserted by counting RPC calls, not by trusting a comment.
"""

from __future__ import annotations

import pytest

import onchain
from tests.fixtures.fake_rpc import SEL_PAYMENT_TOKEN, FakeRpc, configure_escrow, word

# A well-formed ABI header (offset 32) followed by `length` bytes of payload.
HEADER = word(32)


def _abi_string(raw: bytes) -> str:
    """A dynamic-string payload whose bytes are exactly `raw` (may be invalid UTF-8)."""
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return "0x" + HEADER + word(len(raw)) + padded.hex()


# --- 1. a broken VERSION() must not become a name, and must not raise ---------
def test_non_hex_version_payload_is_unreadable_not_a_name(monkeypatch):
    # Not hex at all: `bytes.fromhex` raises inside the decoder.
    configure_escrow(monkeypatch, FakeRpc(escrow_version_raw="0x" + "zz" * 40))
    version = onchain.escrow_version()
    assert version is not None, "the escrow is configured; a bad string is not 'no escrow'"
    assert version["name"] is None
    # The code was readable and correct, so the escrow is still compatible: one
    # broken cosmetic read must not condemn a working deployment.
    assert version["compatible"] is True


def test_a_version_string_that_is_not_utf8_is_unreadable(monkeypatch):
    configure_escrow(monkeypatch, FakeRpc(escrow_version_raw=_abi_string(b"\xff\xfe\xfd")))
    assert onchain.escrow_version()["name"] is None


def test_a_version_string_with_a_length_past_the_payload_is_unreadable(monkeypatch):
    # Declares 32 bytes but supplies none: the slice is short, so the decode
    # yields "" and the sanity check (not empty) rejects it.
    configure_escrow(monkeypatch, FakeRpc(escrow_version_raw="0x" + HEADER + word(32)))
    assert onchain.escrow_version()["name"] is None


def test_a_control_character_version_string_is_not_reflected(monkeypatch):
    # Printable-only, because /api/health is public. A newline or an escape
    # sequence in a JSON body is how a log injection starts.
    configure_escrow(monkeypatch, FakeRpc(escrow_version_raw=_abi_string(b"2.0.0\n")))
    assert onchain.escrow_version()["name"] is None


def test_a_correct_payload_still_decodes(monkeypatch):
    # The control for all of the above: the same path with a good answer works,
    # so these tests are not passing merely because the fake is misconfigured.
    configure_escrow(monkeypatch, FakeRpc(escrow_version_name="2.0.0"))
    assert onchain.escrow_version()["name"] == "2.0.0"
    assert onchain.escrow_version_problem() is None


# --- 2. the "unreadable escrow" health line ----------------------------------
def test_an_unreadable_version_is_reported_as_unreadable(monkeypatch):
    """`escrow_version_problem` has a branch for `escrow_version() is None`.

    Reachability, stated honestly: `escrow_configured()` is checked one line
    earlier, and `escrow_version()` only returns None when it is false. So this
    branch fires only if the environment changes between the two reads (an
    operator unsetting ESCROW_ADDRESS mid-flight) or if a future version reader
    gains another reason to answer "nothing". It is one string, kept so that
    `/api/health` can never say "compatible" because a reader returned None;
    the test pins the string rather than pretending the internal path is
    reachable today.
    """
    configure_escrow(monkeypatch, FakeRpc())
    monkeypatch.setattr(onchain, "escrow_version", lambda: None)
    assert onchain.escrow_version_problem() == "escrow version unreadable"


# --- 3. a truncated paymentToken() fails closed and does not hammer the RPC ---
def test_a_truncated_token_address_is_not_read_as_an_address(monkeypatch):
    rpc = FakeRpc()
    rpc.break_call(SEL_PAYMENT_TOKEN)  # answers "0x": no data
    configure_escrow(monkeypatch, rpc)

    assert onchain._escrow_token_address() is None
    assert onchain.token_decimals() is None, (
        "a short paymentToken() answer was treated as an address, so decimals() was read from the wrong place"
    )


def test_the_decimals_failure_is_cached_briefly_not_hit_on_every_call(monkeypatch):
    rpc = FakeRpc()
    rpc.break_call(SEL_PAYMENT_TOKEN)
    configure_escrow(monkeypatch, rpc)
    assert onchain.token_decimals() is None

    calls_after_first_failure = len(rpc.calls)
    for _ in range(5):
        assert onchain.token_decimals() is None
    assert len(rpc.calls) == calls_after_first_failure, (
        "a failing decimals() read was retried on every call — a dead or "
        "misconfigured escrow would be hammered once per request"
    )


def test_the_cooldown_expires_and_the_read_is_retried(monkeypatch):
    rpc = FakeRpc()
    rpc.break_call(SEL_PAYMENT_TOKEN)
    configure_escrow(monkeypatch, rpc)
    assert onchain.token_decimals() is None
    rpc.malformed_selectors.clear()  # the contract recovers
    calls_before = len(rpc.calls)

    # Past the cooldown (never a fixed stamp: `timebase.now()` is monotonic and
    # must be moved, not guessed — see tests/unit/test_clock_seam.py).
    monkeypatch.setattr(onchain, "_token_decimals_retry_after", 0.0)
    assert onchain.token_decimals() == rpc.token_decimals
    assert len(rpc.calls) > calls_before


def test_decimals_above_uint8_is_refused(monkeypatch):
    # Already covered elsewhere; repeated here because it shares the branch this
    # module is about, and a regression would scale every stake by 10^garbage.
    rpc = FakeRpc(token_decimals=1000)
    configure_escrow(monkeypatch, rpc)
    assert onchain.token_decimals() is None


# --- 4. the decoder must not be lenient in the other direction ---------------
@pytest.mark.parametrize("payload", ["0x", "0x12", "0x" + word(32), "0x" + "zz" * 40])
def test_short_empty_and_garbage_payloads_decode_to_none(payload, monkeypatch):
    # Directly, so the decoder's own `except` is load-bearing in the test: if it
    # is deleted, this raises instead of answering None (going through
    # `escrow_version` alone would hide that behind ITS try/except).
    assert onchain._decode_string(payload) is None
    configure_escrow(monkeypatch, FakeRpc(escrow_version_raw=payload))
    assert onchain.escrow_version()["name"] is None
