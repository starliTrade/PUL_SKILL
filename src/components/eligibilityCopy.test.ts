/**
 * Phase 7 / M40 — the eligibility gate must not claim enforcement it does not
 * have.
 *
 * `EligibilityGate` is a client-side self-declaration: it writes one
 * localStorage key and can be bypassed by clearing it. Nothing on the server or
 * at the edge refuses a restricted region — `api/` has no geo check at all. Yet
 * the legal copy told the user "The Service is unavailable in restricted
 * jurisdictions" and "Access may be blocked in restricted regions", and the
 * component's own header said the game server "must refuse SIWE sessions from
 * blocked regions".
 *
 * For a product whose pitch is cryptographic proof, a claim of enforcement the
 * operator cannot defend is a trust liability. The copy must describe the real
 * mechanism — the user's own declaration — and say plainly that automated
 * geo-restriction is not implemented.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const TRANSLATIONS = fs.readFileSync(
  path.resolve(process.cwd(), 'src/i18n/translations.ts'),
  'utf8'
);
const GATE = fs.readFileSync(
  path.resolve(process.cwd(), 'src/components/EligibilityGate.tsx'),
  'utf8'
);
// Comments wrap across lines with a leading ` * `; flatten so a phrase that
// spans two lines still matches.
const GATE_FLAT = GATE.replace(/\s*\*\s*/g, ' ').replace(/\s+/g, ' ');

describe('eligibility copy is honest about enforcement (audit M40)', () => {
  it('does not claim the Service is unavailable in restricted jurisdictions', () => {
    expect(TRANSLATIONS).not.toMatch(/unavailable in restricted jurisdictions/i);
  });

  it('does not claim access is blocked in restricted regions', () => {
    expect(TRANSLATIONS).not.toMatch(/access may be blocked in restricted regions/i);
  });

  it('does not claim the game server refuses sessions from blocked regions', () => {
    expect(GATE_FLAT).not.toMatch(/must refuse SIWE sessions from blocked regions/i);
  });

  it('states plainly that enforcement is a self-declaration, not automated', () => {
    expect(GATE_FLAT).toMatch(/self-declaration/i);
    expect(GATE_FLAT).toMatch(/no server or edge enforcement/i);
  });
});
