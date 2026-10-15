/**
 * The responsible-gaming UI (plan item 11.3 / G3).
 *
 * The API existed and nothing could reach it — a control a player cannot find is
 * not a control. These tests pin the SURFACE, and specifically the two things
 * the wording has to get right:
 *
 *   * lowering or clearing a limit takes effect now; RAISING waits. A player who
 *     sets a limit and sees it not apply will conclude the control is broken.
 *   * self-exclusion cannot be lifted early, and the UI says so BEFORE the player
 *     commits.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string, vars?: Record<string, string>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
    currentLanguage: 'en',
    langInfo: { code: 'en', name: 'English', nativeName: 'English', flag: '🇬🇧', dir: 'ltr' },
    setLanguage: vi.fn(),
  }),
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { connected: true, address: '0xabc', fullAddress: '0xabc' },
  }),
}));

const session = { address: '0xabc', token: 't', issuedAt: Date.now() };
vi.mock('../lib/gameServerClient', () => ({
  loadServerSession: () => session,
  fetchLimits: vi.fn(),
  setDepositLimit: vi.fn(),
  selfExclude: vi.fn(),
  coolOff: vi.fn(),
}));

import { ResponsibleGamingCard } from '../components/ResponsibleGamingCard';
import { fetchLimits, setDepositLimit, selfExclude } from '../lib/gameServerClient';

const base = {
  depositLimit: null,
  pendingLimit: null,
  pendingLimitAt: null,
  excludedUntil: 0,
  cooloffUntil: 0,
  selfExcluded: false,
  coolingOff: false,
};

beforeEach(() => {
  vi.mocked(fetchLimits).mockResolvedValue({ ...base });
  vi.mocked(setDepositLimit).mockResolvedValue({ ...base, depositLimit: 1 });
  vi.mocked(selfExclude).mockResolvedValue({ ...base, selfExcluded: true, excludedUntil: 9e9 });
});
afterEach(() => cleanup());

describe('the responsible-gaming card', () => {
  it('renders the three controls', async () => {
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('depositLimit')).toBeTruthy());
    expect(screen.getByText('selfExclusion')).toBeTruthy();
    expect(screen.getByText('takeAnHourOff')).toBeTruthy();
  });

  it('says that RAISING a limit takes effect later, not now', async () => {
    // The server scheduled a raise. The UI must not imply it applied.
    vi.mocked(fetchLimits).mockResolvedValue({
      ...base,
      depositLimit: 1,
      pendingLimit: 10,
      pendingLimitAt: Date.now() + 86400_000,
    });
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText(/limitRaisePending/)).toBeTruthy());
    // And the CURRENT limit is still the one shown as active.
    expect(screen.getByText('$1')).toBeTruthy();
  });

  it('clearing a limit calls the API with null', async () => {
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('noLimit')).toBeTruthy());
    fireEvent.click(screen.getByText('noLimit'));
    await waitFor(() => expect(setDepositLimit).toHaveBeenCalledWith(session, null));
  });

  it('setting a limit calls the API with the value', async () => {
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('$5')).toBeTruthy());
    fireEvent.click(screen.getByText('$5'));
    await waitFor(() => expect(setDepositLimit).toHaveBeenCalledWith(session, 5));
  });

  it('warns that self-exclusion cannot be lifted early, BEFORE committing', async () => {
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('selfExclusionHint')).toBeTruthy());
    // The hint is on screen before any click — the player reads it first.
    expect(screen.getByText('selfExclusionHint')).toBeTruthy();
    fireEvent.click(screen.getByText('24h'));
    await waitFor(() => expect(selfExclude).toHaveBeenCalledWith(session, 86400));
  });

  it('shows an active self-exclusion as a notice, not as a setting', async () => {
    vi.mocked(fetchLimits).mockResolvedValue({ ...base, selfExcluded: true, excludedUntil: 9e9 });
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('selfExcludedNotice')).toBeTruthy());
  });

  it('a failed read does NOT look like "no limits set"', async () => {
    // The distinction matters: telling a player their controls are gone when the
    // server is merely unreachable is worse than saying nothing.
    vi.mocked(fetchLimits).mockRejectedValue(new Error('offline'));
    render(<ResponsibleGamingCard />);
    await waitFor(() => expect(screen.getByText('limitsUnavailable')).toBeTruthy());
  });
});
