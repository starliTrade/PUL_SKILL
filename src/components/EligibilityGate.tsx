/**
 * P2.3 — First-visit eligibility gate: 18+ confirmation and restricted-
 * jurisdiction check. Consent is stored locally; the client-side check is a
 * UX layer — the authoritative enforcement belongs to the deployment edge
 * (geo-blocking at the hosting/CDN layer) and to the game server, which must
 * refuse SIWE sessions from blocked regions (P2.5 runbook item).
 */

import React, { useState } from 'react';
import { motion } from 'motion/react';
import { ShieldAlert, CheckCircle2, XCircle } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageContext';

const CONSENT_KEY = 'pulsar.eligibility-consent.v1';

/** ISO-3166 codes whose residents may not use real-money skill-duel features. */
export const RESTRICTED_JURISDICTIONS = [
  'US', // state-level skill-gaming/real-money rules vary — block until legal review
  'CN',
  'IR',
  'KP',
  'SY',
  'CU',
  'SD',
  'BY',
];

interface EligibilityGateProps {
  onProceed?: () => void;
}

export const EligibilityGate: React.FC<EligibilityGateProps> = ({ onProceed }) => {
  const { t } = useLanguage();
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [jurisdictionConfirmed, setJurisdictionConfirmed] = useState(false);

  const alreadyConsented = (() => {
    try {
      return localStorage.getItem(CONSENT_KEY) === 'granted';
    } catch {
      return false;
    }
  })();

  if (alreadyConsented) return null;

  const accept = () => {
    try {
      localStorage.setItem(CONSENT_KEY, 'granted');
      localStorage.setItem(CONSENT_KEY + '.at', String(Date.now()));
    } catch {
      /* storage unavailable */
    }
    onProceed?.();
  };

  const decline = () => {
    // Honest exit: send the user away from the product.
    try {
      window.location.href = 'https://www.google.com';
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/95 backdrop-blur-xl">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-sm linear-card-elevated p-5 relative border border-sky-500/20"
      >
        <div className="w-11 h-11 rounded-2xl bg-sky-500/10 border border-sky-500/25 flex items-center justify-center text-sky-400 mx-auto mb-3">
          <ShieldAlert className="w-5.5 h-5.5" />
        </div>

        <h2 className="text-base font-bold text-white text-center mb-1">{t('eligibilityTitle')}</h2>
        <p className="text-xs text-zinc-400 text-center mb-4 leading-relaxed">{t('eligibilityIntro')}</p>

        <div className="space-y-2.5 mb-4">
          <button
            onClick={() => setAgeConfirmed((v) => !v)}
            className="w-full flex items-start gap-2.5 p-3 rounded-xl bg-zinc-900/70 border border-white/[0.07] text-left cursor-pointer hover:border-white/[0.14] transition-colors"
          >
            {ageConfirmed ? (
              <CheckCircle2 className="w-4.5 h-4.5 text-emerald-400 shrink-0 mt-0.5" />
            ) : (
              <div className="w-4.5 h-4.5 rounded-full border-2 border-zinc-600 shrink-0 mt-0.5" />
            )}
            <span className="text-xs text-zinc-200 leading-relaxed">{t('eligibilityAge')}</span>
          </button>

          <button
            onClick={() => setJurisdictionConfirmed((v) => !v)}
            className="w-full flex items-start gap-2.5 p-3 rounded-xl bg-zinc-900/70 border border-white/[0.07] text-left cursor-pointer hover:border-white/[0.14] transition-colors"
          >
            {jurisdictionConfirmed ? (
              <CheckCircle2 className="w-4.5 h-4.5 text-emerald-400 shrink-0 mt-0.5" />
            ) : (
              <div className="w-4.5 h-4.5 rounded-full border-2 border-zinc-600 shrink-0 mt-0.5" />
            )}
            <span className="text-xs text-zinc-200 leading-relaxed">{t('eligibilityJurisdiction')}</span>
          </button>
        </div>

        <p className="text-[10px] text-zinc-500 leading-relaxed mb-4">{t('eligibilityTermsRef')}</p>

        <div className="flex gap-2">
          <button
            onClick={decline}
            className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-zinc-900 border border-white/[0.08] text-xs font-semibold text-zinc-400 hover:text-zinc-200 cursor-pointer"
          >
            <XCircle className="w-4 h-4" />
            {t('eligibilityDecline')}
          </button>
          <button
            onClick={accept}
            disabled={!ageConfirmed || !jurisdictionConfirmed}
            className="flex-1 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-30 disabled:cursor-not-allowed text-black text-xs font-bold cursor-pointer transition-colors"
          >
            {t('eligibilityAccept')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export const hasEligibilityConsent = (): boolean => {
  try {
    return localStorage.getItem(CONSENT_KEY) === 'granted';
  } catch {
    return false;
  }
};
