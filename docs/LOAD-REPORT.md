# Load report (plan item 10.3)

Measured 2026-10-13 against the local stack: FastAPI + uvicorn (single worker),
the Firestore emulator, anvil, and 50–1000 authenticated SIWE sessions driven by
Locust (`load/locustfile.py`).

Every endpoint in the hot path is authenticated, so the profile signs a pool of
real players in once and then drives the poll paths the game uses.

## The headline: the application is not the bottleneck

| Store | p50 | p95 | max | `POST /api/queue` |
|---|---|---|---|---|
| **Firestore emulator** | 240 ms | **10 000 ms** | 17 s | **100 % failure** |
| **In-memory** | **4 ms** | **68 ms** | 70 ms | 0 % failure |

Same code, same load, one variable changed. The 10-second latencies are the
**emulator**, not the application: the app's own request handling is ~4 ms at p50
and ~68 ms at p95 with 50 concurrent users.

This matters for interpreting the numbers: **the emulator is a single Java
process with no production tuning**, so these figures are a lower bound on what
a real Firestore deployment would do — and an upper bound on what the
application code costs. A production load test must run against real Firestore;
that is a phase-11 item.

## Sequential latency (no contention)

| Endpoint | Latency |
|---|---|
| `GET /api/health` | 3 ms |
| `GET /api/challenges` | 11 ms |
| `POST /api/queue` (join) | 158 ms |

The join path is the expensive one — it writes a queue document and reads the
escrow deposit gate over RPC.

## Firestore reads per match — MEASURED

**35 reads per match** (was 47 before the optimization below), against the plan's
target of **< 20**. Measured from `/api/metrics` → `firestore.readsPerMatch`
after a full ranked duel driven through the API
(`tests/integration/test_ranked_flow_e2e.py`).

The metric is now **attributed per route**, because a single total says a match
costs 47 reads but not which endpoints spend them — a number you cannot act on:

```
    13  /api/round/result        (before the fix)
    12  /api/round/commit
    12  /api/round/target
     6  /api/match/{match_id}
     4  /api/match/{match_id}/settle
```

**37 of 47 (79%) were the round endpoints, at 2 reads per call.** Each round
action read the match twice: once in the deposit gate and once inside
`store.update`'s transaction. The gate runs outside the transaction deliberately
(it is blocking network I/O), but the read was redundant — it only needs `stake`
and `players`, which are immutable after activation. `store.identity` serves
those from the in-process mirror and falls back to a real read on a miss, so it
can only ever be a cache hit. **47 → 35.**

**Still above target.** The remaining cost is the round endpoints' own
transactional read — which is what makes concurrent replicas safe — plus
`/api/match/{id}`, which the *client* polls during a match and which this metric
does not yet include. The real production number is therefore higher than 35.

## Cost estimate at scale

Derived from the measured 35 reads per match. Firestore list prices
(us-central1): **$0.031 per 100 000 document reads**, **$0.108 per 100 000
writes**. A match performs roughly 9 writes (one per round action plus settle).

| Matches/day | Reads | Read cost | Write cost | Total/day |
|---|---|---|---|---|
| 1 000 | 35 000 | $0.011 | $0.010 | **$0.02** |
| 100 000 | 3 500 000 | $1.09 | $0.97 | **$2.06** |
| 1 000 000 | 35 000 000 | $10.85 | $9.72 | **$20.57** |

**The database is not the cost driver.** Even at a million matches a day the
Firestore bill is ~$21. The costs that matter are the RPC calls the deposit gate
makes per round (one `eth_call` per round action, plus the settlement
transaction), the oracle's signing, and the Polygon gas for settlement — all of
which are chain costs, not database costs.

**Caveat, stated rather than buried:** these are list prices against the
*measured* read count, which excludes the client's polling. At a 1.5-second poll
interval a three-minute match adds ~120 reads — more than tripling the figure.
Reducing that polling is the next lever, and it is worth more than any further
database tuning.

## 1000 concurrent pollers — MEASURED, and it found a bug

Run: `.venv/bin/locust -f load/locustfile.py --headless -u 1000 -r 100 -t 45s`.

The first run returned **157 of 157 `POST /api/queue` requests as HTTP 500**:

```
ValueError: Failed to commit transaction in 5 attempts.
```

Under contention the Firestore transaction exhausts its retries and raises. That
escaped as a **500**, which tells a client "this is broken, do not retry" — when
the truth was the opposite: the request was fine and the store was busy.

**Fixed:** store contention is now a **retryable 503** with `Retry-After`, handled
once globally rather than per route (the first fix covered only `/api/queue`, and
the same failure kept surfacing on `/api/challenges` and
`/api/player/{addr}/stats`). A `store.contention503` counter exposes it, so
capacity and breakage are never confused.

**After the fix, under the same load:**

| | Before | After |
|---|---|---|
| `/api/queue` 500s | 157 | **0** |
| `/api/queue` 503s | 0 | 86 |
| 500s on **any** route | 13+ | **0** |

Latencies remain in the tens of seconds at 1000 concurrent users — that is the
**emulator**, as the headline table shows, not the application.

## What this run already found

Two real defects, neither of which any unit test could see:

1. **The API was unreachable in the documented split deployment.**
   `ALLOWED_DOMAIN` (the frontend's SIWE host) was reused as the `TrustedHost`
   allowlist, so an API on its own hostname rejected every request with 403.
   Split into `ALLOWED_HOSTS`.
2. **`/api/health` returned 500 when `ORACLE_PRIVATE_KEY` was missing.** A
   liveness probe that fails instead of reporting turns a misconfiguration into
   a crash loop. It now answers with `oracleConfigured: false`.
