/**
 * Audit M-18 — the update prompt is a conversation, not a takeover.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import React from 'react';

import {
  isUpdateWaiting,
  onWorkerWaiting,
  resetSwUpdate,
  watchRegistration,
} from '../lib/swUpdate';
import { UpdateBanner } from './UpdateBanner';

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) => key,
    currentLanguage: 'en',
    setLanguage: vi.fn(),
  }),
}));

function fakeWorker() {
  return { postMessage: vi.fn() } as unknown as ServiceWorker;
}

describe('the update banner (audit M-18)', () => {
  beforeEach(() => {
    resetSwUpdate();
    cleanup();
  });

  it('stays hidden when no new version is waiting', () => {
    render(<UpdateBanner />);
    expect(screen.queryByTestId('pulsar-update-available')).toBeNull();
  });

  it('tells the player to update when THEY are ready, and only posts on click', () => {
    const worker = fakeWorker();
    act(() => onWorkerWaiting(worker));
    render(<UpdateBanner />);

    expect(screen.getByTestId('pulsar-update-available').textContent).toContain(
      'updateAvailable',
    );
    // Merely being offered the update must not swap the worker.
    expect(worker.postMessage).not.toHaveBeenCalled();

    act(() => screen.getByText('updateNow').click());
    expect(worker.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
  });

  it('does not fire twice if the button is double-clicked', () => {
    const worker = fakeWorker();
    act(() => onWorkerWaiting(worker));
    render(<UpdateBanner />);
    act(() => screen.getByText('updateNow').click());
    act(() => screen.getByText('updateNow').click());
    expect(worker.postMessage).toHaveBeenCalledTimes(1);
  });
});

describe('registration wiring (audit M-18)', () => {
  beforeEach(() => resetSwUpdate());

  it('does not announce an update on a FIRST install (nothing to replace)', () => {
    const listeners: Record<string, () => void> = {};
    let installed: (() => void) | null = null;
    const registration = {
      waiting: null,
      installing: {
        state: 'installing',
        addEventListener: (_t: string, fn: () => void) => {
          installed = fn;
        },
      },
      addEventListener: (type: string, fn: () => void) => {
        listeners[type] = fn;
      },
    };

    watchRegistration(registration as never, false, () => undefined);
    // Pretend the worker finishes installing.
    (registration.installing as { state: string }).state = 'installed';
    installed?.();

    expect(isUpdateWaiting()).toBe(false);
  });

  it('announces the update when a LATER build installs over a live page', () => {
    const listeners: Record<string, () => void> = {};
    let installed: (() => void) | null = null;
    const waiting = { postMessage: vi.fn() };
    const registration = {
      waiting: null as unknown,
      installing: {
        state: 'installing',
        addEventListener: (_t: string, fn: () => void) => {
          installed = fn;
        },
      },
      addEventListener: (type: string, fn: () => void) => {
        listeners[type] = fn;
      },
    };

    watchRegistration(registration as never, true, () => undefined);
    listeners.updatefound(); // the registration discovers the download
    const installing = registration.installing as { state: string };
    installing.state = 'installed';
    (registration as { waiting: unknown }).waiting = waiting;
    installed?.();

    expect(isUpdateWaiting()).toBe(true);
  });

  it('reloads exactly once on controllerchange', () => {
    const listeners: Record<string, () => void> = {};
    const registration = {
      waiting: null,
      installing: null,
      addEventListener: (type: string, fn: () => void) => {
        listeners[type] = fn;
      },
    };
    const onControllerChange = vi.fn();
    watchRegistration(registration as never, true, onControllerChange);
    listeners.controllerchange();
    expect(onControllerChange).toHaveBeenCalledTimes(1);
  });
});
