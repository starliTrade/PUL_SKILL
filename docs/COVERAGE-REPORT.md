# Server coverage — what the number means (measured 2026-10-23)

**Why this document exists.** `pytest --cov` prints one percentage, and a single
percentage invites exactly the wrong conclusion: "78 % covered" does not mean
"22 % of the risk is untested". It means 22 % of *statements* never executed in
this environment — and a large part of that 22 % is code that **cannot** execute
here (Firestore, the emulator, Java), not code that is dangerous.

So this file records three things separately: the measurement conditions, the
number, and an explicit classification of every remaining gap into
**environmental** (no test can reach it on this machine) and **genuinely
untested** (a test could, and should).

---

## 1. Conditions of the measurement

| | |
|---|---|
| config | `.coveragerc-hermetic` (the gate that runs everywhere) |
| command | `env -u FIRESTORE_EMULATOR_HOST coverage run --rcfile=.coveragerc-hermetic --source=api -m pytest -q -m "not emulator and not chain"` |
| suite | **645 passed / 8 skipped / 28 deselected** |
| statements | 4314, missed **969** |
| repeats | three consecutive runs: 78 %, 78 %, 78 % (missed 969/970/969 — one test touches a thread-timing line) |
| machine | 2 vCPU sandbox, no JRE, no emulator, anvil available but deselected |

The complete gate (`.coveragerc`, floor 79) needs the emulator + anvil. **It was
not measured here** and this document does not claim it.

---

## 2. The number, before and after this audit pass

Two configurations produce two numbers. Quoting one without the other is how the
old single gate became a coin flip, so both are given, and the column says which
is which.

| module | full run, before | full run, after | hermetic, after | what moved it |
|---|---:|---:|---:|---|
| `onchain.py` | 81 % | **90 %** | 87 % | `verify_settlement_tx` had **zero** direct tests (H-26); the gap between the two columns is the chain-marked integration tests, deselected hermetically |
| `main.py` | 74 % | 74 % | 74 % | — (see §3) |
| `oracle.py` | 86 % | 86 % | 86 % | one branch (unknown horizon) added by H-25 |
| `store.py` | 71 % | 71 % | 71 % | Firestore-only code (see §3) |
| `signer.py` | 69 % | 69 % | 69 % | KMS/HSM paths, no hardware here |
| `privacy.py` | 47 % | 47 % | 47 % | export/delete against Firestore |
| **TOTAL** | **77 %** (988 missed) | **78 %** (957 missed) | **78 %** (969 missed) | |
| statements | — | 4314 | 4314 | |
| floor | 74 (hermetic) | **77** (hermetic) | 77 | ratcheted in the same commit, per the rule in the config |

The two totals agree at 78 % by coincidence, not by construction: the full run
executes more lines (the chain suites) and also counts more missed lines in code
that only the emulator would reach.

---

## 3. The gaps, classified

### 3.1 Environmental — no test on this machine can reach them

These are not holes in testing; they are holes in the *environment*, and the
go-live checklist names the command that closes each one.

| area | lines | why it cannot run here | how it gets closed |
|---|---|---|---|
| `store.py` Firestore store (≈ 200) | `915-984`, `1594-1625`, … | needs the Firestore emulator (Java) | `bash scripts/start_emulator.sh --bg` then the `-m emulator` suite |
| `main.py` distributed rate limiter | `226-274` | transactional Firestore window | same |
| `main.py` admin/export/delete | `2502-2565` | Firestore-backed | same |
| `signer.py` external signer | `285-370` | KMS/HSM endpoint | a real cloud account |
| `privacy.py` export/delete | `107-165` | Firestore collections | same as §3.1 row 1 |
| `onchain.py` RPC edge cases | `339-345`, `433-434`, `508`, `536-542` | needs a misbehaving live node | the fake-RPC suite covers the shapes; the rest is latency/transport |

### 3.2 Genuinely untested — a test could reach it, and now does where it mattered

**Closed in this pass (H-26).** `onchain.verify_settlement_tx` — the function
that decides whether a supplied transaction hash really settled *this* match for
*this* claimer — was stubbed out (`lambda *a, **k: True`) in the only two tests
that exercised the claim endpoint. The tests therefore proved "a verified claim
is recorded" while the verification itself was assumed.

15 cases now drive the real function through the shared `FakeRpc`:

* accepts a genuine receipt (correct escrow, correct match key, correct winner);
* refuses a reverted transaction, a transaction to another contract, an event
  emitted by another contract, a settlement for a different match, a settlement
  paid to a different address, a receipt with no event, a log with truncated
  topics, a malformed hash (without even calling the RPC), an unreadable receipt,
  an RPC outage, a wrong chain, and an unconfigured escrow;
* **never raises** — and this one found a real defect: a malformed `logs` entry
  (a string instead of an object, a `null`, a provider quirk) raised
  `AttributeError` inside the claim endpoint, which would have answered **500**
  to a player whose prize was already on chain. Fixed.

The match-key derivation is also cross-checked against `tests/fixtures/chain.py`,
which documents that its own derivation must equal the server's.

**Still open, ranked by what a bug there would cost** (hermetic line numbers):

| # | area | lines | what it would cost | effort |
|---|---|---|---|---|
| 1 | `main.py` settle/claim error branches | `2162-2174`, `2210-2232`, `2300-2327` | a settlement failing in a way nobody sees | 1 day |
| 2 | `oracle.py` signer fallbacks | `148-152` | an eth-account version where signing silently changes shape | 2 h |
| 3 | `onchain.py` version/decode edges | `249-250`, `268`, `284` | a pre-2.0 escrow mistaken for a 2.0 one | 4 h |
| 4 | `metrics.py` overflow paths | `99-164` | the route table dropping entries under load | 3 h |

None of these is a known bug. They are the places where a *future* change could
land without a failing test, which is exactly what a ratchet is for.

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
