# Server coverage — what the number means (measured 2026-10-25)

**Why this document exists.** `pytest --cov` prints one percentage, and a single
percentage invites exactly the wrong conclusion: "79 % covered" does not mean
"21 % of the risk is untested". It means 21 % of *statements* never executed in
this environment — and most of what remains is code that **cannot** execute here
(Firestore, the emulator, Java, a KMS endpoint), not code that is dangerous.

So this file records three things separately: the measurement conditions, the
number over time, and an explicit classification of every remaining gap into
**environmental** (no test can reach it on this machine) and **genuinely
untested** (a test could, and should).

---

## 1. Conditions of the measurement

| | |
|---|---|
| config | `.coveragerc-hermetic` (the gate that runs everywhere) |
| command | `env -u FIRESTORE_EMULATOR_HOST coverage run --rcfile=.coveragerc-hermetic --source=api -m pytest -q -m "not emulator and not chain"` |
| suite | **753 passed / 42 skipped** |
| statements | 4318, missed **910** (79 %) |
| repeats | two consecutive runs on 2026-10-25: identical (910 missed, 753 passed) |
| machine | 2 vCPU sandbox, no JRE, no emulator, anvil available but deselected |

The complete gate (`.coveragerc`, floor 79) needs the emulator + anvil. **It was
not measured here** and this document does not claim it.

---

## 2. The number over time

Three columns, because a ratchet that only records "now" cannot show whether it
moved forward or was redefined. Column 1 is where this audit started; column 2 is
the H-26 pass (the claim verifier); column 3 is this pass.

