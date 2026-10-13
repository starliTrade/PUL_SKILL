/**
 * Wipe the Firestore emulator before the suite runs.
 *
 * Audit 2026-10-13 (found while chasing the "joiner revert"): the E2E signs in
 * with anvil's deterministic accounts, and those accounts are the SAME on every
 * run. So a match created by a previous run is still in the store, and the
 * server's `/api/queue` — which returns the caller's waiting OR active match —
 * handed the new run a match that had already settled. The symptoms looked like
 * app bugs: the creator's page stuck on "Waiting for a ranked opponent", and
 * `createDuel` reverting because the match id already existed on-chain.
 *
 * A test suite that reuses identities must reset the state those identities
 * accumulated.
 */
import { request } from '@playwright/test';

const EMULATOR = process.env.FIRESTORE_EMULATOR_HOST ?? '127.0.0.1:8081';
const PROJECT = process.env.GCLOUD_PROJECT ?? 'demo-pulsar';

export default async function globalSetup(): Promise<void> {
  const ctx = await request.newContext();
  try {
    const res = await ctx.delete(
      `http://${EMULATOR}/emulator/v1/projects/${PROJECT}/databases/(default)/documents`
    );
    // A missing emulator is not a suite failure — the API may be running in
    // memory mode — but it IS worth saying out loud.
    if (!res.ok()) {
      console.warn(`[e2e] could not reset the emulator (${res.status()}); state may leak between runs`);
    }
  } catch (err) {
    console.warn(`[e2e] emulator not reachable for the reset: ${String(err).slice(0, 80)}`);
  } finally {
    await ctx.dispose();
  }
}
