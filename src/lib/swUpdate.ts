/**
 * Audit M-18 (2026-10-22) — a new build waits for the player, it does not take
 * over underneath them.
 *
 * The old worker called `skipWaiting()` during install, so the moment a deploy
 * landed the new worker activated, deleted the previous cache, and the open tab
 * (still running the old chunks) asked for an asset that no longer existed. It
 * got the cached index.html back and rendered a blank page — in the lobby, in a
 * duel, wherever the player happened to be.
 *
 * Now the worker waits. This module is the small handshake: the registration code
 * hands us the waiting worker, the banner asks the player, and only then do we
 * post SKIP_WAITING and reload once.
 */

type Listener = () => void;

const listeners = new Set<Listener>();
let waiting: ServiceWorker | null = null;
let updateRequested = false;

function emit(): void {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      // A broken listener must not stop the update handshake.
    }
  });
}

/** Called by the registration code when a worker is installed and waiting. */
export function onWorkerWaiting(worker: ServiceWorker | null): void {
  waiting = worker;
  emit();
}

export function isUpdateWaiting(): boolean {
  return waiting !== null;
}

export function subscribeSwUpdate(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Ask the waiting worker to take over. `controllerchange` in the registration
 * code performs the single reload — not this function, so a caller cannot end up
 * with two reloads.
 */
export function requestUpdate(): void {
  if (!waiting || updateRequested) return;
  updateRequested = true;
  try {
    waiting.postMessage({ type: 'SKIP_WAITING' });
  } catch {
    // If the message cannot be delivered the page keeps working on the old
    // build; a later reload picks the new one up.
    updateRequested = false;
  }
  emit();
}

export function updateWasRequested(): boolean {
  return updateRequested;
}

/** Test seam. */
export function resetSwUpdate(): void {
  waiting = null;
  updateRequested = false;
  emit();
}

export interface UpdateRegistration {
  waiting: ServiceWorker | null;
  installing: ServiceWorker | null;
  addEventListener: (type: string, fn: () => void) => void;
}

/**
 * Wire a `ServiceWorkerRegistration` to this module. Extracted from `main.tsx`
 * so it can be tested without a browser.
 *
 * `hadController` is passed in because a FIRST install has no controller and
 * must not show "a new version is available" — there is nothing to replace.
 */
export function watchRegistration(
  registration: UpdateRegistration,
  hadController: boolean,
  onControllerChange: () => void,
): void {
  if (hadController && registration.waiting) {
    onWorkerWaiting(registration.waiting);
  }
  registration.addEventListener('updatefound', () => {
    const installing = registration.installing;
    if (!installing) return;
    installing.addEventListener('statechange', () => {
      if (installing.state !== 'installed') return;
      // First install: the page is already running the only version there is.
      if (!hadController) return;
      onWorkerWaiting(registration.waiting ?? installing);
    });
  });
  registration.addEventListener('controllerchange', onControllerChange);
}