| module | 2026-10-22 | 2026-10-23 (H-26) | 2026-10-25 (this pass) | what moved it |
|---|---:|---:|---:|---|
| `onchain.py` | 81 % | 87 % | **90 %** | the version/decoding edges: hostile `VERSION()` payloads, a truncated `paymentToken()`, the decimals cooldown (§3.2 #3) |
| `oracle.py` | 86 % | 86 % | **90 %** | all three `eth-account` signing spellings + the loud failure (§3.2 #2) |
| `metrics.py` | — | 91 % | **100 %** | the middleware promise, the read attribution, the empty-percentile case (§3.2 #4) |
| `main.py` | 74 % | 74 % | **77 %** | settle/re-sign/void branches, and the two post-commit side effects (§3.2 #1 and “the fifth cluster”) |
| `store.py` | 71 % | 71 % | 71 % | Firestore-only code (§3.1) |
| `signer.py` | 69 % | 69 % | 69 % | KMS/HSM paths, no hardware here |
| `privacy.py` | 47 % | 47 % | 47 % | export/delete against Firestore |
| `economy.py` | 62 % | 62 % | 62 % | ledger and stats rows against Firestore |
| **TOTAL** | **77 %** (988 missed) | **78 %** (969 missed) | **79 %** (910 missed) | 50 new tests, no test deleted or weakened |
| statements | 4314 | 4314 | 4318 | statements moved with the code, not with the config |
| floor | 74 (hermetic) | 77 (hermetic) | **78** |

The floor is ratcheted in the same commit as the tests that earn it, and it is
one point below the measurement, never equal to it: a floor equal to the wall
makes every skipped test on a slower machine look like a regression.

---

## 3. The gaps, classified

### 3.1 Environmental — no test on this machine can reach them

These are not holes in testing; they are holes in the *environment*, and the
go-live checklist names the command that closes each one.

| area | lines | why it cannot run here | how it gets closed |
|---|---|---|---|
| `store.py` Firestore store (≈ 200) | `915-984`, `1594-1625`, `sweep_expired`, `enqueue`, `update`, `pending_challenges` | needs the Firestore emulator (Java) | `bash scripts/start_emulator.sh --bg` then the `-m emulator` suite |
| `main.py` distributed rate limiter | `226-274`, `_rl_check` | transactional Firestore window | same |
| `main.py` admin/export/delete | `2493-2581` | Firestore-backed | same |
| `economy.py` ledger and stats | `256-282`, `325-368`, `452-549`, `640-650` | rows in Firestore | same |
| `auth.py` durable revocation | `334-360` | Firestore `auth_revocations` | same |
| `privacy.py` export/delete | `107-165` | Firestore collections | same as above |
| `signer.py` external signer | `285-370`, `_public_key`, `_raw_sign` | KMS/HSM endpoint | a real cloud account |
| `onchain.py` RPC transport edges | `340-346`, `475-486`, `510-519` | needs a misbehaving live node | the fake-RPC suite covers the shapes; the rest is latency/transport |

### 3.2 Genuinely untested — closed in this pass

**Already closed (H-26, 2026-10-23).** `onchain.verify_settlement_tx` — the
function that decides whether a supplied transaction hash really settled *this*
match for *this* claimer — was stubbed out (`lambda *a, **k: True`) in the only
two tests that exercised the claim endpoint. The tests therefore proved "a
verified claim is recorded" while the verification itself was assumed. 15 cases
now drive the real function through the shared `FakeRpc`, and one of them found
a real defect: a malformed `logs` entry raised `AttributeError` inside the claim
endpoint, answering **500** to a player whose prize was already on chain.

**Closed in this pass (2026-10-25).** The four ranked gaps in the previous
version of this table, in the order they were ranked, plus a fifth cluster the
triage below turned up.

| # | area | test file | cases | what the tests now pin |
|---|---|---|---:|---|
| 1 | `main.py` settle/claim/re-sign | `test_institution_resign.py` | 11 | a failed signature leaves the STORED match untouched (asserted through `store.update`, the mechanism that actually rolls it back); the counter and the `match.sign_failed` event; a spendable envelope replays without re-signing; an expired one is re-signed with `resigned: true` and its `roundWins` preserved; a failed re-sign returns the stale envelope instead of a 5xx; a match past its refund horizon is voided with the refund reason, not resigned; the sweep counts its own failures |
| 2 | `oracle.py` signer fallbacks | `test_oracle_signer_api.py` | 6 | `unsafe_sign_hash` → `signHash` → `sign_hash`, precedence, digest passthrough, the loud failure when none exists, and a guard that the LOCKED eth-account still exposes the preferred method |
| 3 | `onchain.py` version/decode edges | `test_rpc_decoding.py` | 14 | non-hex, non-UTF-8, truncated, control-ridden and empty `VERSION()` payloads all answer `None` (never raise, never reflect); a truncated `paymentToken()` is not an address; a failing `decimals()` read is not retried on every call, and IS retried after its cooldown |
| 4 | `metrics.py` overflow/attribution | `test_metrics_attribution.py` | 11 | the middleware promise ("never raise"), the three counters that had zero callers, `readsPerMatch: None` before the first match, the signature failure rate, `_percentile([])` |
| 5 | `main.py` post-commit side effects | `test_post_commit_side_effects.py` | 8 | a settled match writes ONE ledger row and an unsettled one writes none; a failed row emits `ledger.write_failed` with the match and the error type and does not pass silently; integrity scoring uses the server's `observed_ms`, never the client's `measuredMs`, and swallows its own failure |

**One defect fixed under #4.** `metrics.note_firestore_read` incremented a module
global outside `_lock` while `snapshot()` read it inside: `+=` is a
read-modify-write, so concurrent requests could lose an increment — always
downward, on the number the "<20 reads per match" target is measured with. It is
now incremented under the lock. A data race cannot be asserted
deterministically, so the test pins the lock itself and says so.

Every one of these was mutation-checked: the fix was reverted (or the branch
deleted) and at least one test failed. In one case this exposed a test that
proved nothing — the first version of the rollback test passed with the rollback
deleted, because it did not go through `store.update`; it was rewritten, and the
`api/main.py` comment claiming that line was the protection was corrected.

### 3.3 What is left, ranked by cost (triage, not a promise)

The remaining 910 lines, grouped by the function that owns them (an AST mapping
of coverage's own missing set, so the numbers add up to the total). The reason
column is the classification, not a hope.

| lines | where | classification |
|---:|---|---|
| 41 | `store.sweep_expired` | environmental — Firestore sweep |
| 25 | `main.py` module level | import-time production guards; run only under a production env (see §3.1) |
| 24 | `economy.record_settlement._apply` | environmental — Firestore transaction body |
| 23 | `privacy.erase` | environmental — Firestore collections |
| 21 | `signer._public_key` | environmental — KMS |
| 19 | `main.queue` (the endpoint body) | **testable** — the store-contention 503 belongs to the global handler (tested); the per-endpoint duplicate is reached only by injecting a store failure mid-request |
| 18 + 14 | `store.enqueue`, `enqueue._txn_body` | environmental — Firestore |
| 18 + 9 | `store.update`, `update._txn_body` | environmental — Firestore (the memory-mode twin IS tested) |
| 17 | `main._rl_check` | environmental — Firestore window |
| 17 | `store.player_live_match` | environmental — Firestore |
| 16 | `store._round_from_doc` | environmental — Firestore document shape |
| 15 + 15 | `main.username_lookup`, `store.pending_challenges` | environmental — Firestore |
| 14 | `auth.verify_siwe` (durable nonce branch) + 10 `revoke_session` | environmental — Firestore |
| 13 + 13 | `abuse._firestore_client`, `limits._firestore_client` | environmental — client construction |
| 13 | `main.admin_force_settle` | environmental — admin + Firestore |
| 12 | `store.__init__` | environmental — Firestore client init |
| 10 | `main.players_search` | environmental — Firestore query |
| 10 + 10 | `main._resign_stale_settlements`, `store.recent/settled_matches` | mixed: the memory sweep and the past-horizon skip are tested; the Firestore variants are not |

Nothing in that table is a known bug. It is the set of places where a future
change could land without a failing test — which is what a ratchet is for — and
the two "testable" rows are named as such rather than quietly filed under
"environment" with the rest.

---

## 4. Rules this document follows

1. A percentage is only quoted with its configuration and its service state.
2. A gap is either environmental (with the command that closes it) or untested
   (with an owner and an effort estimate). Nothing is "probably fine".
3. The floor moves **up** in the same commit that adds the tests, never before,
   and never by more than the measurement minus one point.
4. Coverage is a floor, not a goal: 100 % of statements says nothing about
   whether `verify_settlement_tx` checks the right topics — which is why §3.2
   lists behaviour, not lines.
5. A test that does not fail when its subject is broken is not a test. The
   mutation that was run is recorded next to the claim it supports.
