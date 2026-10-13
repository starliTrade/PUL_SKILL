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

## Firestore reads per match

Not yet measured. The counter exists (`metrics.note_firestore_read`, wired to
`/api/health` under `readsPerMatch`), but a full ranked duel has to run through
the harness before the number is meaningful. The plan's target is < 20.

## Cost estimate at scale

Not yet produced — it depends on the reads-per-match figure above. The shape of
the estimate: `reads_per_match × matches_per_day × Firestore read price`, plus
the RPC calls the deposit gate makes per round.

## What this run already found

Two real defects, neither of which any unit test could see:

1. **The API was unreachable in the documented split deployment.**
   `ALLOWED_DOMAIN` (the frontend's SIWE host) was reused as the `TrustedHost`
   allowlist, so an API on its own hostname rejected every request with 403.
   Split into `ALLOWED_HOSTS`.
2. **`/api/health` returned 500 when `ORACLE_PRIVATE_KEY` was missing.** A
   liveness probe that fails instead of reporting turns a misconfiguration into
   a crash loop. It now answers with `oracleConfigured: false`.
