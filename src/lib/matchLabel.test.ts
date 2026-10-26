import { describe, expect, it } from 'vitest';
import { matchLabel } from './matchLabel';
import { translations } from '../i18n/translations';

const t = (key: keyof typeof translations.en): string => translations.en[key];

describe('match history labels are translated at the display layer', () => {
  it('maps the stored ranked identifier instead of printing it', () => {
    // The record stores `Reaction Duel (Ranked · Bo3)`; history used to render it
    // verbatim in every language.
    expect(matchLabel('Reaction Duel (Ranked · Bo3)', t)).toBe(translations.en.duelRankedBo3);
    expect(matchLabel('reaction', t)).toBe(translations.en.duelBestOf3);
    expect(matchLabel('Reaction Duel (Best of 3)', t)).toBe(translations.en.duelBestOf3);
  });

  it('falls back to the raw identifier for a game it does not know', () => {
    // Inventing a label for an unknown record is worse than showing the raw id:
    // an old or future game type must remain visible, not silently relabeled.
    expect(matchLabel('Some Future Mode', t)).toBe('Some Future Mode');
  });

  it('uses the calibration label when the record has no game at all', () => {
    expect(matchLabel(undefined, t)).toBe(translations.en.reflexCalibration);
    expect(matchLabel('', t)).toBe(translations.en.reflexCalibration);
  });

  it('the ranked and best-of-3 labels are different in every language', () => {
    // If a translator collapsed them, the mapping above would be pointless.
    for (const lang of Object.keys(translations) as Array<keyof typeof translations>) {
      expect(translations[lang].duelRankedBo3, lang).not.toBe(translations[lang].duelBestOf3);
    }
  });
});
