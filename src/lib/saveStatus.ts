/**
 * Audit M-24 (2026-10-22) — a failed save must be visible.
 *
 * `syncToFirestore` and the profile load caught their errors and called
 * `console.warn`. A player could rename themselves, watch the UI update (the
 * local cache is written first), close the tab, and find the old tag the next
 * day. The console is not a user interface.
 *
 * This module is the smallest thing that fixes it: a subscribable list of
 * per-area failures that the banner component renders, and that the data layer
 * clears when the next save succeeds. It deliberately keeps no history — a
 * banner that remembers yesterday's blip is noise.
 */

export type SaveFailureKind = 'write' | 'read';

export interface SaveFailure {
  /** Where the data lives: 'profile', 'matchHistory', … */
  area: string;
  kind: SaveFailureKind;
  message: string;
  /** Increments every time the same area fails again. */
  count: number;
  at: number;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let failures: readonly SaveFailure[] = [];
/** Stable snapshot identity is required by useSyncExternalStore. */
let snapshot: readonly SaveFailure[] = failures;

function emit(): void {
  snapshot = failures;
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      // A broken listener must not break the save path.
    }
  });
}

/** Record a failure. Called from catch blocks in the data layer. */
export function reportSaveFailure(
  area: string,
  kind: SaveFailureKind,
  error: unknown,
): void {
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : 'unknown error';
  const existing = failures.find((f) => f.area === area && f.kind === kind);
  const next: SaveFailure = {
    area,
    kind,
    message,
    count: (existing?.count ?? 0) + 1,
    at: Date.now(),
  };
  failures = [...failures.filter((f) => !(f.area === area && f.kind === kind)), next];
  emit();
}

/**
 * Clear an area (a later save/load succeeded).
 *
 * `kind` is normally supplied — a successful write says nothing about whether
 * the read that failed earlier has been repaired.
 */
export function clearSaveFailure(area: string, kind?: SaveFailureKind): void {
  const keep = (f: SaveFailure) => f.area !== area || (kind !== undefined && f.kind !== kind);
  if (failures.every(keep)) return;
  failures = failures.filter(keep);
  emit();
}

export function getSaveFailures(): readonly SaveFailure[] {
  return snapshot;
}

export function subscribeSaveStatus(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Test seam: reset between cases. */
export function resetSaveStatus(): void {
  failures = [];
  snapshot = failures;
  emit();
}
