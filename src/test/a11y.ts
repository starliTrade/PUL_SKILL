/**
 * axe in jsdom (plan item 8.13).
 *
 * The phase-8 exit gate is "axe: zero critical/serious violations". Playwright
 * is deferred to phase 10, so the gate runs here: axe-core against the rendered
 * DOM in vitest. jsdom has no layout, so axe's colour-contrast rule cannot run —
 * everything else (names, roles, ARIA relationships, labels, focus order,
 * landmarks, heading order) does, and that is what the phase-8 items are about.
 */
import axe from 'axe-core';

export interface A11yViolation {
  id: string;
  impact: string;
  help: string;
  html: string[];
}

/** The rules jsdom cannot evaluate (no layout / no real paint). */
const UNSUPPORTED_IN_JSDOM = ['color-contrast'];

export async function axeViolations(
  container: HTMLElement,
  opts: { include?: string[] } = {}
): Promise<A11yViolation[]> {
  const results = await axe.run(container, {
    resultTypes: ['violations'],
    rules: Object.fromEntries(UNSUPPORTED_IN_JSDOM.map((id) => [id, { enabled: false }])),
    ...(opts.include ? { runOnly: { type: 'rule', values: opts.include } } : {}),
  });

  return results.violations
    .filter((v) => v.impact === 'critical' || v.impact === 'serious')
    .map((v) => ({
      id: v.id,
      impact: String(v.impact),
      help: v.help,
      html: v.nodes.map((n) => n.html),
    }));
}

/** A readable assertion message for a failing sweep. */
export function describeViolations(violations: A11yViolation[]): string {
  return violations
    .map((v) => `${v.impact.toUpperCase()} ${v.id}: ${v.help}\n    ${v.html.join('\n    ')}`)
    .join('\n');
}
