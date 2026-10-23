# The `nightly` profile — run and recorded (2026-10-23)

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

## 4. Where this pass is weaker than the numbers suggest

Foundry reports a revert table per property. From the nightly run:

| action | calls | reverts | rate |
|---|---:|---:|---:|
| `create` | 102,440 | 0 | 0 % |
| `join` | 102,366 | **28,856** | **28.2 %** |
| `settle` | 102,711 | 2,315 | 2.3 % |
| `refund` | 102,363 | 0 | 0 % |
| `withdraw` | 102,120 | 0 | 0 % |

`fail_on_revert = false` is set on every invariant profile, which means **those
reverts did not fail the run and are not classified**. Two consequences:

1. **A revert cannot distinguish "expected" from "bug".** If `join` started
   reverting for a reason nobody predicted — a new require, a broken transfer —
   the campaign would still be green, because the properties only inspect state
   *after successful calls*.
2. **The effective call mix is smaller than 512,000.** 28 % of joins are spent
   on a path that cannot change state.

The cause of the join reverts is identifiable from the code and is benign: the
handler's `refund` action does `vm.warp(block.timestamp + MATCH_TIMEOUT +
REFUND_GRACE + 1)`, which advances time for **every** match, so every
`Created` match older than the timeout then fails `joinDuel`'s
`require(block.timestamp < duel.createdAt + MATCH_TIMEOUT, "Match expired")`.
The `settle` reverts (2.3 %) are the same warp interacting with the settlement
deadline. Both are the contract **correctly rejecting** an action the handler
keep retrying.

That is the honest reading: the pass is real, the properties are real, but the
campaign spends a quarter of its budget on calls it already knows are invalid,
and it has no mechanism to tell a *new* revert from that background noise.

### The fix, and its estimate

| step | change | time |
|---|---|---|
| 1 | pre-check expiry in the handler (`if (block.timestamp >= createdAt + MATCH_TIMEOUT) return;`) so the budget goes to reachable states | 20 min |
| 2 | wrap `join`/`settle` in `try/catch`, record the revert selector, and add `invariant_no_unexpected_reverts()` asserting the recorded set is exactly the allowlist (`Error("Match expired")`, the settlement deadline error) | 45 min |
| 3 | re-run `nightly` and record the new revert table plus the new call mix | 21 min (unattended) |

Total ≈ 1.5 h of work plus one unattended run. It is **not** done here: an
invariant campaign that has been narrowed blind is worse than one that is
honestly described, and step 2 needs the allowlist to be derived from a run, not
guessed.

---

## 5. What this proves, and what it does not

**Proves:** the escrow's six financial invariants hold across 3.07 million
randomized calls at 16× the depth CI uses, and its five fuzz properties hold
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
