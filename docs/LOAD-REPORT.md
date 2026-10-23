# Load report (plan item 10.3)

**Audit L-06.** The previous version of this file presented numbers without the
conditions that make them meaningful, and one heading claimed far more than the
measurement behind it. A latency has no meaning without the machine, the store
and the number of virtual users, so every table below now carries all three, and
the sections are split into what was measured *today, in this repository* and
what is a historical result that **cannot be reproduced in this sandbox**.

## What this document does and does not say

| | |
|---|---|
| **It does say** | how much CPU the API's own handlers cost per request when the store is memory (`p50 ≈ 1 ms`); that the API returned **zero 5xx** in every run; that a contended store must answer 503, not 500; the Firestore read cost of a match (35) and its list-price consequences |
| **It does not say** | how many players a production deployment supports. No run here touched real Firestore, a real network, TLS, a load balancer, or more than one API process |
| **Why not** | the only stores available here are an in-memory dict and (historically) a single-process Firestore emulator, and the load generator shares the same two vCPUs as the server. A capacity number from that setup would be a number about this laptop |

The honest status of "capacity": **unknown, and it needs one afternoon on the
target host** (see *How to measure it for real* at the end). Nothing in this
document should be quoted as a production capacity figure.

---

## 1. Measured 2026-10-23 — memory store, 2 vCPU, generator on the same box

Conditions for all three runs, stated once:

* machine: **2 vCPU**, 2 GB-class sandbox; `python -m uvicorn main:app` **one
  worker process**, memory match store (`PULSAR_MATCH_STORE=memory`);
* load: `locust 2.47.0 -f load/locustfile.py --headless`, 1100 pre-minted
  sessions from `scripts/load_sessions.py`, wait time 0.5–1.5 s;
* the **generator runs on the same two cores as the server**, so once CPU
  saturates, every latency in the table includes the client's own scheduling.

| Virtual users | Requests | Failures | Throughput | Server-side p50 | Server-side p95 |
|---:|---:|---:|---:|---:|---:|
| 200 | 3 144 | **0** | 157 req/s | **≈ 1 ms** | **≤ 35 ms** |
| 1000 (run A) | 16 239 | **0** | 359 req/s | 1.1 s | 2.6 s |
| 1000 (run B) | 10 356 | **0** | 343 req/s | 0.83 s | 2.5 s |

Per-route, **as the server measured itself** (`/api/metrics`, which times the
handler between request start and response write):

| Route (memory store) | 200 users p50 / p95 | 1000 users p50 / p95 |
|---|---|---|
| `POST /api/queue` (join) | 0.9 ms / 2.9 ms | 387 ms / 486 ms |
| `GET /api/challenges` | 1.0 ms / 29.6 ms | 1 863 ms / 2 108 ms |
| `GET /api/player/{addr}/stats` | 1.1 ms / 25.9 ms | 1 884 ms / 2 181 ms |
| `GET /api/health` | 1.0 ms / 34.6 ms | 1 747 ms / 2 186 ms |
| `POST /api/eligibility/confirm` | 1.2 ms / 1.5 ms | 1.2 ms / 1.4 ms |

**How to read the 1000-user column.** `GET /api/health` touches nothing — no
store, no disk, no network — and it still reports **1.7 s at p50**. A handler
that does no work cannot take 1.7 s; the time is spent waiting to be *run*. That
is the signature of a saturated host (1000 locust users and uvicorn sharing two
cores), not of application cost. The 200-user column is the one that measures
code: **≈ 1 ms p50, tens of milliseconds at p95**, with the whole request mix
still at 157 req/s.

The 1000-user run is therefore a **stability** result, not a latency result: at
359 req/s and ~16 000 requests, **zero** requests failed and the metrics layer
reported `routesDropped: 0, complete: true` — the route table did not overflow
and nothing was silently dropped (see audit L-08).

### One defect this run found (2026-10-23)

The load profile signed players in and then pounded `/api/queue`, which sits
behind the eligibility attestation (G2). Every join would have answered **403**,
so the earlier "queue" numbers were measuring the gate, not the queue. The
profile now posts `/api/eligibility/confirm` once per player, the way the client
does. It also refuses to start with zero sessions:

> A misconfigured host made the session-prep listener throw, the run continued
> with **zero** authenticated sessions, every task returned early, and the
> summary still showed a healthy request rate — for `/api/health` alone. Green
> output from a test that never touched the path it exists to measure is the
> worst kind of result.

---

## 2. Historical: 2026-10-13, Firestore emulator, 50 concurrent users

Kept for the two findings it produced, **not** as a capacity statement. The
emulator is a single Java process with no production tuning; it needs `java` and
the Firebase CLI, neither of which is present in the sandbox that wrote this
version, so **these numbers cannot be re-measured here**.

| Store | p50 | p95 | max | `POST /api/queue` |
|---|---|---|---|---|
| Firestore emulator | 240 ms | **10 000 ms** | 17 s | **100 % failure** |
| In-memory | 4 ms | 68 ms | 70 ms | 0 % failure |

