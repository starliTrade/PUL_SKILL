# The `nightly` profile — run, recorded, and hardened (2026-10-23 → 2026-10-24)

> **2026-10-24:** §4 is closed. The reverts are now classified at the source, a
> revert fails the campaign, a negative control proves the recorder can fail, and
> the profile runs on a schedule in CI (§5). Sections 1–3 are kept exactly as the
> 2026-10-23 run reported them — rewriting a measurement after the code changes
> would be a falsified record, and the point of this file is that the numbers can
> be traced.

`contracts/foundry.toml` has carried a `nightly` profile since CT14. Until today
it had **never been executed**: every gate in `scripts/verify.sh` and the CI
workflow uses `default` or `ci`, so the deepest configuration in the repository
was a number in a file. This is the record of running it, what it proves, and —
more useful — **where the pass is weaker than it looks**.

---

## 1. The run

```
FOUNDRY_PROFILE=nightly forge test
```

| | value |
|---|---|
| suites | 9 |
| tests | **104 passed, 0 failed, 0 skipped** |
| wall clock | **1264.52 s** (21 min 4.5 s) |
| CPU time | 2005.88 s |
| forge | 1.7.1 · solc 0.8.20 · evm `paris` · optimizer 200 |
| invariant suite | 1264.51 s of the total — the fuzzer is the whole cost |

For comparison, the same command on `default`:

| profile | fuzz runs | invariant runs × depth | wall clock |
|---|---:|---:|---:|
| `default` | 256 | 64 × 100 = 6,400 calls | 5.6 s |
| `ci` | 1,024 | 256 × 200 = 51,200 calls | ~40 s |
| **`nightly`** | **10,000** | **1,024 × 500 = 512,000 calls** | **1264.5 s** |

The nightly profile therefore ran **80× the state transitions of `ci`** and
**~48× the fuzz cases**.

---

## 2. Fuzz: 50,000 cases, all pass

`FOUNDRY_PROFILE=nightly forge test --match-path test/PulsarEscrow.t.sol`, 4.52 s:

| test | runs | result |
|---|---:|---|
| `testFuzz_FeeMathIsExact(uint256)` | 10,000 | PASS |
| `testFuzz_OutsiderWinnerImpossible(uint256)` | 10,000 | PASS |
| `testFuzz_SelfJoinAndGhostJoinRevert(uint256,uint8)` | 10,000 | PASS |
| `testFuzz_SettledIsTerminal(uint8,uint256)` | 10,000 | PASS |
| `testFuzz_StakeGateAndPoolAccounting(uint96)` | 10,000 | PASS |

**50,000 generated inputs, zero counterexamples.** The fee arithmetic, the
"seller can never be the winner" rule, the self/ghost-join rejection, settlement
finality and the stake gate all held across the full 10,000-run budget, not just
the 256 the default profile uses.

---

## 3. Invariants: 3,072,000 calls, all pass

Six properties, each run 1,024 times to depth 500 (512,000 calls per property):

| property | what it would catch |
|---|---|
| `invariant_balance_covers_every_obligation` | money created or leaked: the token balance falls below live stakes + deferred payouts |
| `invariant_total_locked_equals_obligations` | the `totalLocked` counter drifting from the obligations it claims to track |
| `invariant_residual_is_zero_without_stray_transfers` | dust accumulating in the contract outside the accounting |
| `invariant_settled_and_refunded_are_terminal` | a match moving out of Settled/Refunded — double payout |
| `invariant_counters_match_the_actions_taken` | the handler's tally disagreeing with on-chain state |
| `invariant_deferred_payouts_are_backed` | a deferred payout that the balance cannot honour |

Total: **3,072,000 randomized calls** across the five handler actions
(`create`, `join`, `settle`, `refund`, `withdraw`), 0 failures.

---

## 4. Where this pass was weaker than the numbers suggested — closed 2026-10-24

### 4.1 The diagnosis (2026-10-23)

Foundry reports a revert table per property. From the nightly run:

