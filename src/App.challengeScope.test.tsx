/**
 * M27 closure — a challenge target must not leak into the NEXT duel.
 *
 * `App` only wrote `activeOpponentAddress` when the argument was not
 * `undefined`, and nothing ever cleared it. So after a friend challenge (or
 * accepting one), the next ORDINARY duel was queued with the stale address:
 * the server reserved the match for the previous friend, the player sat in
 * "waiting" until the 90-second timeout, and could not match a stranger at all
 * until a full page reload. A one-shot value must behave like one.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const CHALLENGER = '0x' + 'ab'.repeat(20);

vi.mock('./pages/HomePage', () => ({
  HomePage: ({ onNavigate }: { onNavigate: (p: string) => void }) => (
    <button data-testid="go-lobby" onClick={() => onNavigate('/lobby')}>
      lobby
    </button>
  ),
}));

vi.mock('./pages/LobbyPage', () => ({
  LobbyPage: ({ onNavigate }: { onNavigate: (...a: unknown[]) => void }) => (
    <div>
      <button
        data-testid="challenge"
        onClick={() => onNavigate('/game/reaction', 'Friend', 1, undefined, CHALLENGER)}
      >
        challenge
      </button>
      <button data-testid="play" onClick={() => onNavigate('/game/reaction', undefined, 1)}>
        play
      </button>
    </div>
  ),
}));

vi.mock('./pages/ReactionGamePage', () => ({
  ReactionGamePage: ({
    challengeOpponent,
    onNavigate,
  }: {
    challengeOpponent?: string;
    onNavigate: (p: string) => void;
  }) => (
    <div>
      <span data-testid="target">{challengeOpponent ?? ''}</span>
      <button data-testid="back" onClick={() => onNavigate('/lobby')}>
        back
      </button>
    </div>
  ),
}));

vi.mock('./pages/DashboardPage', () => ({ DashboardPage: () => null }));
vi.mock('./pages/ProfilePage', () => ({ ProfilePage: () => null }));
vi.mock('./pages/LegalPage', () => ({ LegalPage: () => null }));
vi.mock('./components/BottomNav', () => ({ BottomNav: () => null }));
vi.mock('./components/EligibilityGate', () => ({ EligibilityGate: () => null }));
vi.mock('./components/IdentityLockBanner', () => ({ IdentityLockBanner: () => null }));

import App from './App';

describe('the challenge target is scoped to one navigation (audit M27 closure)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
  });

  afterEach(() => {
    cleanup();
  });

  it('does not carry a challenge target into the next ordinary duel', async () => {
    render(<App />);

    // The route chunks are lazy: let the first one resolve.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('go-lobby'));
      await Promise.resolve();
    });

    // A friend challenge carries the address.
    await act(async () => {
      fireEvent.click(screen.getByTestId('challenge'));
      await Promise.resolve();
    });
    expect(screen.getByTestId('target').textContent).toBe(CHALLENGER);

    // Back to the lobby, then play an ORDINARY duel.
    await act(async () => {
      fireEvent.click(screen.getByTestId('back'));
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('play'));
      await Promise.resolve();
    });

    expect(screen.getByTestId('target').textContent).toBe('');
  });
});
