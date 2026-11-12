"""
PULSAR — the load profile (plan item 10.3).

Every endpoint in the hot path is authenticated (SIWE), so a meaningful load
test cannot just hammer /api/health: it has to hold real sessions. This file
prepares a pool of signed-in players once, then drives the poll paths the game
actually uses.

Run:
    .venv/bin/locust -f load/locustfile.py --headless -u 1000 -r 100 -t 60s \
        --host http://127.0.0.1:8000 --csv /tmp/load

`-u 1000` is the plan's target: 1000 concurrent pollers.
"""

from __future__ import annotations

import json
import os
import random
from collections import Counter

from eth_account import Account
from eth_account.messages import encode_defunct
from locust import HttpUser, between, events, task

HOST = os.environ.get("PULSAR_LOAD_HOST", "http://127.0.0.1:8000")
# `--host` on the command line must win: the session prep posts to absolute
# URLs, and during an audit run it kept posting to the default :8000 while the
# target was elsewhere — the listener died with a connection error, the run
# continued with ZERO sessions, and every task returned early. A load test that
# reports 20 req/s of /api/health while measuring nothing is worse than no test.
_TARGET = HOST
POOL_SIZE = int(os.environ.get("PULSAR_LOAD_POOL", "1200"))

# One funded-looking address per virtual user. These are throwaway keys: the
# load test never moves money, it only needs a valid SIWE statement.
_SESSIONS: list[str] = []
# Address per session, index-aligned. Kept as strings rather than Account
# objects so a tokens file needs no private keys (audit L-06).
_PLAYERS: list[str] = []

# Answers that are legitimate under load but are NOT a completed join (H-21).
_EXPECTED_NON_200: Counter[int] = Counter()


