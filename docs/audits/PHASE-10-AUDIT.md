# Phase 10 — independent audit

Written after the phase was declared complete. Every number below was **re-measured
on the merged `main`**, not copied from the report that claimed it. Where a claim
did not survive re-measurement, it is called out as a correction.

`main = a7ac3ba` · `bun run verify` → **16 gates, 0 fail, 0 skip**

## Claims that survived re-measurement

| Claim | Re-measured | Verdict |
|---|---|---|
| Chaos suite 19/19 | `chaos_suite.py` → **19 passed, 0 failed** | ✅ holds |
| Firestore reads per match = 35 | `/api/metrics` after a real match → **reads=35, settled=1, perMatch=35.0** | ✅ holds |
| Verify: 16 gates, 0 fail, 0 skip | re-ran `verify.sh` → **16/0/0** | ✅ holds |
| Ranked duel runs end to end | 3 rounds commit/target/result 200 → settle 200 both sides → prize claimed on-chain | ✅ holds |
| Transaction rejection is honest | `ranked-failure-modes.spec.ts` → **passed** | ✅ holds |
| Wrong chain (H15) is honest | same spec → **passed** | ✅ holds |

## Claims that did NOT survive — corrections

| Claim | Re-measured | Correction |
|---|---|---|
| "coverage 84%" | `coverage report` → **83%** (2492 stmts, 434 missed) | The reports said 84%. The real number is **83%**. The gate (`fail_under = 79`) still passes with 4 points of headroom, so nothing is broken — but the figure I published was wrong by a point. |
| "26 E2E" | `playwright test --list` → **32** | The "26" counted only the default project; the suite also runs mobile and the opt-in specs. The smaller number understated the suite. |

## The one open item in the phase

**RPC failure at every step** — with `failRpc` the app renders a **blank page**. Not a
message, not an error shell, not a way forward: the connect button never appears, so
no test can reach an assertion. Measured, not assumed — the page snapshot at the
timeout is a single empty element.

This is why there is no test for it rather than a test that cannot run. A test that
hangs in setup and dies on a timeout is a **worse** signal than an honest gap: it
looks like coverage while asserting nothing. The fix belongs in the app — render the
same error shell it already renders for a refused transaction — and until then the
item stays open in the plan.

## What the phase actually delivered

The phase's value was not the features; it was the **false greens it killed**. Nine
of them, each caught by reading evidence rather than trusting a passing run:

1. The API returned **403 on every request** in the split topology its own runbook describes.
2. `/api/health` returned **500** when the oracle key was absent → crash loop.
3. `chain_reachable()` returned **true** with a dead RPC.
4. `ledger_available()` was a config check exposed as a reachability check.
5. The app could not connect to the **local** chain at all (mainnet/Amoy only).
6. Real-money mode was locked to two of four addresses.
7. The faucet called `faucet`, not `mint` — a "successful" transaction that moved nothing.
8. The app reported **wallet** errors as "server error".
9. Two false greens in my own tests: a 401 that looked like a rejection, and a spec that never clicked the verify node.

Item 9 is the one worth keeping. A test that passes for the wrong reason is worse
than a test that fails, because it is the one nobody looks at.

## Method note

Every "measured" figure in this phase came from the running system — anvil
transactions, `/api/metrics`, the Firestore emulator, the chaos suite — not from
reading code and reasoning about what it should do. Three of the nine bugs above
were invisible to code reading and only appeared when the thing was run.
