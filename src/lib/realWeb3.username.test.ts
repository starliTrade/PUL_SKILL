/**
 * Audit M12 (2026-10-13) — the client must use the server's registry endpoint.
 *
 * `GET /api/username/{name}` existed, was tested, and had no caller: the client
 * read the public `usernames` collection directly, so the authoritative,
 * rate-limited path protected nothing.
 *
 * Audit M-04 (2026-10-22): there is no longer a Firestore fallback. `usernames/*`
 * and `users/*` are closed to clients (M-19), so the old fallback threw and its
 * `catch` returned `available: true` — the app called a taken name free and the
 * claim only failed on submit. A fact about other people's data has no offline
 * answer, so an unreachable server now says "could not check".
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const h = vi.hoisted(() => ({
  checkUsername: vi.fn(),
  ensureSession: vi.fn(),
  // Plan item 11.3/G2: the game page records the eligibility attestation
  confirmEligibility: vi.fn(async () => undefined),
  getDoc: vi.fn(),
}));

vi.mock('./gameServerClient', () => ({
  checkUsername: (...a: unknown[]) => h.checkUsername(...(a as [])),
  ensureSession: (...a: unknown[]) => h.ensureSession(...(a as [])),
  logoutServerSession: vi.fn(),
}));

vi.mock('./firebase', () => ({ getDb: () => ({}), syncToFirestore: async () => undefined }));

vi.mock('firebase/firestore', () => ({
  doc: vi.fn(() => ({ __doc: true })),
  getDoc: (...a: unknown[]) => h.getDoc(...(a as [])),
  setDoc: vi.fn(),
  deleteDoc: vi.fn(),
  collection: vi.fn(() => ({})),
  query: vi.fn(() => ({})),
  where: vi.fn(() => ({})),
  orderBy: vi.fn(),
  limit: vi.fn(),
  getDocs: vi.fn(async () => ({ empty: true, forEach: () => {} })),
  onSnapshot: vi.fn(),
}));

import { realWeb3Manager } from './realWeb3';

const ME = '0x' + '11'.repeat(20);

describe('username availability goes through the server (audit M12)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    h.ensureSession.mockResolvedValue({ token: 't', address: ME });
  });

  it('asks the server and reports a taken name', async () => {
    h.checkUsername.mockResolvedValue({ available: false, username: 'taken', taken: true });

    const res = await realWeb3Manager.checkUsernameAvailability('taken', ME);

    expect(h.checkUsername).toHaveBeenCalled();
    expect(res.available).toBe(false);
    // The direct Firestore read must not have been needed.
    expect(h.getDoc).not.toHaveBeenCalled();
  });

  it('reports a free name from the server', async () => {
    h.checkUsername.mockResolvedValue({ available: true, username: 'free' });
    const res = await realWeb3Manager.checkUsernameAvailability('free', ME);
    expect(res.available).toBe(true);
    expect(h.getDoc).not.toHaveBeenCalled();
  });

  it('does NOT claim a name is free when the server cannot be reached', async () => {
    h.ensureSession.mockRejectedValue(new Error('no wallet'));
    const res = await realWeb3Manager.checkUsernameAvailability('offlinename', ME);
    expect(res.available).toBe(false);
    expect(res.error).toMatch(/could not check/i);
    // And it certainly does not read the (now closed) collection.
    expect(h.getDoc).not.toHaveBeenCalled();
  });

  it('still rejects a malformed name without asking anyone', async () => {
    const res = await realWeb3Manager.checkUsernameAvailability('no spaces!', ME);
    expect(res.available).toBe(false);
    expect(h.checkUsername).not.toHaveBeenCalled();
  });
});
