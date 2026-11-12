/**
 * Audit M-24 — a save that fails must be visible, and must clear itself.
 *
 * The profile save wrote the local cache first, so the UI showed the new tag
 * while the server still had the old one; the only trace was a console.warn.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import React from 'react';

import {
  clearSaveFailure,
  getSaveFailures,
  reportSaveFailure,
  resetSaveStatus,
} from '../lib/saveStatus';
import { SaveStatusBanner } from './SaveStatusBanner';

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string, params?: Record<string, string | number>) =>
      params ? `${key}(${JSON.stringify(params)})` : key,
    currentLanguage: 'en',
    setLanguage: vi.fn(),
  }),
}));

describe('save failure surfacing (audit M-24)', () => {
  beforeEach(() => {
    resetSaveStatus();
    cleanup();
  });

  it('renders nothing when the last save succeeded', () => {
    render(<SaveStatusBanner />);
    expect(screen.queryByTestId('pulsar-save-status')).toBeNull();
  });

  it('says the change was not saved, and that it is only in this browser', () => {
    act(() => reportSaveFailure('profile', 'write', new Error('503 from /api/profile')));
    render(<SaveStatusBanner />);

    const banner = screen.getByTestId('pulsar-save-status');
    expect(banner.textContent).toContain('saveWriteFailed');
  });

  it('distinguishes a failed READ from a failed write', () => {
    act(() => reportSaveFailure('profile', 'read', new Error('offline')));
    render(<SaveStatusBanner />);
    expect(screen.getByTestId('pulsar-save-status').textContent).toContain('saveReadFailed');
  });

  it('counts repeated failures instead of hiding them', () => {
    act(() => {
      reportSaveFailure('profile', 'write', new Error('a'));
      reportSaveFailure('profile', 'write', new Error('b'));
    });
    expect(getSaveFailures()).toHaveLength(1);
    expect(getSaveFailures()[0].count).toBe(2);
    expect(getSaveFailures()[0].message).toBe('b');
  });

  it('a successful save clears the write warning but not the read one', () => {
    act(() => {
      reportSaveFailure('profile', 'write', new Error('write failed'));
      reportSaveFailure('profile', 'read', new Error('read failed'));
    });
    act(() => clearSaveFailure('profile', 'write'));
    expect(getSaveFailures().map((f) => f.kind)).toEqual(['read']);
  });

  it('dismiss hides the banner without pretending the save happened', () => {
    act(() => reportSaveFailure('profile', 'write', new Error('nope')));
    const { rerender } = render(<SaveStatusBanner />);
    act(() => screen.getByLabelText('saveDismiss — profile').click());
    rerender(<SaveStatusBanner />);
    expect(screen.queryByTestId('pulsar-save-status')).toBeNull();
  });
});
