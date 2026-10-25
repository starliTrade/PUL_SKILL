"""The last line between a settlement and a signature: which eth-account API is used.

Ranked gap #2 in `docs/COVERAGE-REPORT.md`: `oracle._sign_hash_bytes`, lines
148-152 — the `signHash` / `sign_hash` fallbacks and the final `raise`.

Why this is not cosmetic. `eth-account` has renamed its raw-digest entry point
more than once (`signHash` -> `sign_hash` -> `unsafe_sign_hash`, the last one
renamed precisely because signing an arbitrary digest is dangerous). The server
pins a version in `requirements.lock`, so today exactly one of those exists —
which is why the other two branches never execute, and why a lockfile bump is
the moment they matter. Two failure modes are worth a test:

* **a rename that removes the pin's method**: without the fallbacks, every
  settlement would raise inside the signing path and no duel could ever be
  cashed out. The fallbacks turn a hard outage into a version bump that just
  works.
* **an API that disappears entirely**: the code must say so in one sentence,
  naming the problem, instead of raising `AttributeError: 'Account' object has
  no attribute 'unsafe_sign_hash'` — which names a method, not the cause, at
  3 a.m. during an incident.

Precedence is asserted too: `unsafe_sign_hash` first, because that is the API
this version documents, and a fallback that silently wins over the intended
method would hide a partial upgrade.
"""

from __future__ import annotations

import pytest

import oracle


class _FakeAccount:
    """An account exposing only the named signing methods."""

    def __init__(self, **methods):
        for name, value in methods.items():
            setattr(self, name, value)

    def _recorder(self, name, seen):
        def sign(digest):
            seen.append((name, digest))
            return {"via": name, "digest": digest}

        return sign


def test_unsafe_sign_hash_is_preferred_when_all_three_exist():
    seen: list[tuple[str, bytes]] = []
    account = _FakeAccount(
        unsafe_sign_hash=_FakeAccount._recorder(None, "unsafe_sign_hash", seen),
        signHash=_FakeAccount._recorder(None, "signHash", seen),
        sign_hash=_FakeAccount._recorder(None, "sign_hash", seen),
    )
    out = oracle._sign_hash_bytes(account, b"\x01" * 32)
    assert out["via"] == "unsafe_sign_hash"
    assert [name for name, _ in seen] == ["unsafe_sign_hash"]


@pytest.mark.parametrize("method", ["signHash", "sign_hash"])
def test_an_older_eth_account_still_signs(method):
    seen: list[tuple[str, bytes]] = []
    account = _FakeAccount(**{method: _FakeAccount._recorder(None, method, seen)})
    out = oracle._sign_hash_bytes(account, b"\x02" * 32)
    assert out["via"] == method
    assert seen == [(method, b"\x02" * 32)], "the digest was altered on the way to the signer"


def test_the_digest_is_passed_through_untouched():
    # A signature over a *different* digest is a signature over a different
    # settlement: this is the cheapest possible check that nothing re-hashes or
    # truncates on the way in.
    captured: list[bytes] = []
    account = _FakeAccount(unsafe_sign_hash=lambda d: (captured.append(d), {"ok": True})[1])
    digest = bytes(range(32))
    oracle._sign_hash_bytes(account, digest)
    assert captured == [digest]


def test_an_account_with_no_signing_api_fails_loudly():
    with pytest.raises(RuntimeError) as exc:
        oracle._sign_hash_bytes(_FakeAccount(), b"\x03" * 32)
    message = str(exc.value)
    assert "hash-signing API" in message
    assert "eth-account" in message, (
        "the error must name WHICH dependency is wrong; an operator reading it "
        "during an incident should not have to grep the source"
    )


def test_the_installed_eth_account_takes_the_tested_branch():
    """The pin and the tests must not drift apart.

    The fallbacks are only useful if the installed library really exposes
    `unsafe_sign_hash` — otherwise every run silently exercises a fallback and
    the "preferred" path above would be the one nobody has ever run.
    """
    from eth_account import Account

    assert hasattr(Account, "unsafe_sign_hash"), (
        "the locked eth-account no longer has unsafe_sign_hash — the oracle is "
        "now signing through a fallback; re-check the signing branch deliberately"
    )
