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
  reportDispute: vi.fn(async () => ({
    ok: true,
    matchId: 'a'.repeat(32),
    disputeId: 'd'.repeat(32),
    status: 'open',
  })),
  fetchDisputeStatus: vi.fn(async () => ({ matchId: 'a'.repeat(32), count: 0, disputes: [] })),
  ensureSession: vi.fn(async () => ({ token: 't', address: '0x' + '11'.repeat(20) })),
  // Plan item 11.3/G2: the game page records the eligibility attestation
  confirmEligibility: vi.fn(async () => undefined),
}));

vi.mock('../lib/gameServerClient', () => ({
  ensureSession: (...a: unknown[]) => h.ensureSession(...(a as [])),
  reportDispute: (...a: unknown[]) => h.reportDispute(...(a as [])),
  fetchDisputeStatus: (...a: unknown[]) => h.fetchDisputeStatus(...(a as [])),
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

  it('shows the status of the report and can re-check it (audit L-09)', async () => {
    h.fetchDisputeStatus.mockResolvedValueOnce({
      matchId: MATCH_ID,
      count: 1,
      disputes: [
        {
          id: 'd'.repeat(32),
          reason: 'timer froze',
          filedAt: 1_700_000_000,
          status: 'resolved',
          resolution: 're-timed, prize stands',
          resolvedAt: 1_700_000_100,
        },
      ],
    });

    render(<DisputeReportButton matchId={MATCH_ID} address={ME} />);
    fireEvent.click(screen.getByTestId('dispute-open'));
    fireEvent.change(screen.getByTestId('dispute-reason'), { target: { value: 'timer froze' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-submit'));
      await Promise.resolve();
      await Promise.resolve();
    });
    await screen.findByTestId('dispute-sent');

    // The report is visible immediately as "open" — the player is not told it
    // is solved when nobody has looked at it yet.
    expect(screen.getByTestId('dispute-status-row').textContent).toContain('disputeStatusOpen');

    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-check'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => expect(h.fetchDisputeStatus).toHaveBeenCalled(), { timeout: 3000 });
    expect(screen.getByTestId('dispute-status-row').textContent).toContain('disputeStatusResolved');
    expect(screen.getByTestId('dispute-status-row').textContent).toContain('re-timed, prize stands');
  });

  it('says so when the status cannot be read, instead of showing a stale status', async () => {
    h.fetchDisputeStatus.mockRejectedValueOnce(new Error('offline'));
    render(<DisputeReportButton matchId={MATCH_ID} address={ME} />);
    fireEvent.click(screen.getByTestId('dispute-open'));
    fireEvent.change(screen.getByTestId('dispute-reason'), { target: { value: 'x y' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-submit'));
      await Promise.resolve();
      await Promise.resolve();
    });
    await screen.findByTestId('dispute-sent');

    await act(async () => {
      fireEvent.click(screen.getByTestId('dispute-check'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(await screen.findByTestId('dispute-check-error')).toBeTruthy();
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