def _sign_in(client, account: Account) -> str | None:
    address = account.address.lower()
    nonce = client.post(f"{_TARGET}/api/auth/nonce", json={"address": address})
    if nonce.status_code != 200:
        return None
    message = nonce.json()["message"]
    signature = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    verify = client.post(
        f"{_TARGET}/api/auth/verify", json={"message": message, "signature": signature}
    )
    if verify.status_code != 200:
        return None
    token = verify.json()["token"]

    # Audit L-06: the profile used to sign in and then hammer `/api/queue`,
    # which is behind the eligibility attestation (G2) — so every join answered
    # 403 and the run measured the gate, not the queue. Attest once per player,
    # the same way the client does, so the load lands on the path under test.
    attested = client.post(
        f"{_TARGET}/api/eligibility/confirm",
        json={"ageConfirmed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    if attested.status_code != 200:
        print(f"[load] eligibility refused: {attested.status_code} {attested.text[:120]}")
        return None
    return token


@events.test_start.add_listener
def _prepare_sessions(environment, **_kwargs) -> None:
    """Get one distinct player per virtual user, before the load starts.

    Two sources, in order:

    * `PULSAR_LOAD_TOKENS` — a JSON list of `{address, token}` from
      `scripts/load_sessions.py`. Required for a large run: `/api/auth/verify`
      allows 30 sign-ins per minute per IP, so 1000 real handshakes would take
      ~33 minutes before the first request, and fewer distinct addresses would
      just measure the per-address rate limiter (audit L-06).
    * otherwise, the SIWE handshake, for a small local run.
    """
    global _TARGET
    _TARGET = environment.host or HOST

    tokens_file = os.environ.get("PULSAR_LOAD_TOKENS", "")
    if tokens_file:
        import requests

        with open(tokens_file, encoding="utf-8") as fh:
            rows = json.load(fh)
        session = requests.Session()
        refused = 0
        for row in rows:
            address = row["address"].lower()
            # The join path is behind the eligibility gate (G2); a token that has
            # not attested would answer 403 and the run would measure the gate.
            res = session.post(
                f"{_TARGET}/api/eligibility/confirm",
                json={"ageConfirmed": True},
                headers={"Authorization": f"Bearer {row['token']}"},
            )
            if res.status_code != 200:
                refused += 1
                continue
            _SESSIONS.append(row["token"])
            _PLAYERS.append(address)
        print(f"[load] loaded {len(_SESSIONS)} sessions from {tokens_file} ({refused} refused)")
        _require_sessions()
        return

    import requests

    session = requests.Session()
    session.headers.update({"Host": "127.0.0.1:8000"})
    for _ in range(POOL_SIZE):
        account = Account.create()
        token = _sign_in(session, account)
        if token:
            _SESSIONS.append(token)
            _PLAYERS.append(account.address.lower())
    print(f"[load] prepared {len(_SESSIONS)} authenticated sessions")
    _require_sessions()


def _require_sessions() -> None:
    """Abort instead of "passing" while every task returns early.

    Measured failure mode: a misconfigured host made the prep listener throw, the
    run continued with zero sessions, and the summary showed a healthy request
    rate for /api/health alone — a green-looking result for a test that never
    touched the path it exists to measure.
    """
    if not _SESSIONS:
        raise RuntimeError(
            "[load] no authenticated sessions were prepared — refusing to run. "
            "Check PULSAR_LOAD_HOST / --host and PULSAR_LOAD_TOKENS."
        )


@events.test_stop.add_listener
def _report_expected(environment, **_kwargs) -> None:
    """Say out loud how many joins were answered with 409/429 (audit H-21).

    Without this line those answers vanish into "0 failures", which is how a
    100 %-422 endpoint looked healthy for a month.
    """
    if _EXPECTED_NON_200:
        print(
            "[load] joins answered non-200 but expected: "
            + ", ".join(f"{code}={count}" for code, count in sorted(_EXPECTED_NON_200.items()))
        )


class PollingPlayer(HttpUser):
    """
    A player sitting in the lobby: polls the queue state, the challenge list and
    their own stats. That is the traffic shape the server sees at rest — the
    plan's "1000 concurrent pollers on /api/queue".
    """

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        if not _SESSIONS:
            self.token, self.address = "", ""
        else:
            i = random.randrange(len(_SESSIONS))
            self.token, self.address = _SESSIONS[i], _PLAYERS[i]
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    @task(6)
    def join_queue(self) -> None:
        """The plan's "1000 concurrent pollers on /api/queue" — the JOIN path.

        POST, not GET: this is the endpoint a player hits to enter the queue.

        Audit H-21 (2026-10-23): this posted the stake ALONE while the endpoint
        requires an rtt (the ping cap is an entry gate, audit H-03). Every join
        answered **422** before touching the store, and the old rule — "only 5xx
        is a failure" — recorded all of them as SUCCESS. That is why the join
        row in docs/LOAD-REPORT.md looked both fast and flawless: it was timing
        a request-validation error.

        A 4xx that means "your payload is wrong" is never a success. 409/429 are
        expected answers under load (already queued / rate limited) and are
        reported separately so they cannot hide inside the failure count either.
        """
        if not self.token:
            return
        with self.client.post(
            "/api/queue",
            json={"stake": 1, "rttMs": random.randint(20, 80)},
            name="/api/queue (join)",
            catch_response=True,
        ) as res:
            if res.status_code == 200:
                res.success()
            elif res.status_code in (409, 429):
                # Expected: a player already queued, or the per-address limiter.
                # Reported, not failed — but never counted as a join either.
                res.success()
                _EXPECTED_NON_200[res.status_code] += 1
            else:
                res.failure(f"unexpected {res.status_code}: {res.text[:120]}")

    @task(3)
    def poll_challenges(self) -> None:
        if not self.token:
            return
        self.client.get("/api/challenges", name="/api/challenges")

    @task(2)
    def poll_stats(self) -> None:
        if not self.address:
            return
        self.client.get(f"/api/player/{self.address}/stats", name="/api/player/{addr}/stats")

    @task(1)
    def health(self) -> None:
        self.client.get("/api/health", name="/api/health")