| action | calls | reverts | rate |
|---|---:|---:|---:|
| `create` | 102,440 | 0 | 0 % |
| `join` | 102,366 | **28,856** | **28.2 %** |
| `settle` | 102,711 | 2,315 | 2.3 % |
| `refund` | 102,363 | 0 | 0 % |
| `withdraw` | 102,120 | 0 | 0 % |

`fail_on_revert = false` is set on every invariant profile, which meant **those
reverts did not fail the run and were not classified**. Two consequences:

1. **A revert could not distinguish "expected" from "bug".** If `join` started
   reverting for a reason nobody predicted — a new require, a broken transfer —
   the campaign would still be green, because the properties only inspect state
   *after successful calls*.
2. **The effective call mix was smaller than 512,000.** 28 % of joins were spent
   on a path that cannot change state.

The cause was identified from the code: the handler's `refund` action does
`vm.warp(block.timestamp + MATCH_TIMEOUT + REFUND_GRACE + 1)`, which advances time
for **every** match, so every `Created` match older than the timeout then failed
`joinDuel`'s `require(block.timestamp < duel.createdAt + MATCH_TIMEOUT, "Match
expired")`. The `settle` reverts were the same warp interacting with the
settlement deadline: the handler always minted `now + 600`, which after the warp
was routinely past `createdAt + MATCH_TIMEOUT`, so the contract answered
`"deadline exceeds horizon"` — correctly. Both were **the handler's bug, not the
contract's**, and both were invisible.

### 4.2 The fix

| # | change | file |
|---|---|---|
| 1 | `join` skips a duel the contract will refuse as expired — the same rule, `block.timestamp >= createdAtOf(id) + MATCH_TIMEOUT()` — and records `skippedExpiredJoins` | `contracts/test/PulsarEscrowInvariants.t.sol` |
| 2 | `settle` mirrors `api/oracle.py`: `deadline = min(now + 600, clockOrigin + MATCH_TIMEOUT)`, and skips when `now > horizon` (`skippedPastHorizonSettles`) | same |
| 3 | every action (`join`, `settle`, `refund`, `withdraw`) is wrapped in `try/catch`; any revert is recorded as `revertCount` + the first reason and the call it came from (`firstRevert`, `firstRevertIn`) | same |
| 4 | `invariant_no_unexpected_reverts()` fails the campaign unless `revertCount == 0` | same |
| 5 | `EscrowHandlerRevertControl` — a **negative control**: a handler built with the wrong oracle key provokes a real `settle` revert, and a test asserts the recorder captures it. Without this, a recorder that never fired would look exactly like a clean campaign | same |

There is **no allowlist**. The previous plan was to permit `Error("Match expired")`
and the deadline error; the rewrite removes those calls at the source instead, so
the expected revert set is empty. That is a stronger property than an allowlist:
an allowlist would have to be maintained, and a bug that produced a *permitted*
reason would still pass.

### 4.3 The measured result

`FOUNDRY_PROFILE=ci forge test --match-path test/PulsarEscrowInvariants.t.sol`:

```
| Contract      | Selector | Calls | Reverts | Discards |
| EscrowHandler | create   | 10214 | 0 | 0 |
| EscrowHandler | join     | 10144 | 0 | 0 |
| EscrowHandler | refund   | 10109 | 0 | 0 |
| EscrowHandler | settle   | 10219 | 0 | 0 |
| EscrowHandler | withdraw | 10514 | 0 | 0 |
```

Every selector now has a **zero** revert column, not a 28 % one. The suite is
104 → 107 tests / 9 → 10 suites: seven properties instead of six, plus the two
control tests.

The deep profile was then re-run to completion (2026-10-24, same machine):

```
Suite result: ok. 7 passed; 0 failed; 0 skipped; finished in 1089.57s
| EscrowHandler | create   | 102603 | 0 | 0 |
| EscrowHandler | join     | 102359 | 0 | 0 |
| EscrowHandler | refund   | 102369 | 0 | 0 |
| EscrowHandler | settle   | 102546 | 0 | 0 |
| EscrowHandler | withdraw |  ...   | 0 | 0 |
```

