/**
 * Audit M-07 (2026-10-22) — one deposit prompt per duel, across tabs.
 *
 * The audit's example was the touch tap (`touchend` + synthetic `click`), which
 * is guarded by a ref. The guard it did not have is the one that costs money: the
 * escrow deposit phase (`approve` → `createDuel` / `joinDuel`). A ref only
 * protects ONE tab, and it dies on reload. Two tabs on the same browser, or a
 * reload mid-flow, gave two wallet prompts for the same duel; and because both
 * writers target the same `matchId`, the loser of the race got a contract revert
 * ("Match already exists"), which the code surfaced as an error even though the
 * deposit had succeeded.
 *
 * A SERVER idempotency key cannot fix this: `createDuel` is a chain write, and
 * the server cannot un-send it. What does fix it is the chain itself — the
 * contract already refuses a second `createDuel` for the same id — plus a
 * cross-tab lease so the second tab does not even prompt, and reading the revert
 * as "someone already did this" rather than as a failure.
 *
 * This module is the lease. `localStorage` is the only store shared by tabs, and
 * a lease must expire on its own: a tab that is closed mid-deposit must not lock
 * the player out of their own duel. `storage` events are not relied on — the
 * read-then-write race is closed by re-reading, not by listening.
 */

const PREFIX = 'pulsar.depositLock.';

export interface DepositLease {
  matchId: string;
  token: string;
  expiresAt: number;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // Private mode / disabled storage: fall back to no locking rather than
    // refusing to deposit at all.
    return null;
  }
}

function newToken(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch {
    /* fall through */
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function read(matchId: string): DepositLease | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(PREFIX + matchId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DepositLease>;
    if (typeof parsed.token !== 'string' || typeof parsed.expiresAt !== 'number') return null;
    return { matchId, token: parsed.token, expiresAt: parsed.expiresAt };
  } catch {
    return null;
  }
}

/**
 * Try to take the deposit lease for `matchId`.
 *
 * Returns the lease when the caller may proceed, or `null` when another tab
 * holds a live one. `ttlMs` must cover a wallet prompt plus a mined transaction;
 * it is deliberately generous because an expired lease is recoverable (the
 * chain still refuses the duplicate) while a stuck lease is not.
 */
export function acquireDepositLease(matchId: string, ttlMs = 5 * 60_000): DepositLease | null {
  const store = storage();
  if (!store) return { matchId, token: newToken(), expiresAt: Date.now() + ttlMs };

  const existing = read(matchId);
  const now = Date.now();
  if (existing && existing.expiresAt > now) {
    // Live lease held by someone else (another tab, or this tab's earlier flow
    // that never released). Do NOT prompt a second wallet.
    return null;
  }
  const lease: DepositLease = { matchId, token: newToken(), expiresAt: now + ttlMs };
  try {
    store.setItem(PREFIX + matchId, JSON.stringify({ token: lease.token, expiresAt: lease.expiresAt }));
  } catch {
    return lease; // storage full: still let THIS tab deposit
  }
  // Re-read: if two tabs wrote in the same tick, the last writer wins and the
  // other must back off. Comparing tokens is the only reliable check because
  // localStorage has no compare-and-swap.
  const after = read(matchId);
  if (after && after.token !== lease.token) return null;
  return lease;
}

/** Extend a lease the caller already holds (called around a slow wallet step). */
export function renewDepositLease(lease: DepositLease, ttlMs = 5 * 60_000): boolean {
  const store = storage();
  if (!store) return true;
  const current = read(lease.matchId);
  if (!current || current.token !== lease.token) return false;
  lease.expiresAt = Date.now() + ttlMs;
  try {
    store.setItem(
      PREFIX + lease.matchId,
      JSON.stringify({ token: lease.token, expiresAt: lease.expiresAt })
    );
  } catch {
    return false;
  }
  return true;
}

/** Release the lease. Only the holder can release it. */
export function releaseDepositLease(lease: DepositLease): void {
  const store = storage();
  if (!store) return;
  const current = read(lease.matchId);
  if (current && current.token !== lease.token) return;
  try {
    store.removeItem(PREFIX + lease.matchId);
  } catch {
    /* nothing to do */
  }
}

/** Test/diagnostic helper: the live lease for a match, if any. */
export function peekDepositLease(matchId: string): DepositLease | null {
  const lease = read(matchId);
  if (!lease) return null;
  return lease.expiresAt > Date.now() ? lease : null;
}
