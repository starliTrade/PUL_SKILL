/**
 * Audit 2026-10-13 — `POST /api/dispute` must have a client path.
 *
 * The endpoint existed and was tested, but nothing in `src/` referenced it, so
 * the "user reports a match" feature (phase 6.4 / G8) could not be used by a
 * user. This is the H22b class: a mechanism in one layer with no consumer in
 * another.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const ME = '0x' + '11'.repeat(20);
const MATCH_ID = 'a'.repeat(32);

const h = vi.hoisted(() => ({
  reportDispute: vi.fn(async () => ({ ok: true, matchId: 'a'.repeat(32) })),
  ensureSession: vi.fn(async () => ({ token: 't', address: '0x' + '11'.repeat(20) })),
}));

vi.mock('../lib/gameServerClient', () => ({
  ensureSession: (...a: unknown[]) => h.ensureSession(...(a as [])),
  reportDispute: (...a: unknown[]) => h.reportDispute(...(a as [])),
}));

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    getActiveEip1193Provider: () => ({ request: vi.fn(async () => '0xsig') }),
  },
}));

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({ t: (key: string) => key, currentLanguage: 'en', setLanguage: vi.fn() }),
}));

import { DisputeReportButton } from './DisputeReportButton';

describe('dispute reporting (audit 2026-10-13)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it('sends the report to the server with the match id and the reason', async () => {
    render(<DisputeReportButton matchId={MATCH_ID} address={ME} />);

    fireEvent.click(screen.getByTestId('dispute-open'));
    fireEvent.change(screen.getByTestId('dispute-reason'), {
      target: { value: 'The opponent never appeared and the match still settled.' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-submit'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => {
      expect(h.reportDispute).toHaveBeenCalled();
    }, { timeout: 3000 });

    const [session, matchId, reason] = h.reportDispute.mock.calls[0] as unknown[];
    expect(session).toBeTruthy();
    expect(matchId).toBe(MATCH_ID);
    expect(String(reason)).toContain('never appeared');
    expect(await screen.findByTestId('dispute-sent')).toBeTruthy();
  });

  it('does not send an empty report', async () => {
    render(<DisputeReportButton matchId={MATCH_ID} address={ME} />);
    fireEvent.click(screen.getByTestId('dispute-open'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-submit'));
      await Promise.resolve();
    });
    expect(h.reportDispute).not.toHaveBeenCalled();
  });
});
