/**
 * Locale-independent number formatting (i18n audit, 2026-10-23).
 *
 * THE POLICY: every numeral this UI renders is a LATIN digit with a `,`
 * thousands separator and a `.` decimal point — in all five languages.
 *
 * Why not "format numbers in the user's locale"? Because the rest of the screen
 * cannot follow:
 *
 *  - amounts, XP and reaction times sit beside a wallet address, a transaction
 *    hash and a `font-mono` column, all of which are Latin by necessity;
 *  - `toLocaleString()` with no argument reads the BROWSER's locale, not the
 *    app's language. A Persian-speaking user on an English browser got Latin
 *    digits, the same user on a Persian browser got `۱٬۲۳۴` — in the same
 *    position in the same table. That is not localisation, it is a coin flip;
 *  - Persian (۰-۹, U+06F0) and Arabic-Indic (٠-٩, U+0660) digits are different
 *    code points from each other, so a number copy-pasted out of the UI into a
 *    block explorer or a support ticket is a different string.
 *
 * So the choice is not "localised vs. not localised"; it is "one numeral system
 * the whole product agrees on" vs. "two systems on one screen". The audit chose
 * the first and converted the 35 translation strings that still used Persian or
 * Arabic digits (see docs/I18N-AUDIT.md §4). If that decision is ever reversed,
 * it must be reversed in THIS file for every number at once — not per string.
 */

const NUMBER = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
  useGrouping: true,
});

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

/** A plain number: `1234.5` -> `1,234.5`. Never returns non-Latin digits. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return Number.isInteger(value) ? INTEGER.format(value) : NUMBER.format(value);
}

/** A USDC amount with a `$` sign: `0.98` -> `$0.98`, `1234` -> `$1,234`. */
export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return '$—';
  return `$${formatNumber(value)}`;
}

/**
 * A wall-clock time for a timestamp, always 24-hour `HH:MM`.
 *
 * `toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })` produced
 * `۰۲:۰۵` on a Persian browser and `2:05 PM` on an American one — and an AM/PM
 * marker is itself English copy that no translation table can reach.
 */
export function formatClock(timestamp: number | string | Date): string {
  const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}
