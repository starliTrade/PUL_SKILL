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
| "RPC failure renders a blank page" | instrumented probe → **responsive page, 0 mutations, "RPC endpoint unreachable" + Dismiss** | **Wrong.** The modal covers the page, so a click behind it hangs and the test times out. I read the timeout as a blank screen. See below. |

## The "open item" was a misdiagnosis — corrected here

I recorded that with an unreachable node (`failRpc`) the app **renders a blank page**,
and left the item open on that basis. **That was wrong.**

Re-measured with a probe that instruments the page instead of reading a timeout:

- the page is **responsive** (`1 + 1` evaluates fine);
- **0 DOM mutations in 2 seconds** — it is not re-rendering or looping;
- the body text contains **"RPC endpoint unreachable"** with a **Dismiss** action.

The app **does** report the failure. What actually happened: the wallet modal
**covers the page**, so a click on anything behind it hangs on Playwright's
stability check — and the run died on a timeout, which I read as a blank screen.

`e2e/ranked-failure-modes.spec.ts` now asserts the real behaviour: the message is
shown, Dismiss leaves a usable page, and no duel starts. **All three failure-mode
tests pass.**

**Phase 10 is therefore zero open items** — not one.

The lesson is the one this phase keeps teaching, and this time I was the one who
needed it: **a timeout is not a diagnosis.** A hanging action and a blank screen
look identical from a test failure and are completely different bugs.

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
