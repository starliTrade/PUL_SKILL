/**
 * H16 — the anti-cheat must not claim to measure what it does not.
 *
 * `analyzeBiometrics` returned four fields that look like measurements and are
 * not:
 *
 *   humanEntropyScore        a lookup table on the reaction time
 *                            (`>= 160 ? 96.5 : >= 130 ? 88.0 : 78.5`), or a hash
 *                            of other computed values — not an entropy
 *                            measurement of anything
 *   fittsKinematicScore      `reactionTimeMs >= 160 ? 95.0 : 82.0` — a lookup,
 *                            not a Fitts's-law computation
 *   neuromuscularJitterHz    `3.8 + sin(reactionTimeMs * 0.05) * 1.8` — a SINE
 *                            WAVE of the reaction time, presented as "natural
 *                            2-8 Hz hand tremor"
 *   subMillisecondClockIntegrity   always `true`, never measured
 *
 * Under D1 (real money) this is worse than useless: a player shown "Human
 * Entropy 96.5%" believes the game verified something. It did not. A false
 * claim of verification is a claim the operator cannot defend.
 *
 * The checks that ARE real stay: the `isTrusted` flag, the human floor, and the
 * trajectory analysis.
 */
import { describe, it, expect } from 'vitest';

import { AntiCheat } from './antiCheat';

const POINTS = [
  { x: 10, y: 10, t: 0 },
  { x: 40, y: 22, t: 30 },
  { x: 90, y: 60, t: 70 },
  { x: 120, y: 95, t: 110 },
];

describe('anti-cheat honesty (audit H16)', () => {
  it('does not report a fabricated human-entropy score', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result).not.toHaveProperty('humanEntropyScore');
  });

  it('does not report a fabricated Fitts score', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result).not.toHaveProperty('fittsKinematicScore');
  });

  it('does not report a fabricated neuromuscular jitter frequency', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result).not.toHaveProperty('neuromuscularJitterHz');
  });

  it('does not claim clock integrity it never checked', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result).not.toHaveProperty('subMillisecondClockIntegrity');
  });

  it('the jitter value is not a function of the reaction time alone', () => {
    // The old value was `3.8 + sin(ms * 0.05) * 1.8` — identical inputs gave a
    // value that tracked the clock, not the hand. Two different trajectories at
    // the SAME reaction time must not produce the same "measurement".
    const a = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    const b = AntiCheat.analyzeBiometrics([{ x: 0, y: 0, t: 0 }, { x: 5, y: 5, t: 90 }], 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });

    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  // --- the real checks must survive ------------------------------------------
  it('still rejects an untrusted event', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: false, pointerType: 'mouse', hasNaturalJitter: false });
    expect(result.passedValidation).toBe(false);
    expect(result.flagReason).toMatch(/isTrusted/i);
  });

  it('still rejects a reaction below the human floor', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, AntiCheat.MIN_HUMAN_REACTION_MS - 1, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result.passedValidation).toBe(false);
    expect(result.flagReason).toMatch(/floor/i);
  });

  it('still accepts a plausible reaction', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result.passedValidation).toBe(true);
  });

  it('still reports how many samples it actually saw', () => {
    const result = AntiCheat.analyzeBiometrics(POINTS, 220, { isTrusted: true, pointerType: 'mouse', hasNaturalJitter: true });
    expect(result.sampleCount).toBe(POINTS.length);
  });
});
