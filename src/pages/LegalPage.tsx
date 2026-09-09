/**
 * P2.3 — Legal pack: Terms of Service, Privacy Policy, Risk Disclosure.
 *
 * ⚠️ TEMPLATE NOTICE: These documents are a professionally-structured
 * starting point. Before real-money launch they MUST be reviewed and adapted
 * by a qualified attorney for the operating entity's jurisdiction, and the
 * [OPERATOR] placeholders replaced with the real legal entity.
 */

import React, { useState } from 'react';
import { motion } from 'motion/react';
import { ArrowLeft, FileText, ShieldCheck, AlertTriangle, Gavel } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageContext';
import { PulsarCosmicBackground } from '../components/PulsarCosmicBackground';

type LegalTab = 'tos' | 'privacy' | 'risk';

interface LegalPageProps {
  onNavigate: (path: string) => void;
  initialTab?: LegalTab;
}

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="space-y-1.5">
    <h3 className="text-[13px] font-bold text-white">{title}</h3>
    <div className="text-xs text-zinc-400 leading-relaxed space-y-2">{children}</div>
  </div>
);

export const LegalPage: React.FC<LegalPageProps> = ({ onNavigate, initialTab = 'tos' }) => {
  const { t } = useLanguage();
  const [tab, setTab] = useState<LegalTab>(initialTab);

  const tabs: { id: LegalTab; label: string; icon: React.ReactNode }[] = [
    { id: 'tos', label: t('legalTosTitle'), icon: <FileText className="w-3.5 h-3.5" /> },
    { id: 'privacy', label: t('legalPrivacyTitle'), icon: <ShieldCheck className="w-3.5 h-3.5" /> },
    { id: 'risk', label: t('legalRiskTitle'), icon: <AlertTriangle className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="min-h-screen bg-black relative overflow-x-hidden text-zinc-100 selection:bg-white/20">
      <PulsarCosmicBackground className="opacity-60" />
      <div className="absolute inset-0 bg-grid opacity-30 pointer-events-none" />

      <main className="relative z-10 px-4 pt-4 pb-24 max-w-md mx-auto">
        <button
          onClick={() => onNavigate('/')}
          className="btn-secondary py-1.5 px-3 flex items-center gap-1.5 text-xs text-zinc-300 hover:text-white cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>{t('backToLobby')}</span>
        </button>

        <div className="flex items-center gap-2 mt-4 mb-1">
          <Gavel className="w-5 h-5 text-sky-400" />
          <h1 className="text-xl font-bold text-white tracking-tight">{t('legalTitle')}</h1>
        </div>
        <p className="text-[11px] text-zinc-500 mb-4">
          {t('legalEffectiveDate')} · {t('legalEntityNotice')}
        </p>

        {/* Tabs */}
        <div className="flex gap-1.5 mb-4">
          {tabs.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-[11px] font-semibold border transition-all cursor-pointer ${
                tab === item.id
                  ? 'bg-sky-500/15 border-sky-500/40 text-sky-300'
                  : 'bg-zinc-900/60 border-white/[0.06] text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {item.icon}
              <span className="truncate">{item.label}</span>
            </button>
          ))}
        </div>

        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="linear-card p-4 space-y-4"
        >
          {/* ─────────────────── TERMS OF SERVICE ─────────────────── */}
          {tab === 'tos' && (
            <>
              <Section title={t('legalTosAcceptanceTitle')}>
                <p>{t('legalTosAcceptanceBody')}</p>
              </Section>
              <Section title={t('legalTosEligibilityTitle')}>
                <p>{t('legalTosEligibilityBody')}</p>
              </Section>
              <Section title={t('legalTosServiceTitle')}>
                <p>{t('legalTosServiceBody')}</p>
              </Section>
              <Section title={t('legalTosAccountsTitle')}>
                <p>{t('legalTosAccountsBody')}</p>
              </Section>
              <Section title={t('legalTosFeesTitle')}>
                <p>{t('legalTosFeesBody')}</p>
              </Section>
              <Section title={t('legalTosConductTitle')}>
                <p>{t('legalTosConductBody')}</p>
              </Section>
              <Section title={t('legalTosTerminationTitle')}>
                <p>{t('legalTosTerminationBody')}</p>
              </Section>
              <Section title={t('legalTosLiabilityTitle')}>
                <p>{t('legalTosLiabilityBody')}</p>
              </Section>
              <Section title={t('legalTosLawTitle')}>
                <p>{t('legalTosLawBody')}</p>
              </Section>
            </>
          )}

          {/* ─────────────────── PRIVACY POLICY ─────────────────── */}
          {tab === 'privacy' && (
            <>
              <Section title={t('legalPrivacyDataTitle')}>
                <p>{t('legalPrivacyDataBody')}</p>
              </Section>
              <Section title={t('legalPrivacyUseTitle')}>
                <p>{t('legalPrivacyUseBody')}</p>
              </Section>
              <Section title={t('legalPrivacyNoSellTitle')}>
                <p>{t('legalPrivacyNoSellBody')}</p>
              </Section>
              <Section title={t('legalPrivacyStorageTitle')}>
                <p>{t('legalPrivacyStorageBody')}</p>
              </Section>
              <Section title={t('legalPrivacyRightsTitle')}>
                <p>{t('legalPrivacyRightsBody')}</p>
              </Section>
              <Section title={t('legalPrivacyContactTitle')}>
                <p>{t('legalPrivacyContactBody')}</p>
              </Section>
            </>
          )}

          {/* ─────────────────── RISK DISCLOSURE ─────────────────── */}
          {tab === 'risk' && (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs leading-relaxed">
                {t('legalRiskSummary')}
              </div>
              <Section title={t('legalRiskLossTitle')}>
                <p>{t('legalRiskLossBody')}</p>
              </Section>
              <Section title={t('legalRiskCryptoTitle')}>
                <p>{t('legalRiskCryptoBody')}</p>
              </Section>
              <Section title={t('legalRiskSkillTitle')}>
                <p>{t('legalRiskSkillBody')}</p>
              </Section>
              <Section title={t('legalRiskTechTitle')}>
                <p>{t('legalRiskTechBody')}</p>
              </Section>
              <Section title={t('legalRiskJurisdictionTitle')}>
                <p>{t('legalRiskJurisdictionBody')}</p>
              </Section>
              <Section title={t('legalRiskTaxesTitle')}>
                <p>{t('legalRiskTaxesBody')}</p>
              </Section>
            </div>
          )}
        </motion.div>
      </main>
    </div>
  );
};

export type { LegalTab };
