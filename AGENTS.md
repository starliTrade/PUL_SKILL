# Base44 Dev Environment — PULSAR Duels

## Stack
- **Frontend**: Vite 6 + React 19 + TypeScript + Tailwind v4. Dev server on port 3000 (`npm run dev` / `bun run dev`).
- **Backend**: FastAPI (Python) in `api/`. uvicorn with `--reload` on port 8000.
- **Persistence**: Firestore in production; **in-memory fallback** for local dev (no Firebase creds needed to boot).

## Running
```
docker compose -f docker-compose.base44.yml up -d --build
```
- Frontend preview: port 3000. Backend API: port 8000.
- The two are on **separate origins**; the frontend reaches the API via `VITE_GAME_SERVER_URL` (set in compose to the API's public URL). Auth is bearer-token (SIWE), not cookies, so cross-origin is fine.

## Required env
- `ORACLE_SIGNING_SECRET` — **required at boot**. `api/auth.py` and `api/match_engine.py` raise `RuntimeError` without it. Delivered via `/run/base44/app.env` (platform secret store). A generated dev placeholder is fine for local play; rotate for production.

## Optional env (all degrade gracefully when absent)
- `VITE_WALLETCONNECT_PROJECT_ID` — falls back to a hardcoded default project id if unset.
- `VITE_FIREBASE_*` / `VITE_FIRESTORE_DATABASE_ID` — cloud features disabled, app runs local-only with a console warning.
- `VITE_GAME_SERVER_URL` — when unset the app stays in **practice mode** (bot flow); real-money duels need it.
- `VITE_ESCROW_ADDRESS` / `VITE_PAYMENT_TOKEN_ADDRESS` / `VITE_ORACLE_WALLET_ADDRESS` / `VITE_TREASURY_WALLET_ADDRESS` — on-chain escrow config; unset in dev (money path off).
- `ESCROW_ADDRESS` + `ESCROW_RPC_URL` (server) — both must be set together to enable the on-chain deposit gate; unset in dev.

## Quirks
- `api/` modules import each other as **top-level packages** (`import auth`, `from match_engine import ...`). The backend working dir must be `api/` and `PYTHONPATH` must include it (set in compose) for uvicorn `--reload` subprocesses to resolve imports.
- A prod-like deployment gate triggers on `PULSAR_ENV=prod*` or cloud deploy markers (`K_SERVICE`, `RENDER`, etc.) and then requires a fuller env set. Local dev leaves `PULSAR_ENV` unset, so the gate stays off.
- The frontend uses `npm` in compose (the repo ships `bun.lock`, but `npm install` against `package.json` works equivalently for the Vite dev server).

## Verifying
- `curl localhost:8000/api/health` → `{"status":"ok",...}`
- `curl localhost:3000` → serves the Vite app HTML.
- The app renders the home page in practice mode without any wallet or Firebase credentials.
