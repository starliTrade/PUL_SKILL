/**
 * Audit M-24 — the profile save path must report a failure to the UI.
 *
 * `saveUserDataAsync` writes the local cache first, so a failed server save is
 * invisible: the player sees the new tag until the next reload, then the old one
 * comes back. This pins that the manager records the failure (and clears it when
 * a later save succeeds) instead of leaving it in `console.warn`.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const h = vi.hoisted(() => ({
  saveProfile: vi.fn(),
  fetchProfile: vi.fn(),
}));

vi.mock('./gameServerClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./gameServerClient')>();
  return {
    ...actual,
    saveProfile: h.saveProfile,
    fetchProfile: h.fetchProfile,
  };
});

vi.mock('./firebase', () => ({
  getDb: () => ({ __db: true }),
  syncToFirestore: async () => undefined,
}));

import { realWeb3Manager } from './realWeb3';
import { getSaveFailures, resetSaveStatus } from './saveStatus';

const ADDRESS = '0x' + 'aa'.repeat(20);

function seedSession() {
  localStorage.setItem(
    'pulsar.server.session.v1',
    JSON.stringify({ address: ADDRESS, token: 't', issuedAt: Date.now() }),
  );
}

const profile = {
  address: ADDRESS,
  playerId: 'Nova#1',
  level: 1,
  xp: 0,
  wins: 0,
  totalMatches: 0,
  savedFriends: [],
  history: [],
};

describe('profile sync failure is observable (audit M-24)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    resetSaveStatus();
    seedSession();
  });

  it('records a failed save and keeps the error text for the caller', async () => {
    h.saveProfile.mockRejectedValue(new Error('503 from /api/profile'));

    await realWeb3Manager.saveUserDataAsync(profile as never);

    expect(getSaveFailures()).toHaveLength(1);
    expect(getSaveFailures()[0]).toMatchObject({ area: 'profile', kind: 'write' });
    expect(getSaveFailures()[0].message).toContain('503');
    expect(realWeb3Manager.lastProfileSyncError).toContain('503');
  });

  it('clears the warning once a save succeeds', async () => {
    h.saveProfile.mockRejectedValueOnce(new Error('offline'));
    await realWeb3Manager.saveUserDataAsync(profile as never);
    expect(getSaveFailures()).toHaveLength(1);

    h.saveProfile.mockResolvedValueOnce({});
    await realWeb3Manager.saveUserDataAsync(profile as never);
    expect(getSaveFailures()).toHaveLength(0);
    expect(realWeb3Manager.lastProfileSyncError).toBe('');
  });

  it('the local cache is still written, so the edit is not lost in this browser', async () => {
    h.saveProfile.mockRejectedValue(new Error('offline'));
    await realWeb3Manager.saveUserDataAsync({ ...profile, playerId: 'Nova#2' } as never);

    const raw = localStorage.getItem(`pulsar_data_${ADDRESS}`);
    expect(raw).toContain('Nova#2');
  });
});
