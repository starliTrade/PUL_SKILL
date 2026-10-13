/**
 * Plan item 8.4 — the modals must behave like dialogs.
 *
 * Before this they were plain `<div>` overlays: no `role="dialog"`, no
 * `aria-modal`, no focus trap, and Escape did nothing. A keyboard user could
 * tab out of the dialog into the page behind it; a screen reader announced the
 * dialog's contents as ordinary page content.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import React from 'react';

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) => key,
    currentLanguage: 'en',
    langInfo: { code: 'en', name: 'English', nativeName: 'English', flag: '🇬🇧', dir: 'ltr' },
    setLanguage: vi.fn(),
  }),
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playClick: vi.fn(), playTick: vi.fn(), playGo: vi.fn(), playHit: vi.fn(),
    playWin: vi.fn(), playLoss: vi.fn(), playError: vi.fn(),
  },
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { connected: false, address: '', balance: 0 },
    stats: { balance: 0, balanceUnknown: true },
    history: [],
  }),
}));

import { DuelCertificateModal } from '../components/DuelCertificateModal';
import { FriendChallengeModal } from '../components/FriendChallengeModal';

const MATCH = {
  id: 'a'.repeat(32),
  game: 'reaction',
  result: 'win' as const,
  entryFee: 1,
  prize: 1.96,
  opponentTime: 300,
  yourTime: 200,
  timestamp: Date.now(),
  hash: '0x' + 'cd'.repeat(32),
};

describe('modals are dialogs (plan item 8.4)', () => {
  afterEach(() => {
    cleanup();
  });

  it('the certificate modal exposes role=dialog, aria-modal and a name', () => {
    render(<DuelCertificateModal isOpen onClose={() => {}} match={MATCH} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    // The accessible name comes from aria-labelledby → the visible title.
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy();
    expect(screen.getByRole('dialog').textContent).toContain('certificateTitleWin');
  });

  it('Escape closes the certificate modal', () => {
    const onClose = vi.fn();
    render(<DuelCertificateModal isOpen onClose={onClose} match={MATCH} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Escape closes the friend-challenge modal', () => {
    const onClose = vi.fn();
    render(
      <FriendChallengeModal isOpen onClose={onClose} selectedStake={1} onStartDuel={() => {}} />
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('moves focus into the dialog when it opens', () => {
    render(<DuelCertificateModal isOpen onClose={() => {}} match={MATCH} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('keeps Tab inside the dialog (focus trap)', () => {
    render(<DuelCertificateModal isOpen onClose={() => {}} match={MATCH} />);
    const dialog = screen.getByRole('dialog');
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')
    );
    expect(focusables.length).toBeGreaterThan(1);

    // Tab from the LAST focusable must wrap to the FIRST, not escape.
    focusables[focusables.length - 1].focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(focusables[0]);

    // Shift+Tab from the FIRST must wrap to the LAST.
    focusables[0].focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(focusables[focusables.length - 1]);
  });

  it('restores focus to the previously focused element on close', () => {
    const opener = document.createElement('button');
    opener.textContent = 'open';
    document.body.appendChild(opener);
    opener.focus();

    const { unmount } = render(<DuelCertificateModal isOpen onClose={() => {}} match={MATCH} />);
    expect(document.activeElement).not.toBe(opener);

    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
