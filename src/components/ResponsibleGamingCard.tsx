/**
 * Responsible-gaming controls (plan item 11.3 / G3).
 *
 * The API existed and nothing could reach it: a control a player cannot find is
 * not a control. This is the surface for it.
 *
 * The wording matters as much as the wiring, so it is deliberate:
 *
 *   * lowering or clearing a limit takes effect NOW, raising it takes effect
 *     LATER — and the UI says which, because a player who sets a limit and sees
 *     it not apply will conclude the control is broken;
 *   * self-exclusion CANNOT be lifted early, and the confirmation says so before
 *     the player commits, not after.
 */
import { useCallback, useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Shield, Loader2, AlertCircle, Clock } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageContext';
import { usePulsarStore } from '../store/usePulsarStore';
import {
  fetchLimits,
  setDepositLimit,
  selfExclude,
  coolOff,
  type GamingLimits,
} from '../lib/gameServerClient';
import { loadServerSession } from '../lib/gameServerClient';

const STAKE_CHOICES = [1, 2, 5, 10];
const EXCLUSION_CHOICES = [
  { seconds: 24 * 60 * 60, label: '24h' },
  { seconds: 7 * 24 * 60 * 60, label: '7d' },
  { seconds: 30 * 24 * 60 * 60, label: '30d' },
];

export function ResponsibleGamingCard() {
  const { t } = useLanguage();
  // `usePulsarStore()` takes no selector — it returns the whole snapshot.
  const { wallet } = usePulsarStore();
  const [limits, setLimits] = useState<GamingLimits | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const session = loadServerSession();

  const refresh = useCallback(async () => {
    if (!session) return;
    try {
      setLimits(await fetchLimits(session));
    } catch {
      // A failed read must not look like "no limits set" — that would tell a
      // player their controls are gone when the server is simply unreachable.
      setError(t('limitsUnavailable'));
    }
  }, [session, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (fn: () => Promise<GamingLimits>, message: string) => {
    if (!session) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      setLimits(await fn());
      setNotice(message);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!wallet.connected || !session) {
    return (
      <div className="linear-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <Shield className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-bold text-white">{t('responsibleGaming')}</h3>
        </div>
        <p className="text-xs text-zinc-400">{t('responsibleGamingConnect')}</p>
      </div>
    );
  }

  const raising =
    limits?.pendingLimit !== null &&
    limits?.pendingLimit !== undefined &&
    limits.pendingLimitAt !== null;

  return (
    <div className="linear-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Shield className="w-4 h-4 text-emerald-400" />
        <h3 className="text-sm font-bold text-white">{t('responsibleGaming')}</h3>
      </div>

      {limits?.selfExcluded && (
        <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 flex items-start gap-2">
          <AlertCircle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-amber-200 leading-relaxed">{t('selfExcludedNotice')}</p>
        </div>
      )}
      {limits?.coolingOff && (
        <div className="mb-3 rounded-lg border border-sky-500/30 bg-sky-500/10 p-2.5 flex items-start gap-2">
          <Clock className="w-3.5 h-3.5 text-sky-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-sky-200 leading-relaxed">{t('coolOffNotice')}</p>
        </div>
      )}

      {/* Deposit limit */}
      <div className="mb-4">
        <p className="text-[11px] font-semibold text-zinc-300 mb-1.5">{t('depositLimit')}</p>
        <p className="text-[10.5px] text-zinc-500 mb-2 leading-relaxed">{t('depositLimitHint')}</p>
        <div className="flex flex-wrap gap-1.5">
          <button
            disabled={busy}
            onClick={() => void run(() => setDepositLimit(session, null), t('limitCleared'))}
            className="px-2.5 py-1.5 rounded-lg text-[11px] border border-white/10 text-zinc-300 hover:bg-white/5 cursor-pointer disabled:opacity-50"
          >
            {t('noLimit')}
          </button>
          {STAKE_CHOICES.map((v) => (
            <button
              key={v}
              disabled={busy}
              onClick={() => void run(() => setDepositLimit(session, v), t('limitSet'))}
              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-mono border cursor-pointer disabled:opacity-50 ${
                limits?.depositLimit === v
                  ? 'bg-emerald-500/15 border-emerald-400/60 text-emerald-300'
                  : 'border-white/10 text-zinc-300 hover:bg-white/5'
              }`}
            >
              ${v}
            </button>
          ))}
        </div>
        {raising && (
          <p className="text-[10.5px] text-amber-300 mt-2">
            {t('limitRaisePending', { limit: String(limits?.pendingLimit) })}
          </p>
        )}
      </div>

      {/* Self-exclusion */}
      <div className="mb-3">
        <p className="text-[11px] font-semibold text-zinc-300 mb-1.5">{t('selfExclusion')}</p>
        <p className="text-[10.5px] text-zinc-500 mb-2 leading-relaxed">{t('selfExclusionHint')}</p>
        <div className="flex flex-wrap gap-1.5">
          {EXCLUSION_CHOICES.map((c) => (
            <button
              key={c.seconds}
              disabled={busy}
              onClick={() => void run(() => selfExclude(session, c.seconds), t('selfExcluded'))}
              className="px-2.5 py-1.5 rounded-lg text-[11px] border border-white/10 text-zinc-300 hover:bg-white/5 cursor-pointer disabled:opacity-50"
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Cool-off */}
      <button
        disabled={busy}
        onClick={() => void run(() => coolOff(session, 60 * 60), t('coolOffStarted'))}
        className="w-full py-2 rounded-lg text-[11px] font-semibold border border-white/10 text-zinc-300 hover:bg-white/5 cursor-pointer disabled:opacity-50 flex items-center justify-center gap-1.5"
      >
        {busy && <Loader2 className="w-3 h-3 animate-spin" />}
        {t('takeAnHourOff')}
      </button>

      {notice && (
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[10.5px] text-emerald-400 mt-2">
          {notice}
        </motion.p>
      )}
      {error && <p className="text-[10.5px] text-red-400 mt-2">{error}</p>}
    </div>
  );
}
