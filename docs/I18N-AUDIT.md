# Five-language audit (fa · ar · tr · zh · en) — 2026-10-23

This is a **measurement**, not a claim of completeness. Every number below was
produced by a script against this commit, and every "fixed" item has a test that
fails if it comes back.

The existing `src/i18n/translations.test.ts` already proved that the five
dictionaries have the same keys, the same placeholders, no `${…}`, and no mixed
digit systems *inside one string*. Those tests were correct and they passed —
while the UI was still shipping English in five languages. Here is why, and what
was done about it.

---

## 1. Method

| check | how | scope |
|---|---|---|
| dictionary parity | import the module, compare key sets | 5 dictionaries |
| untranslated literals in JSX | parse every `.tsx` text node between `>` … `</` and flag Latin words not in a units/brands allowlist | 54 source files |
| copy hidden in expressions | flag `? 'Text' : 'Text'` string branches | same |
| browser-locale formatting | grep `toLocaleString()` / `toLocaleTimeString([]` | same |
| numeral consistency | regex for U+06F0–06F9 and U+0660–0669 in every value | 502 keys × 5 |
| physical-vs-logical CSS | grep `text-left` / `text-right` and physical insets | same |
| direction locks | find `dir="ltr"` / `direction: 'ltr'` and inspect what they contain | same |

---

## 2. What the audit found (all of it, including what is still open)

| # | finding | severity | status |
|---|---|---|---|
| 1 | **42 user-visible strings never reached a dictionary** — "Loading…", "Duels", "Network", "Token", "Sync/Syncing…", "Copy/Copied", "Connected", "Detected", "Popular", "Browser extension ready", "Mobile Wallets & QR Code", "1-Tap Mobile Testing", a full sentence about pairing codes, the reaction game's round banners ("ROUND 3 WON!"), the settlement status messages ("Payout confirmed…", "Wallet action cancelled — no funds moved."), refund messages, the certificate title, the stake-tier tags, and the "Arena Duelist" fallback | **high** — the game loop and the money messages were English for fa/ar/tr/zh users | **fixed** (42 keys) |
| 2 | **The wallet-connect sheet forced `direction: ltr` over ~25 translated strings** | **high** — Persian/Arabic text rendered with English word order in the most important flow | **fixed** (direction removed; only two identity rows keep a lock) |
| 3 | **Numbers were formatted by the browser, not the product** — 5 × `toLocaleString()` and one `toLocaleTimeString([], …)` | **high** — the same screen showed `1,234` for one user and `۱٬۲۳۴` for another; the `[]` form also emitted an English AM/PM marker no dictionary can reach | **fixed** (`src/lib/localeFormat.ts`, one formatter) |
| 4 | **33 translation values used Persian or Arabic-Indic digits** while every dynamic number is Latin | medium — two numeral systems on one screen | **fixed** (all converted; policy in §4) |
| 5 | **Match history rendered a stored identifier** — `game: 'Reaction Duel (Ranked · Bo3)'` was printed verbatim in all five languages | medium | **fixed** (`src/lib/matchLabel.ts`, mapping at the display layer; the stored id is untouched) |
| 6 | **`text-left` / `text-right` on page content** (9 places) forced English alignment under `dir="rtl"` | medium | **fixed** (`text-start` / `text-end`) |
| 7 | **Search icon on the wrong side under RTL** — `absolute left-3` with a symmetric `px-9` input | low | **fixed** (`start-3`; the status and clear buttons moved to `end-*`) |
| 8 | **The share sheet text is English** (`DuelCertificateModal` builds 4 English variants for WhatsApp/Telegram) | low–medium | **open** — see §6 |
| 9 | **Avatar tier names and descriptions are English** ("Novice Duelist", "Emerald Matrix", "Clean metallic baseline", 5 tiers × 3 fields) | low | **open** — see §6 |
| 10 | **`legal*` keys are English-only by design** (43 of 49) | acknowledged | documented in `translations.test.ts`; the UI discloses it via `legalEnglishOnly` |
| 11 | **Turkish casing** — CSS `text-transform: uppercase` on 38 elements | none found | safe: the spec makes it language-sensitive and `<html lang>` is set (including by the pre-boot script), so `i → İ` follows the document language. Verified by reading the spec, **not** by rendering in a Turkish browser — an honest gap in coverage, not a known defect |

**Total: 42 new keys × 5 languages = 210 values written; 33 values re-digitised;
11 hardcoded literals deleted at 44 call sites; 9 alignment classes changed.**

---

## 3. Dictionary state after this pass

| language | keys | direction | notes |
|---|---:|---|---|
| `en` | **502** | ltr | reference set |
| `fa` | 459 | rtl | 43 legal keys English-only (disclosed in UI) |
| `ar` | 459 | rtl | same |
| `tr` | 459 | ltr | same |
| `zh` | 459 | ltr | same |

