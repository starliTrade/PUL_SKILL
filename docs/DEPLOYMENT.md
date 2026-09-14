# PULSAR — Production Deployment Runbook (P2.5)

End-to-end path from this repository to a real-money launch. Complete every
step in order; the Readiness Checklist at the bottom is the final gate.

---

## 0. Prerequisites

- Node.js 20+ and [Foundry](https://book.getfoundry.sh/) (`curl -L https://foundry.paradigm.xyz | bash`)
- A funded deployer wallet on Polygon (holds MATIC for gas; **never** used as the oracle key)
- Firebase project (the one the client already uses) with Firestore enabled
- A Sentry account (free tier is enough to start)
- A free [Polygonscan API key](https://polygonscan.com/apis) (for contract verification)
- Free testnet POL from the [Polygon faucet](https://faucet.polygon.technology/) (Amoy)

### Chain strategy (Amoy first — this is the rehearsal phase)

The client now defaults to **Polygon Amoy (80002)** and only switches to
mainnet (137) via `VITE_CHAIN_ID=137` after the Readiness Checklist passes.
On Amoy the escrow runs against `MockUSDT` (deployed by the script below, with
a built-in faucet), so the entire money path is rehearsed with zero risk.

---

## 1. Deploy PulsarEscrow

First scaffold forge-std (one time) and run the test suite on your machine:

```bash
cd contracts && forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts --no-commit
forge test        # 10-test lifecycle suite: replay, forged sig, high-s, deadlines, refunds
```

Then deploy with the provided script (Amoy shown; mainnet = add `--chain 137`):

```bash
export DEPLOYER_PRIVATE_KEY=0x...        # gas wallet, funded with testnet POL
export TREASURY_ADDRESS=0x...            # receives the 2% rake
export ORACLE_SIGNER_ADDRESS=0x...       # public addr of ORACLE_PRIVATE_KEY (step 2)
# On Amoy leave PAYMENT_TOKEN_ADDRESS unset -> MockUSDT is deployed automatically

forge script script/Deploy.s.sol --rpc-url https://rpc-amoy.polygon.technology --broadcast
# => prints MockUSDT address + PulsarEscrow address
```

Fund the two test wallets on Amoy:

```bash
cast send $MOCK_USDT "faucet(address,uint256)" $PLAYER1 5000000000 --rpc-url ... --private-key $DEPLOYER_PRIVATE_KEY
```

Verify on the explorer:

```bash
forge verify-contract <ESCROW_ADDRESS> contracts/PulsarEscrow.sol:PulsarEscrow \
  --chain-id 80002 --verifier-url https://api-amoy.polygonscan.com/api \
  --etherscan-api-key $POLYGONSCAN_API_KEY
```

When moving to mainnet (137): set `PAYMENT_TOKEN_ADDRESS=0xc2132D05D31c914a87C6611C10748AEb04B58e8F`
(canonical USDT), verify against `polygonscan.com`, and re-derive every address.

⚠️ The oracle key signs real payouts. Use a dedicated key holding no funds;
give it only signing authority. Consider moving production signing to AWS KMS
or GCP KMS (the signing surface in `api/oracle.py` is designed for it).

⚠️ Chain binding: `ORACLE_CHAIN_ID` on the server **must equal** `VITE_CHAIN_ID`
on the client. `settleDuel()` hashes `block.chainid`, so a mismatch makes every
settlement signature invalid on-chain (the oracle defaults to 80002 = Amoy,
matching the client default).

## 2. Generate the oracle key

Generate the oracle key (run ONCE, on a secure machine):

```bash
cast wallet new
# → store the private key as ORACLE_PRIVATE_KEY (server secret)
# → store the address    as VITE_ORACLE_WALLET_ADDRESS (public, baked into contract)
```

---

## 3. Host the game server (FastAPI, `api/`)

Any Python host works (Fly.io, Railway, Google Cloud Run, a VPS). The server
is stateless except for match persistence, which now lives in Firestore.

```bash
pip install -r api/requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080   # run from inside api/
```

Server environment (all **secrets** — set on the host, never in git):

| Variable | Purpose |
|---|---|
| `ORACLE_SIGNING_SECRET` | HMAC secret for SIWE nonces + session tokens (any long random string) |
| `ORACLE_PRIVATE_KEY` | The oracle signer (matches the contract's `oracleSigner`) |
| `ORACLE_CHAIN_ID` | **Must equal `VITE_CHAIN_ID`** (default 80002). The escrow hashes `block.chainid` — a mismatch invalidates every settlement signature |
| `ESCROW_ADDRESS` | Deployed contract address (binds settlement signatures) |
| `ESCROW_RPC_URL` | JSON-RPC endpoint for the deposit gate (e.g. an Alchemy/Infura Amoy URL). **Required in production**: with `ESCROW_ADDRESS` + `ESCROW_RPC_URL` set, the server independently verifies BOTH stakes are locked on-chain (read-only `eth_call`) before every round — fail-closed if the RPC is down. Unset = gate inactive (practice mode only) |
| `PULSAR_MATCH_STORE` | `firestore` (or unset for in-memory dev fallback) |
| `FIRESTORE_PROJECT_ID` | Your Firebase project ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service-account JSON path (or use ambient Cloud Run credentials) |
| `CORS_ALLOW_ORIGINS` (optional) | Comma-separated allowlist; leave unset ("*") while frontend and API are on different origins |
| `SENTRY_DSN` (optional) | Server error monitoring |
| `ALLOWED_DOMAIN` (optional) | Force the SIWE domain if behind a proxy that rewrites Host |

Smoke-test the deployment: `GET https://<server>/api/health` must return
`{"ok": true, "matchStore": "firestore"}` in production.

---

## 4. Configure the web client

Set in Freebuff **Settings → Environment** (dev) **and** in
`freebuff-deploy env` (production):

| Variable | Purpose |
|---|---|
| `VITE_ESCROW_ADDRESS` | Deployed contract (real-money mode activates when present) |
| `VITE_TREASURY_WALLET_ADDRESS` | Public treasury (display purposes) |
| `VITE_FIREBASE_API_KEY` | Firebase web config (audit #7 R7: moved OUT of the committed `firebase-applet-config.json` — set all `VITE_FIREBASE_*` vars here instead). Cloud profiles/leaderboard are honestly disabled when absent |
| `VITE_FIREBASE_AUTH_DOMAIN` | e.g. `<project>.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | Firebase project ID |
| `VITE_FIREBASE_STORAGE_BUCKET` | e.g. `<project>.appspot.com` |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | From Firebase console → Web app config |
| `VITE_FIREBASE_APP_ID` | From Firebase console → Web app config |
| `VITE_FIRESTORE_DATABASE_ID` | The Firestore database ID (was previously leaked by the committed config file) |
| `VITE_ORACLE_WALLET_ADDRESS` | Public oracle address (display purposes) |
| `VITE_CHAIN_ID` | `80002` (Amoy rehearsal — the default) / `137` (mainnet, checklist-gated) |
| `VITE_FAUCET_URL` (testnet) | MockUSDT/feucet link shown to players on Amoy |
| `VITE_GAME_SERVER_URL` | e.g. `https://api.yourdomain.com` (no trailing slash) |
| `VITE_WALLETCONNECT_PROJECT_ID` | From cloud.reown.com — needed for mobile wallets |
| `VITE_SENTRY_DSN` (optional) | Client error monitoring |

**Reown works without a domain.** The Project ID is a public client value (not a
secret), so you can register at cloud.reown.com and create the project today —
no domain needed. Leave the project's *Allowed Domains* list empty: the ID then
works from any origin (localhost, the preview sandbox, anywhere), which is
needed for the Amoy rehearsal. After the production domain is bought, just add
it under Project → Domains in the Reown dashboard — the same Project ID keeps
working, with zero code or env changes. WalletConnect is optional anyway: on
desktop, users connect via injected providers (MetaMask/Rabby) without it; it
only adds mobile-wallet support.

---

## 5. Legal review (hard gate)

The pack in `src/pages/LegalPage.tsx` + `EligibilityGate.tsx` is a structured
template. Before enabling real-money mode:

1. An attorney reviews ToS / Privacy / Risk Disclosure for your entity's jurisdiction
2. Replace `[OPERATOR LEGAL ENTITY]`, `[OPERATOR JURISDICTION]`, `[OPERATOR PRIVACY CONTACT]`
3. Review the `RESTRICTED_JURISDICTIONS` list; enable edge geo-blocking at the
   hosting/CDN layer (client gate is UX only — the server must also refuse
   sessions from blocked regions)
4. Confirm skill-competition legality in target markets

---

## 6. Real-Money Readiness Checklist

- [ ] Contract deployed, verified on Polygonscan, constructor args correct
- [ ] `ESCROW_RPC_URL` set on the server (activates the on-chain deposit gate — commit/target/result refuse to run unless the escrow holds both stakes)
- [ ] Oracle key generated, stored as server secret, public address set in contract
- [ ] Game server live, `/api/health` shows `matchStore: "firestore"`
- [ ] `ESCROW_ADDRESS` on server **matches** `VITE_ESCROW_ADDRESS` on client
- [ ] All `VITE_*` env vars set in production deploy env
- [ ] Legal docs reviewed + placeholders replaced; geo-blocking at edge active
- [ ] Sentry (client + server) receiving test events
- [ ] End-to-end test with real wallet on **Polygon Amoy testnet first**: approve → createDuel → joinDuel → play → settleDuel; verify winner receives 98% and treasury 2%
- [ ] `refundTimeoutMatch` verified: create a duel, wait 30 minutes (MATCH_TIMEOUT), refund works
- [ ] Rollback plan: keep `VITE_ESCROW_ADDRESS` unset → app reverts to honest practice-only mode instantly
