/**
 * H22b — disconnecting the wallet must revoke the SERVER session.
 *
 * H22 added `POST /api/auth/logout` and `auth.session_jti` so a stolen token
 * cannot stay valid for its full 2h TTL. Nothing in the client calls it: when a
 * player disconnects their wallet the local session is dropped, but the bearer
 * token stays valid server-side until it expires.
 *
 * This is the third instance of the same shape found in the phase-4 review —
 * H17b (contract `withdraw()`, no client path), H15b (manager
 * `identityLockedReason`, no UI), and this. The audit reviews each layer
 * separately, so "fixed in one layer, no path from the other" is invisible to
 * it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const SESSION_KEY = 'pulsar.server.session.v1';
const ADDRESS = '0x' + '11'.repeat(20);

vi.mock('./firebase', () => ({ getDb: () => null }));

import { logoutServerSession, loadServerSession } from './gameServerClient';
import { realWeb3Manager } from './realWeb3';

describe('server session logout (audit H22b)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ address: ADDRESS, token: 'tok-123', issuedAt: Date.now() }),
    );
    fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('revokes the token server-side', async () => {
    await logoutServerSession();

    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/auth/logout'));
    expect(call, 'the client never called /api/auth/logout').toBeDefined();
    expect(String(call?.[1]?.method ?? 'POST').toUpperCase()).toBe('POST');
  });

  it('sends the bearer token so the server knows which session to revoke', async () => {
    await logoutServerSession();

    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/auth/logout'));
    const headers = (call?.[1]?.headers ?? {}) as Record<string, string>;
    const auth = headers.Authorization ?? headers.authorization ?? '';
    expect(auth).toContain('tok-123');
  });

  it('clears the local session', async () => {
    await logoutServerSession();
    expect(loadServerSession()).toBeNull();
  });

  it('clears the local session even when the server call fails', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));

    await logoutServerSession();

    // The player asked to disconnect; a network failure must not leave them
    // holding a session they cannot get rid of.
    expect(loadServerSession()).toBeNull();
  });

  it('disconnecting the wallet revokes the session', async () => {
    // The actual bug was that NOTHING called the endpoint. Testing
    // `logoutServerSession` in isolation would not have caught it — this is the
    // wiring, and it is the part that was missing.
    realWeb3Manager.disconnect();

    await vi.waitFor(() => {
      const called = fetchMock.mock.calls.some((c) => String(c[0]).includes('/api/auth/logout'));
      expect(called, 'disconnect() never called /api/auth/logout').toBe(true);
    });

    expect(loadServerSession()).toBeNull();
  });

  it('does nothing when there is no session', async () => {
    localStorage.clear();

    await logoutServerSession();

    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/auth/logout'))).toHaveLength(0);
  });
});
