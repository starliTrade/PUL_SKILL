/**
 * Phase 7 / M43 — literal placeholder interpolation.
 *
 * The old implementation was:
 *
 *   text.replace(new RegExp(`{${paramKey}}`, 'g'), String(paramVal))
 *
 * which is wrong twice over, and both failures are reachable from ordinary data:
 *
 *  - the KEY goes into a regex unescaped. A key containing `.`, `(`, `[` or `+`
 *    either throws or matches something the author did not intend;
 *  - the VALUE is a replacement STRING, so `$&`, `$1`, `` $` `` and `$'` are
 *    interpreted as replacement patterns. A player whose nickname contains `$&`
 *    corrupts every message that names them — and a nickname is exactly the kind
 *    of value that gets interpolated.
 *
 * `split`/`join` has neither problem: it is a literal, global replace with no
 * pattern language anywhere.
 */

export function interpolate(
  template: string,
  params?: Record<string, string | number>
): string {
  if (!params) return template;
  let text = template;
  for (const [key, value] of Object.entries(params)) {
    // Literal, global, and no replacement-pattern semantics on the value.
    text = text.split(`{${key}}`).join(String(value));
  }
  return text;
}
