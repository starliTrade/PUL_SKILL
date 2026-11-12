import type { TranslationKey } from '../i18n/translations';

/**
 * A match's `game` field is a STORED IDENTIFIER, not a label (i18n audit,
 * 2026-10-23).
 *
 * `ReactionGamePage` writes `game: 'Reaction Duel (Ranked · Bo3)'` into the
 * match record, and the dashboard rendered that value directly — so every
 * player, in all five languages, saw an English sentence in their match
 * history. Translating the value at write time would be worse: the stored
 * history would then depend on the language the player happened to use that
 * day, and two records of the same game type would no longer be comparable.
 *
 * The fix is at the display layer: map the known identifiers to dictionary
 * keys, and fall back to the raw value for anything unknown (an old record, a
 * future game type) rather than inventing a label.
 */
export function matchLabel(
  raw: string | null | undefined,
  t: (key: TranslationKey) => string
): string {
  if (!raw) return t('reflexCalibration');
  if (/reaction|reflex/i.test(raw)) {
    return /ranked/i.test(raw) ? t('duelRankedBo3') : t('duelBestOf3');
  }
  return raw;
}
