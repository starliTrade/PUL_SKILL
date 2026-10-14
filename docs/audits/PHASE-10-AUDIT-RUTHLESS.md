# Phase 10 — adversarial audit

Commissioned after the phase was declared complete. Method: **attack the claims, not
re-measure them.** Three independent audit threads (E2E suite, Python/chaos suite,
plan-vs-evidence) plus direct verification of every finding I intended to act on.

`main = f5e9752` at the start of this audit. `bun run verify` → 16 gates, 0 fail.

**Verdict: the engineering is largely real; the claims overreached in specific,
identifiable places.** Phase 10 was declared "zero open items". It was not.

---

## 1. Claims that were FALSE, and are now fixed

### 1.1 `p99` did not exist — the plan claimed it for every endpoint

Plan item 10.3.4 claimed p50/p95/**p99** per endpoint. `api/metrics.py` computed only
p50 and p95; `grep -rn p99` across the repo found **only the plan line itself**.

**Fixed by making the claim true** rather than deleting the requirement: `p99Ms` is
now computed, and the sample window was widened 256 → 1024, because the 99th
percentile of 256 samples is the 2nd-highest value — "almost the max", not a
percentile.

### 1.2 The refund test never ran

`tests/integration/test_refund_after_timeout.py` skips unless
`PULSAR_TEST_TIME_TRAVEL=1`. **Nothing set that flag** — not CI, not `verify.sh`, not
any script. The refund money path was claimed verified by a test that never executed.

**Fixed:** a dedicated gate runs it with the flag, then restarts anvil (the time
travel cannot be undone, and a travelled chain breaks every later deadline test).

### 1.3 The chaos suite ran in no gate

`scripts/chaos_suite.py` was referenced by **nothing** — not `verify.sh`, not CI, not
`package.json`. Nineteen checks that no gate ever ran, cited as evidence for all of
10.4.

**Fixed:** it is now a gate. It immediately failed, which is the point (see 2.1).

### 1.4 The ranked-flow E2E ran in no gate

`tests/integration/test_ranked_flow_e2e.py` — the only end-to-end test of the live
money path — skips without a live API, and the pytest gate runs **before** any API
exists. CI never starts one. So the ranked path was verified by a test that never
ran in an automated gate.

**Fixed:** a live-stack gate starts the E2E stack and runs it for real.

### 1.5 There is no light/dark theme — the plan marked it done

Plan item 10.2: "light/dark theme ✅ both themes". The app has **one** theme. Every
`theme` in the codebase is a rank tier's colour (`currentTier.theme.coreColor`), not
a mode. And the test that "verified" it set `localStorage.pulsar_theme` — **a key
read by nothing in `src/`** — then asserted the banner and main were visible, which is
true in every theme and in no theme.

**Fixed:** the tests are deleted with the reason recorded, and the item is **open**.

### 1.6 The chaos "fail-closed" check was a false green — proven

`scenario_rpc_kill` queued two players and asserted a round came back 409 while the
RPC was down. But `pair_two_players` **never deposits** — so the match had no
on-chain duel, and the gate answers 409 for an unfunded match *whatever the RPC is
doing*. The check passed with the RPC **up**.

**Fixed by adding the control that was missing:** fund the duel, prove a round is
**accepted** with the RPC alive, and only then kill it. The control immediately
caught two further problems in my own setup (participants not matching the duel; a
second match that was not actually a second match).

### 1.7 The "fail-closed" property is narrower than claimed

With the control in place, a **warm** match (deposit already verified, cached 60s)
keeps playing through an RPC outage — returning 200, not 409. That is *correct*
behaviour: a verified deposit does not un-verify because a node went away. But it
means "fail-closed" is only true on a **cold** read, and the plan stated it flatly.

**Recorded as a NOTE in the suite** rather than asserted either way: on a freshly
funded match the cold read also returned 200, which contradicts the gate's own
fail-closed docstring, and I could not settle why within this pass. Asserting either
answer would be a guess dressed as a test.

---

## 2. Claims that were overstated

| Claim | Reality |
|---|---|
| "The application is not the bottleneck" | Measured at **50** concurrent users in-memory; the 1000-user run is against the emulator and stalls. There is **no measurement of the app at 1000 concurrency** — the headline extrapolates. |
| "1000 concurrent pollers on `/api/queue`" | The harness drives the **join** path (POST), not queue-state polling. Different traffic shape, different cost. |
| "Chaos 19/19" | A true count of a suite in which **3 checks did not test their claimed property** (2 passed with the bug present, 1 tested the harness). Now 24 checks with a real control. |
| "24h soak: 196KB growth" | The figure appeared **nowhere in the repo**. Re-measured: **224KB over 45s**. The threshold is `<50 MB`, which is far looser than "no leak". |
| "reads per match: 47" | The repo's own evidence says **35** — and the plan's cost row already used 35. The plan contradicted itself. |
| "replica split: both replicas read the same store" | Compared a **config boolean** (`{"available": true}`) that is true on both by construction. The documented property ("a match created on A is visible on B") was never tested. |
| "prize claimed on-chain" | A **manual run pasted into a comment** in `ranked-duel.spec.ts`, never asserted. |

---

## 3. The process failure

**`6.11` (Firestore document versioning / `schemaVersion`) was moved into Phase 10**
and is **still unimplemented** — `grep -rn schemaVersion api/` finds only a comment
saying the migration is still needed. Phase 10 was declared "zero open items" with a
moved-in item open.

That is the finding I care most about, because it is not a technical error. It is me
declaring a phase complete by reading my own checklist instead of enumerating what
the phase actually contained.

---

## 4. What is genuinely solid — stated plainly

- `tests/integration/test_chain_smoke.py` — CI-enforced, real oracle signature, exact
  token deltas. The strongest money-path file in the repo.
- `tests/unit/test_store_identity.py` — no skips, adversarially designed: the cache
  test makes `get` **raise** if the cache path falls through, and the contention test
  pins the **negative** case.
- `test_a_timeout_refund_makes_both_players_whole` — asserts the specific guard
  message and exact balances.
- `docs/LOAD-REPORT.md` — the most honest artifact in the set: it states that 35 is
  above the target and that client polling is excluded.
- The `ALLOWED_HOSTS` split, the health-probe honesty, the 503 contention fix, and
  the mirror-backed `identity` cache are all real engineering.

---

## 5. Status after this audit

**Phase 10 open items: 2** — the theme (does not exist) and `6.11` (moved in, never
done). Both are now visible instead of ticked.

Gates: **19** (was 16). The three added — live-stack integration, refund time-travel,
chaos — are the ones that were claimed but never ran.

**The lesson, and it is the same one three times now:** every failure in this audit
was a claim resting on an artifact I had not actually run, or had run once by hand.
A test that cannot fail, a gate that does not exist, and a checklist read as evidence
all look identical from the outside — green.
