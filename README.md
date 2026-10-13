# PULSAR — Non-Custodial Web3 Reaction Duels

Skill-based 1v1 reaction duels with USDT escrow on Polygon. The client is
untrusted by design: every result is committed/revealed through the game
server, settled by an oracle signature, and paid out by an on-chain escrow —
no custodial wallets anywhere.

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

bun run verify         # the full gate: 15 checks, 0 tolerated failures
bun run test:unit      # frontend (vitest)
bun run test:server    # server protocol suite (pytest)
bun run test:contract  # Solidity compile gate (solc 0.8.20, paris + shanghai)
```

`bun run verify` is the single source of truth for "is this green". It runs the
frontend suite, the Python suite, the coverage ratchet, ruff, mypy, the contract
compile gate, and a set of protocol/security probes. CI runs the same gates plus
`forge test` and the Firestore emulator.

Current counts (measured, not remembered):

| Suite | Count |
|---|---|
| Frontend (vitest) | 201 tests, 48 files |
| Server (pytest) | 278 tests |
| Contract (forge) | 81 tests |
| Coverage ratchet | 84% (floor 79) |

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
- **No real-money deployment is authorized** until the rehearsal checklist in
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) passes end-to-end.

## Deployment

The full runbook — env vars, Amoy rehearsal, oracle key handling — lives in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Incident response is in
[`docs/INCIDENT-RUNBOOK.md`](docs/INCIDENT-RUNBOOK.md).