Placeholder parity: **0 mismatches** across 459 shared keys (every `{count}`,
`{n}`, `{hash}`, `{reason}`, `{minutes}`, `{amount}`, `{wallet}` appears in the
same shape in all five languages).

---

## 4. The numeral decision (and why it is a decision, not an oversight)

**Policy: every numeral the UI renders is a Latin digit with `,` grouping — in
all five languages.**

The alternative — format numbers in the user's locale — was rejected for three
concrete reasons, in this order:

1. **The rest of the screen cannot follow.** Amounts, XP and reaction times sit
   beside wallet addresses, transaction hashes and `font-mono` columns. Those are
   Latin by necessity. Persian digits in one column and Latin in the next is the
   exact defect the old `translations.test.ts` forbids *inside* a string.
2. **`toLocaleString()` reads the browser, not the app.** A Persian-speaking
   user with an English browser got Latin digits; the same user with a Persian
   browser got `۱٬۲۳۴` — same table, same amount, different rendering. That is a
   coin flip, not localisation.
3. **Copy-paste breaks.** Persian (۰–۹, U+06F0) and Arabic-Indic (٠–٩, U+0660)
   digits are different code points from each other *and* from ASCII. A number
   copied into a block explorer, a support ticket or a dispute message is a
   different string.

If the product ever wants locale digits, it must be one change in
`src/lib/localeFormat.ts` for every number at once (and then bidi isolation for
units, and font coverage for the digit glyphs in the mono columns). Doing it per
string is what produced the 33 mixed strings this audit had to convert.

The Persian percent sign `٪` is kept: it is a symbol, not a digit, and it does
not clash with either system.

---

## 5. Direction: what is LTR-locked, and why

`document.documentElement.dir` is set from the language, and a pre-boot script
sets it before the first paint (L-14). Some chrome is deliberately LTR-locked;
this is the complete list, with the reason:

| element | lock | why |
|---|---|---|
| bottom navigation | `dir="ltr"` + `.navbar-strict-ltr` | icon order and the active-tab indicator are designed LTR; the labels inside are still translated |
| language selector | `dir="ltr"` | language names and flags read left-to-right in every locale |
| app header groups | `dir="ltr"` | the header is a fixed two-cluster layout (brand + wallet); mirroring it moves the wallet button away from where the thumb expects it |
| wallet address / player tag / chain id rows | `direction: 'ltr'` on the row | content is Latin by construction; flipping it reorders glyphs without changing a word |
| the wallet sheet | **removed** (was `direction: 'ltr'` over ~25 translated strings) | translated copy must follow the paragraph direction |

Everything else in `src/pages/**` now uses logical utilities (`text-start`,
`text-end`, `start-3`, `end-0`, `ms-/me-`). The rule is enforced by
`src/i18n/i18nAudit.test.ts` with a one-entry allowlist that must carry a reason.

---

## 6. Still open — with cost, not a shrug

| item | why it was not fixed here | estimate |
|---|---|---|
| share-sheet text (4 English variants in `DuelCertificateModal`) | it is outbound free text with a URL and emoji; 4 × 5 = 20 values, and the correct design is a `buildShareText(lang, result)` builder, not 20 strings | 3 h |
| avatar tier names + descriptions (5 tiers × name/colourway/description) | brand copy ("Emerald Matrix", "Hyper Blue-Violet") — needs a product decision on whether tiers are names or descriptions | 2 h + a naming decision |
| Turkish uppercase audit on a real Turkish device | `text-transform: uppercase` is language-sensitive per spec and `lang` is set, but no test here can prove Chrome/Safari behaviour | 30 min on a device |
| Arabic plural forms (CLDR has 6 categories; all strings use one form) | none of the current strings is plural-sensitive (`saveAttempts` is only rendered when `count > 1`, so the English "1 attempts" case is unreachable) — but a future `{count}` string would be | 1 h when the first such string lands |
| `escrow`, `commit-reveal` left untranslated inside Persian/Arabic sentences | they are protocol nouns with no accepted native term; translating them would be less clear than keeping them | product decision, 0 h |

---

## 7. What this audit proves, and what it does not

**Proves:** dictionary parity and placeholder parity hold; no source file
formats a number through the browser locale; no `.tsx` text node contains an
untranslated English phrase outside the allowlist; no page aligns translated
copy with a physical side; the specific 11 hardcoded strings cannot return; the
merchant-facing numerals are consistent.

**Does not prove:** that the Persian/Turkish/Chinese/Arabic *translations read
well* — no test can. It does not prove RTL layout on a real device (no browser
was available), and it does not prove the Turkish uppercase behaviour. Those are
in §6/§2 with their cost rather than in a green checkmark.