Same code, same load, one variable changed: the ten-second latencies were the
**emulator**. Read that sentence narrowly — it says the emulator is slow at 50
concurrent users, and that the application's own cost with a memory store is a
few milliseconds. It does **not** say real Firestore behaves like either.

The first run also returned **157 of 157 `POST /api/queue` requests as HTTP
500**, `ValueError: Failed to commit transaction in 5 attempts`. That is a real
finding, independent of the store: under contention the Firestore transaction
exhausts its retries, and a 500 tells a client "this is broken, do not retry"
when the truth is the opposite.

**Fixed:** store contention is a **retryable 503 with `Retry-After`**, handled
once globally rather than per route (the first fix covered only `/api/queue`, and
the same failure kept surfacing on `/api/challenges` and
`/api/player/{addr}/stats`). A `store.contention503` counter exposes it, so
capacity and breakage are never confused.

| | Before | After |
|---|---|---|
| `/api/queue` 500s | 157 | **0** |
| `/api/queue` 503s | 0 | 86 |
| 500s on **any** route | 13+ | **0** |

### Sequential latency (2026-10-13, no contention, emulator + anvil)

| Endpoint | Latency |
|---|---|
| `GET /api/health` | 3 ms |
| `GET /api/challenges` | 11 ms |
| `POST /api/queue` (join) | 158 ms |

The join path is the expensive one — it writes a queue document and reads the
escrow deposit gate over RPC.

---

## 3. Firestore reads per match — 35, and the client's polling is not counted

Measured from `/api/metrics` → `firestore.readsPerMatch` after a full ranked duel
driven through the API (`tests/integration/test_ranked_flow_e2e.py`). **35 reads
per match**, down from 47, against the plan's target of **< 20**.

Attribution matters more than the total — a single number says a match costs 47
reads but not which endpoints spend them:

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

### Cost estimate at scale (arithmetic on the measured 35, not a projection)

Firestore list prices, us-central1: **$0.031 per 100 000 document reads**,
**$0.108 per 100 000 writes**; a match performs roughly 9 writes.

| Matches/day | Reads | Read cost | Write cost | Total/day |
|---|---|---|---|---|
| 1 000 | 35 000 | $0.011 | $0.010 | **$0.02** |
| 100 000 | 3 500 000 | $1.09 | $0.97 | **$2.06** |
| 1 000 000 | 35 000 000 | $10.85 | $9.72 | **$20.57** |

**The database is not the cost driver.** Even at a million matches a day the
Firestore bill is ~$21. The costs that matter are the RPC calls the deposit gate
makes per round, the oracle's signing, and the Polygon gas for settlement.

**Caveat, stated rather than buried:** these are list prices against the
*measured* read count, which excludes the client's polling. At a 1.5-second poll
interval a three-minute match adds ~120 reads — more than tripling the figure.
Reducing that polling is worth more than any further database tuning.

---

## 4. Other defects the load work found

1. **The API was unreachable in the documented split deployment.**
   `ALLOWED_DOMAIN` (the frontend's SIWE host) was reused as the `TrustedHost`
   allowlist, so an API on its own hostname rejected every request with 403.
   Split into `ALLOWED_HOSTS`.
2. **`/api/health` returned 500 when `ORACLE_PRIVATE_KEY` was missing.** A
   liveness probe that fails instead of reporting turns a misconfiguration into
   a crash loop. It now answers with `oracleConfigured: false`.
3. **`/api/health` blocked on Firestore** (audit L-04): measured >120 s with the
   database unreachable, because the review-queue read had no deadline that
   applied. It now serves a cached value refreshed by one background thread and
   reports `readStatus`/`readError`. Measured after: **3 ms**.

---

## How to measure it for real

The point of a production load test is to find the knee of the curve on the
machine you will actually deploy to. That run has not happened, and nothing above
substitutes for it.

1. **A host with the production shape** — at least 2 vCPU for the API, separate
   from the generator. Two machines is enough.
2. **Real Firestore**, not the emulator: service-account credentials, the
   composite indexes from `firestore.indexes.json`, and a database with a
   realistic amount of data in it (an empty database answers faster than a
   populated one).
3. **Sessions**: `scripts/load_sessions.py` needs `ORACLE_SIGNING_SECRET` from
   the target. Alternatively run the SIWE path, but `/api/auth/verify` allows 30
   per minute per IP — for 1000 players either raise it for the test window or
   mint tokens.
4. **Ramp**: `-u 1000 -r 25 -t 10m`. A 100/s ramp reaches 1000 in ten seconds
   and measures the ramp, not the steady state.
5. **Read the server's own numbers**, `curl /api/metrics`, and compare them with
   what the client reports. If they disagree by an order of magnitude, the
   generator is the bottleneck (that is exactly what the 1000-user run above
   shows).
6. **Watch**: `requestsObserved` vs `routesDropped` (a non-zero drop means the
   route table overflowed), `rateLimit.fallbacks` (a dead distributed limiter),
   `store.contention503`, and `ledger.outbox` (queued-but-unwritten settlements).
