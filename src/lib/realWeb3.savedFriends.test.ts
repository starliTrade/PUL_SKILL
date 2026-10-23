/**
 * Audit L-02 — a friend list that only exists on the server must still show up.
 *
 * `PUT /api/profile` and `GET /api/profile` store and return `savedFriends`, and
 * the client writes them on every profile save. But `getSavedFriendsList` is
 * synchronous and reads localStorage, so a list saved on another device (or
 * before the SIWE session existed) rendered as "no saved friends" — the data was
 * there, the modal never asked. `refreshSavedFriends` is that ask.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const h = vi.hoisted(() => ({
  saveProfile: vi.fn(),
  fetchProfile: vi.fn(),
}));

vi.mock('./gameServerClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./gameServerClient')>();
  // The real module reads import.meta.env at import time, which is empty under
  // vitest — a configured server is what this file is about, so say so.
  return {
    ...actual,
    gameServerConfigured: () => true,
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

const ME = '0x' + 'aa'.repeat(20);
const FRIEND = '0x' + 'bb'.repeat(20);

function seedSession() {
  localStorage.setItem(
    'pulsar.server.session.v1',
    JSON.stringify({ address: ME, token: 't', issuedAt: Date.now() }),
  );
}

function seedLocal(friends: string[]) {
  localStorage.setItem(
    `pulsar_data_${ME}`,
    JSON.stringify({ address: ME, playerId: 'Me#1', savedFriends: friends }),
  );
}

describe('saved friends reach the modal from the server (audit L-02)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    resetSaveStatus();
  });

  it('shows a friend that exists ONLY on the server, and caches it locally', async () => {
    seedSession();
    seedLocal([]); // fresh device: nothing local
    expect(realWeb3Manager.getSavedFriendsList(ME)).toEqual([]);

    h.fetchProfile.mockResolvedValue({ address: ME, playerId: 'Me#1', savedFriends: [FRIEND] });

    const friends = await realWeb3Manager.refreshSavedFriends(ME);

    expect(h.fetchProfile).toHaveBeenCalledTimes(1);
    expect(friends.map((f) => f.address.toLowerCase())).toEqual([FRIEND]);
    // And the next synchronous read (the one the UI uses) sees it too.
    expect(realWeb3Manager.getSavedFriendsList(ME).map((f) => f.address.toLowerCase())).toEqual([
      FRIEND,
    ]);
  });

  it('never blanks the list when the read fails — it reports the failure', async () => {
    seedSession();
    seedLocal([FRIEND]);
    h.fetchProfile.mockRejectedValue(new Error('503 from /api/profile'));

    const friends = await realWeb3Manager.refreshSavedFriends(ME);

    expect(friends.map((f) => f.address.toLowerCase())).toEqual([FRIEND]);
    expect(getSaveFailures()).toHaveLength(1);
    expect(getSaveFailures()[0]).toMatchObject({ area: 'profile', kind: 'read' });
  });

  it('does not call the server without a session for this address', async () => {
    seedLocal([FRIEND]);
    const friends = await realWeb3Manager.refreshSavedFriends(ME);
    expect(h.fetchProfile).not.toHaveBeenCalled();
    expect(friends.map((f) => f.address.toLowerCase())).toEqual([FRIEND]);
  });

  it('ignores a session that belongs to somebody else', async () => {
    localStorage.setItem(
      'pulsar.server.session.v1',
      JSON.stringify({ address: FRIEND, token: 't', issuedAt: Date.now() }),
    );
    await realWeb3Manager.refreshSavedFriends(ME);
    expect(h.fetchProfile).not.toHaveBeenCalled();
  });

  it('treats an empty server list as a real answer (friends removed elsewhere)', async () => {
    seedSession();
    seedLocal([FRIEND]);
    h.fetchProfile.mockResolvedValue({ address: ME, playerId: 'Me#1', savedFriends: [] });

    const friends = await realWeb3Manager.refreshSavedFriends(ME);

    expect(friends).toEqual([]);
    expect(getSaveFailures()).toEqual([]);
  });
});
