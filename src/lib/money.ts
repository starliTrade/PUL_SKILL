/**
 * Money display helpers (audit 2026-10-24).
 *
 * The rule: a balance is never rounded UP, because the same number feeds a
 * sufficiency gate (`LobbyPage`: `balance < selectedStake` blocks entry). Rounding
 * up lets a wallet holding 4.996 USDT display 5.00, pass the `stake = 5` gate,
 * and send the player into a transaction the contract must reject.
 *
 * Direction matters more than the exact rounding mode:
 *   - truncate  -> can understate by <1 unit, which never lets a player sign an
 *                  unpayable duel;
 *   - round     -> can overstate by half a unit, which does.
 */

/**
 * Truncate `value` to `decimals` places. Non-finite input returns 0, because
 * `NaN < stake` is false — a NaN balance would PASS the sufficiency gate.
 */
export function floorToDecimals(value: number, decimals: number): number {
  if (!Number.isFinite(value)) return 0;
  const factor = 10 ** decimals;
  // No epsilon correction on purpose: `0.29 * 100` is 28.999999999999996 in
  // binary floating point, and flooring it gives 0.28 rather than 0.29. Being a
  // hair low is acceptable; being a hair high is the bug.
  return Math.floor(value * factor) / factor;
}