**3,584,000 randomized calls, all of them accepted by the contract, zero
reverts** — and therefore zero calls whose outcome was thrown away. The
end-to-end command took 1760 s (29 min) on a 2-vCPU box with a cold compile; the
campaign itself is 1089.6 s (18 min 10 s), *faster than the six-property run it
replaces* despite doing more work. That is the payoff of §4.4.

One more thing the table shows: the two view helpers added for the fast path
(`obligationsFromEscrow`, `snapshotOf`) do **not** appear as fuzzed selectors.
They are `view`, and Foundry only fuzzes state-changing functions — which is also
why the attempt to add a public `forceMatchId` helper had to be reverted (it
became a fuzz target and broke three properties).

### 4.4 What the fix cost, and why that is part of the story

A campaign that stops discarding calls does *more* work per call, and the first
version of this rewrite made the deep run unusable:

| mistake | symptom | fix |
|---|---|---|
| `assertEq(x, 0, string.concat(...))` — Foundry evaluates the message on every check | the nightly run had not finished after **43 min** (it used to take 21) | `if (reverts != 0) revert(...)`: no allocation on the happy path |
| the check re-read the handler four times per tracked match, and it runs after **every** call — O(matches) per check, O(depth²) per sequence | `ci` 115 s; one nightly property **923 s** | one `escrow.matches(id)` read per match (`obligationsFromEscrow`, `snapshotOf`): `ci` **68 s** |
| `matchIds` grew without bound | the check's cost grew with the whole campaign | `MAX_TRACKED_MATCHES = 64`; what the campaign hunts is a bad *sequence* over live duels, not a thousand duels |

Net effect on the deep run: **> 43 min (killed) → 18 min 10 s (completed, seven
properties)**, with the budgets untouched. The lesson is worth recording: a
"stronger" campaign that nobody can afford to run is a weaker one, and the fix
belongs in the harness, never in the profile.

---

## 5. It now runs in CI, on a schedule

Until 2026-10-24 the `nightly` profile was selected by **no** workflow, script or
gate: the deepest configuration in the repository was a number in a file. The CI
workflow's `contracts` job uses `FOUNDRY_PROFILE=ci`.

`.github/workflows/ci.yml` now has a `nightly-contracts` job:

| | value |
|---|---|
| trigger | `schedule: 0 3 * * *` (03:00 UTC) and `workflow_dispatch` |
| not on | `push` / `pull_request` — it is the slow run, and a PR gate that takes an hour is a gate people disable |
| profile | `FOUNDRY_PROFILE=nightly` — fuzz 10,000; invariant 1,024 × 500 |
| toolchain | Foundry `v1.8.5`, forge-std `v1.9.7`, OpenZeppelin `v5.7.0` — the same pins as the `contracts` job |
| guards | reads `foundry.toml` back and asserts the **deep** budgets are in force, then summarises the JSON of the run that just happened (`>= 100` tests, 0 failed, failing names printed). Both guards exist because the original `contracts` job shipped green while running zero tests (CI-1): a default-budget run inside a "nightly" job would look identical |
| timeout | 90 min, against a **measured 29 min** end-to-end (2 vCPU, cold compile) |
| cost | one run of the campaign, not two: the first draft ran `forge test -vvv` and then `forge test --json`, which on this profile is the whole thing twice |

A red nightly run is a real finding. It is not a blocker for merging; it is the
answer to "does any of this still hold when the fuzzer gets 80× the budget".

## 6. What this proves, and what it does not

**Proves:** the escrow's seven financial invariants hold across 3.58 million
randomized calls (§4.3), every one of those calls is one the contract accepted
(§4.2), at 16× the depth CI uses, and its five fuzz properties hold
across 50,000 generated inputs. Nothing in the contract leaks, double-pays,
resurrects a terminal match, or lets a non-participant win *within the action
space this handler reaches*.

**Does not prove:** that the handler reaches every state the contract allows
(§4), that gas is acceptable at mainnet scale (not measured), that the token
behaves like USDT on Amoy (mocks only, plus the fee-on-transfer and blacklist
variants in `tests/fixtures`), or anything about the server. It also does not
replace an external audit: a fuzzer that cannot express an attack will not find
it, and this one does not model a malicious *oracle signature* beyond the
forged/deadline/replay cases already in the unit suite.
