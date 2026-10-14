/**
 * PULSAR — the E2E suite (plan item 10.1).
 *
 * Deferred from phase 0.10 until there was something worth driving end to end.
 * It runs against the REAL stack, not a dev bypass: the API starts with the
 * escrow address, RPC, oracle key and chain id set, so the fail-closed gates
 * (H6/H7) are exercised exactly as a deployment exercises them. That is already
 * how the phase-10 setup found the ALLOWED_DOMAIN/ALLOWED_HOSTS bug.
 *
 * Prerequisites (the config starts the API itself, but not the infrastructure):
 *   scripts/start_emulator.sh --bg
 *   scripts/start_anvil.sh --bg
 */
import { defineConfig, devices } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';

const FRONTEND_PORT = Number(process.env.PULSAR_E2E_FRONTEND_PORT ?? 3000);
const API_PORT = Number(process.env.PULSAR_E2E_API_PORT ?? 8000);
const BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// The anvil manifest gives the escrow + chain the frontend must point at.
const manifestPath = 'contracts/deployments/local.json';
const manifest = existsSync(manifestPath)
  ? (JSON.parse(readFileSync(manifestPath, 'utf8')) as {
      escrow: string;
      chainId: number;
      token: string;
      treasury: string;
      oracle: string;
    })
  : null;

export default defineConfig({
  testDir: './e2e',
  // NOTE: the store reset lives in `scripts/start_e2e_stack.sh`, BEFORE the
  // API starts. A globalSetup wipe runs AFTER the web server is up, which
  // leaves the durable store's in-process `player_match` cache holding match
  // ids whose documents were just deleted — the exact `409 Match not found`
  // this suite kept hitting. Resetting the store and starting the server must
  // be one ordered step.
  // The stack is shared and stateful (one Firestore emulator, one anvil), so
  // tests run in one worker. Parallelism here would make failures unrepeatable.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      // Regression C4: the mobile path is a different code path (touch events,
      // the bottom sheet, the safe-area insets), not just a smaller window.
      name: 'mobile',
      use: { ...devices['Pixel 7'] },
    },
  ],
  webServer: [
    {
      command: 'bash scripts/start_e2e_stack.sh',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: true,
      timeout: 60_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      command: 'bun run dev',
      url: BASE_URL,
      // FOOTGUN, hit twice while building this suite: `reuseExistingServer`
      // adopts a `vite` left over from an earlier run **with its old env**. The
      // app then silently lacks VITE_ESCROW_ADDRESS (or points at a stale
      // escrow from a previous anvil deploy), and the symptoms look like app
      // bugs — "the escrow is not deployed yet", or `createDuel` reverting with
      // no data. Kill vite (and re-run scripts/start_anvil.sh --bg, which
      // redeploys and rewrites the manifest) whenever the env or the chain
      // changes.
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        VITE_GAME_SERVER_URL: `http://127.0.0.1:${API_PORT}`,
        VITE_CHAIN_ID: String(manifest?.chainId ?? 31337),
        // ALL FOUR are required for real-money mode to be considered configured
        // (`isEscrowConfigured()` needs escrow + treasury + oracle). Setting two
        // of them leaves the lobby saying "the escrow is not deployed yet".
        VITE_ESCROW_ADDRESS: manifest?.escrow ?? '',
        VITE_PAYMENT_TOKEN_ADDRESS: manifest?.token ?? '',
        VITE_TREASURY_WALLET_ADDRESS: manifest?.treasury ?? '',
        VITE_ORACLE_WALLET_ADDRESS: manifest?.oracle ?? '',
        VITE_LOCAL_RPC_URL: 'http://127.0.0.1:8545',
      },
    },
  ],
});
