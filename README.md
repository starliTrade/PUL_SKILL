# PULSAR — Non-Custodial Web3 Reaction Duels

Skill-based 1v1 reaction duels with USDT escrow on Polygon. The client is
untrusted by design: every result is committed/revealed through the game
server, settled by an oracle signature, and paid out by an on-chain escrow —
no custodial wallets anywhere.

> **Deployment status: TESTNET ONLY. Not fit for real money yet.**
> The application has not been audited by an external firm, the oracle signer
> is a centralised authority, and there is **no KYC, no payout delay and no
> withdrawal cap** — the escrow contract is permissionless, so a server-side
> control can be bypassed by calling it directly. Read
> [`docs/COMPLIANCE-C-02c.md`](docs/COMPLIANCE-C-02c.md) and
> [`docs/audit/RUTHLESS-AUDIT-2026-10-22.md`](docs/audit/RUTHLESS-AUDIT-2026-10-22.md)
> before pointing this at a mainnet token or real users.

## Stack

- **Frontend**: Vite + React 19 + TypeScript + Tailwind CSS v4
- **Backend**: FastAPI (Python) — `api/` — SIWE auth, matchmaking, commit/reveal
  anti-cheat, settlement, oracle signing
- **Contract**: `contracts/PulsarEscrow.sol` (Solidity 0.8.20, dependency-free)
  with Foundry tests
- **Persistence**: Firestore (durable match store, rate limiting, ledger) with an
  in-memory fallback for local dev

## Commands

```bash
bun install            # install JS dependencies
bun run dev            # Vite dev server
bun run build          # production build (dist/)
bun run lint           # tsc --noEmit && eslint . --max-warnings 0

bun run verify         # every gate scripts/verify.sh can run, with a summary of
                       # passed / failed / SKIPPED. A skip is never a pass — it is
                       # reported with its reason, and `--strict` turns skips into
                       # failures. bun is optional: the script falls back to npm.
bun run test:unit      # frontend (vitest)
bun run test:server    # the standalone protocol smoke script (not pytest)
bun run test:contract  # Solidity compile gate (solc 0.8.20, paris + shanghai)
```

`bun run verify` is the single source of truth for "is this green". It runs the
frontend suite, the Python suite, the hermetic coverage gate, ruff, mypy,
`forge test`, the contract compile gate, and a set of protocol/security probes.

**Browser E2E** (audit L-04). `npx playwright test` is 30 tests in 6 files across
two projects (desktop, Pixel 7) and it is wired up, not deferred: the config
starts `scripts/start_e2e_stack.sh`, which brings the API up against anvil with
the production-like configuration (escrow address, RPC, chain id, signer policy),
because a dev bypass would test the wrong thing. Prerequisites are anvil (it must
have deployed the escrow — `scripts/start_anvil.sh --bg`) and browser binaries
(`npx playwright install`).

The old line here said the suite "always SKIPs until phase 10". It does not, and
the difference matters: in the environment this repository was assembled in,
`npx playwright install` cannot reach its download host, so the suite starts the
real stack and then fails at `browserType.launch`. That is an environment limit
and it is reported as one — a green unit suite is not evidence that the app boots
in a browser.

Coverage is measured TWICE, on purpose (audit M-15). The hermetic gate deselects
everything that needs a service, so its number cannot move depending on what
happens to be running; the complete gate adds the emulator and anvil tests and
carries the higher floor. A gate that only passes because you had an emulator
started is not a gate, and the previous single measurement reported 74% and 79%
for the same commit depending on exactly that. The hermetic floor is now 77
(the number it measures is 78); it moves only in the commit that adds tests.

Counts are **generated from the last full run**, not maintained by hand — the
previous table said 202/278/81 and was already stale (audit M-17). Run
`scripts/test_counts.py` to reprint it, and paste its output here at release:

