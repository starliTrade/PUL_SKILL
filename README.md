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
bun run lint           # typecheck (tsc --noEmit) — the only linter wired up

# Server protocol tests (need the Python venv: .venv/bin/python)
bun run test:server    # protocol-level suite (match engine, auth, store)
bun run test:contract  # Solidity compile gate (solc 0.8.20, paris + shanghai)

# Extra server suites
.venv/bin/python scripts/test_http_e2e.py            # HTTP E2E (TestClient)
.venv/bin/python scripts/test_firestore_integration  # real Firestore (needs creds)
```

Contract tests beyond the compile gate (`forge test`) run in CI — Foundry is
not required locally.

## Deployment

The full runbook — env vars, Amoy rehearsal, oracle key handling — lives in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). No real-money deployment is
authorized until the rehearsal checklist there passes end-to-end.

## Honest-status note

Client anti-cheat telemetry is a practice-mode UX aid only; authoritative
anti-cheat is the server-side commit→reveal→submit protocol. See
`docs/DEPLOYMENT.md` for the current known-limitations list.
