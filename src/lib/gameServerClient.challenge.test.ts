/**
 * M27 — the client must send the challenged address.
 *
 * The server can only reserve a match for a specific player if it is told who
 * that player is. `queueForMatch` sent `{stake, rttMs}` and nothing else, so
 * every "challenge" was an ordinary queue entry.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { queueForMatch } from './gameServerClient';

const SESSION = { token: 'token', address: '0x' + '11'.repeat(20) } as never;
const OPPONENT = '0x' + 'ab'.repeat(20);

function okResponse(payload: unknown) {
  return {
    status: 200,
    ok: true,
    headers: { get: () => null },
    json: async () => payload,
  };
}

describe('friend challenge queue (audit M27)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => okResponse({ matchId: 'm1', status: 'waiting' }));
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends the challenged address so the server can reserve the match', async () => {
    await queueForMatch(SESSION, 1, 20, OPPONENT);

    const [, init] = fetchMock.mock.calls[0] as [string, { body: string }];
    const body = JSON.parse(init.body) as Record<string, unknown>;
    expect(body.opponent).toBe(OPPONENT);
    expect(body.stake).toBe(1);
  });

  it('omits the opponent for ordinary matchmaking', async () => {
    await queueForMatch(SESSION, 2, 20);

    const [, init] = fetchMock.mock.calls[0] as [string, { body: string }];
    const body = JSON.parse(init.body) as Record<string, unknown>;
    expect(body.opponent).toBeUndefined();
  });
});
