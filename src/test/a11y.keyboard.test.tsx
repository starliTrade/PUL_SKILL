/**
 * Plan items 8.6 and 8.11 — keyboard operation.
 *
 * 8.6: the language selector opened on click only. A keyboard user could not
 * open it, could not move between languages, and could not close it.
 *
 * 8.11: the game's target was a pointer-only element — the whole game was
 * unplayable without a mouse or a touch screen.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import React from 'react';

const setLanguage = vi.fn();
vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) => key,
    currentLanguage: 'en',
    langInfo: { code: 'en', name: 'English', nativeName: 'English', flag: '🇬🇧', dir: 'ltr' },
    setLanguage,
  }),
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playClick: vi.fn(), playTick: vi.fn(), playGo: vi.fn(), playHit: vi.fn(),
    playWin: vi.fn(), playLoss: vi.fn(), playError: vi.fn(),
  },
}));

import { LanguageSelector } from '../components/LanguageSelector';

describe('the language selector is operable by keyboard (plan item 8.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    cleanup();
  });

  it('announces its popup state', () => {
    render(<LanguageSelector />);
    const trigger = screen.getByRole('button', { name: 'selectLanguageLabel' });
    expect(trigger.getAttribute('aria-haspopup')).toBe('listbox');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens with ArrowDown and moves through the options', async () => {
    render(<LanguageSelector />);
    const trigger = screen.getByRole('button', { name: 'selectLanguageLabel' });

    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 5));
    });

    const options = screen.getAllByRole('option');
    expect(options.length).toBeGreaterThan(1);
    // Focus landed on the currently selected option.
    expect(document.activeElement).toBe(options[0]);

    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(options[1]);

    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'End' });
    expect(document.activeElement).toBe(options[options.length - 1]);

    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Home' });
    expect(document.activeElement).toBe(options[0]);
  });

  it('marks the selected option and selects on click', async () => {
    render(<LanguageSelector />);
    fireEvent.click(screen.getByRole('button', { name: 'selectLanguageLabel' }));
    const options = screen.getAllByRole('option');
    expect(options[0].getAttribute('aria-selected')).toBe('true');

    fireEvent.click(options[1]);
    expect(setLanguage).toHaveBeenCalledWith(options[1].textContent?.includes('فارسی') ? 'fa' : expect.any(String));
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    render(<LanguageSelector />);
    const trigger = screen.getByRole('button', { name: 'selectLanguageLabel' });
    fireEvent.click(trigger);
    expect(screen.getByRole('listbox')).toBeTruthy();

    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