| Suite | Count (last measured in this repository) |
|---|---|
| Frontend (vitest) | 351 tests, 70 files (measured 2026-10-23) |
| Server (pytest) | 661 passed / 25 skipped with anvil running; 650 / 36 with anvil stopped (the chain suites skip), measured 2026-10-23 |
| Contract (forge, `default`) | 104 tests, 9 suites, measured 2026-10-23 (forge 1.7.1, forge-std + OpenZeppelin v5.0.2). The sandbox cannot reach `binaries.soliditylang.org`, so forge was driven with the `solc-js` 0.8.20 build already in `node_modules` via a small shim — the compiler and the tests are real, the toolchain path is not the default one |
| Chain integration (anvil) | 11 tests passing against `scripts/start_anvil.sh --bg` — real `createDuel`/`joinDuel` and a settlement signed by the real `api/oracle.py` |
| Contract (forge, `nightly`) | **104 tests, 0 failed in 21 min** — 5 fuzz tests × 10,000 runs (50,000 cases) and 6 invariants × 1,024 runs × 500 depth (**3,072,000 calls**), run 2026-10-23. The profile had never been executed before; the report records where the pass is weaker than its numbers suggest: [docs/CONTRACT-FUZZ-REPORT.md](docs/CONTRACT-FUZZ-REPORT.md) |
| Coverage, hermetic (`.coveragerc-hermetic`) | **78%** over 4314 statements (969 missed), floor 77, measured three times on 2026-10-23 with no emulator and no anvil — this is the gate that must always be green (audit M-15) |
| Coverage, complete (`.coveragerc`) | 79% floor, only measurable with the Firestore emulator + anvil running; reported as its own gate, skipped loudly when they are absent |
| Contract coverage (`forge coverage --report summary`) | `PulsarEscrow.sol`: **98.57%** lines (207/210), 98.48% statements, **86.73%** branches, **100%** functions (31/31), measured 2026-10-23 on the same commit |

The five-language UI is audited, not asserted: [docs/I18N-AUDIT.md](docs/I18N-AUDIT.md) records what was measured, the 42 strings that never reached a dictionary, and the numeral policy every screen now follows.

Server line coverage is **not** a single number you should quote: [docs/COVERAGE-REPORT.md](docs/COVERAGE-REPORT.md) records the measured figure, the conditions it was measured under, and a classified list of every gap (environmental vs. genuinely untested).

`forge test` is a CI gate; treat its result as the source of truth for the
contract suite, never this table. The contract is versioned (`VERSION` /
`VERSION_CODE`, surfaced in `/api/health`) and a replacement follows
`docs/UPGRADE-PATH.md`; the fee model is fixed by design and documented in
`docs/ECONOMICS.md`.

## What is actually enforced

- **Authoritative anti-cheat is server-side**: the commit → reveal → submit
  protocol. Client-side telemetry is a practice-mode UX aid only.
- **The escrow is the money**: `PulsarEscrow.sol` holds both stakes and pays the
  winner 98% / treasury 2%. The server signs a settlement; it cannot move funds.
- **Fairness gates are server-side**: a ping cap, a rating band, and pairing by
  closest connection. The server does not subtract a client-reported round trip.
- **No fabricated data**: a CI gate (`src/lib/no-fabricated-data.test.ts`)
  rejects any `Math.random()` that feeds a number the player reads as a
  measurement or money.

## Known limitations (read before deploying)

- **The eligibility gate is a self-declaration.** 18+/jurisdiction consent is one
  localStorage key with **no server or edge enforcement** — `api/` performs no
  geo lookup and refuses no region. Real enforcement (edge geo-blocking plus a
  server-side region check) is an open compliance item.
- **The legal documents are English-only.** The Terms of Service, Privacy Policy
  and Risk Disclosure exist only in English; the app says so in the other four
  languages rather than shipping a machine translation of a legal text.
- **Colour contrast does not meet WCAG AA everywhere.** `text-zinc-500` measures
  4.15:1 and `text-zinc-600` 2.59:1 on the app's darkest surface (AA needs 4.5:1
  for normal text).
- **Ratings are process-local**, so the pairing band holds within a replica.
- **The "no fabricated data" gate has a known blind spot.** It sees the literal
  `Math.random()` token and bare measurement literals. A fabrication that uses
  neither — a hardcoded number in a variable, a `crypto.getRandomValues` value,
  a helper that wraps randomness — is invisible to it. That class is caught by
  reading the copy, which is why the audit is a separate step from the gate.
- **No real-money deployment is authorized** until the rehearsal checklist in
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) passes end-to-end.

## Deployment

The full runbook — env vars, Amoy rehearsal, oracle key handling — lives in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Incident response is in
[`docs/INCIDENT-RUNBOOK.md`](docs/INCIDENT-RUNBOOK.md).
