/**
 * Parity pins: the client's constants must equal the contract's.
 *
 * The client and the contract are one protocol. When they drift, the failure is
 * silent and user-visible: a player is told to refund after N minutes, calls
 * `refundTimeoutMatch`, and gets a revert because the contract waits longer.
 *
 * Audit H19 changed the contract's refund horizon (MATCH_TIMEOUT +
 * REFUND_GRACE) and left nine user-facing strings saying "30 minutes" — found
 * by reviewing the phase-3 diff against the audit, not by the audit itself.
 * These pins make that class of drift a red test.
 *
 * The contract's own pins (`test_Pin_ContractFeeMatchesEconomyConstant`) cover
 * the other direction; this is the client half.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { ECONOMY, ESCROW_TIMING, REFUND_OPENS_AFTER_MINUTES } from './chain';

const SOLIDITY = readFileSync(
  path.resolve(process.cwd(), 'contracts/PulsarEscrow.sol'),
  'utf8'
);

/**
 * Read `<NAME> = <n> minutes;` (or `days`) from the Solidity source, in minutes.
 */
function solidityMinutes(name: string): number {
  const match = new RegExp(`${name}\\s*=\\s*(\\d+)\\s*(minutes|days)`).exec(SOLIDITY);
  if (!match) throw new Error(`${name} not found in PulsarEscrow.sol`);
  const value = Number(match[1]);
  return match[2] === 'days' ? value * 24 * 60 : value;
}

/** Read `<NAME> = <n>;` from the Solidity source. */
function solidityNumber(name: string): number {
  const match = new RegExp(`${name}\\s*=\\s*(\\d+)\\s*;`).exec(SOLIDITY);
  if (!match) throw new Error(`${name} not found in PulsarEscrow.sol`);
  return Number(match[1]);
}

describe('client/contract parity', () => {
  it('the settlement window matches PulsarEscrow.MATCH_TIMEOUT', () => {
    expect(ESCROW_TIMING.matchTimeoutSeconds).toBe(solidityMinutes('MATCH_TIMEOUT') * 60);
  });

  it('the refund grace matches PulsarEscrow.REFUND_GRACE', () => {
    expect(ESCROW_TIMING.refundGraceSeconds).toBe(solidityMinutes('REFUND_GRACE') * 60);
  });

  it('the displayed refund window is the contract’s real one', () => {
    const contractWindow =
      (solidityMinutes('MATCH_TIMEOUT') + solidityMinutes('REFUND_GRACE')) * 60;
    expect(REFUND_OPENS_AFTER_MINUTES * 60).toBe(contractWindow);
  });

  it('the platform fee matches PulsarEscrow.PLATFORM_FEE_BPS', () => {
    expect(ECONOMY.platformFeeBps).toBe(solidityNumber('PLATFORM_FEE_BPS'));
    expect(ECONOMY.winnerShareBps).toBe(10_000 - solidityNumber('PLATFORM_FEE_BPS'));
  });

  it('the admin timelock is at least a day', () => {
    // A timelock shorter than the settlement window would not give an
    // outstanding signature time to land (audit M24).
    expect(solidityMinutes('ADMIN_TIMELOCK')).toBeGreaterThanOrEqual(24 * 60);
  });
});
