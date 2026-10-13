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

import os
import random

from eth_account import Account
from eth_account.messages import encode_defunct
from locust import HttpUser, between, events, task

HOST = os.environ.get("PULSAR_LOAD_HOST", "http://127.0.0.1:8000")
POOL_SIZE = int(os.environ.get("PULSAR_LOAD_POOL", "1200"))

# One funded-looking address per virtual user. These are throwaway keys: the
# load test never moves money, it only needs a valid SIWE statement.
_SESSIONS: list[str] = []
_ACCOUNTS: list[Account] = []


def _sign_in(client, account: Account) -> str | None:
    address = account.address.lower()
    nonce = client.post(f"{HOST}/api/auth/nonce", json={"address": address})
    if nonce.status_code != 200:
        return None
    message = nonce.json()["message"]
    signature = account.sign_message(encode_defunct(text=message)).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    verify = client.post(
        f"{HOST}/api/auth/verify", json={"message": message, "signature": signature}
    )
    if verify.status_code != 200:
        return None
    return verify.json()["token"]


@events.test_start.add_listener
def _prepare_sessions(environment, **_kwargs) -> None:
    """Sign POOL_SIZE players in once, before the load starts."""
    import requests

    session = requests.Session()
    session.headers.update({"Host": "127.0.0.1:8000"})
    for _ in range(POOL_SIZE):
        account = Account.create()
        token = _sign_in(session, account)
        if token:
            _ACCOUNTS.append(account)
            _SESSIONS.append(token)
    print(f"[load] prepared {len(_SESSIONS)} authenticated sessions")


class PollingPlayer(HttpUser):
    """
    A player sitting in the lobby: polls the queue state, the challenge list and
    their own stats. That is the traffic shape the server sees at rest — the
    plan's "1000 concurrent pollers on /api/queue".
    """

    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        self.token = random.choice(_SESSIONS) if _SESSIONS else ""
        self.address = _ACCOUNTS[_SESSIONS.index(self.token)].address.lower() if self.token else ""
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    @task(6)
    def join_queue(self) -> None:
        """The plan's "1000 concurrent pollers on /api/queue" — the JOIN path.

        POST, not GET: this is the endpoint a player hits to enter the queue.
        A 409/429 is a normal answer under load (already queued / rate limited),
        so only 5xx counts as a failure.
        """
        if not self.token:
            return
        with self.client.post(
            "/api/queue",
            json={"stake": 1},
            name="/api/queue (join)",
            catch_response=True,
        ) as res:
            if res.status_code >= 500:
                res.failure(f"{res.status_code}")
            else:
                res.success()

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
