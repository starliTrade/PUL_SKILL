import React, { useCallback, useEffect, useState } from 'react';
import { Coins, LoaderCircle, RefreshCw } from 'lucide-react';

import { escrowStatus, getPendingWithdrawal, withdrawPending } from '../lib/escrowFlow';
import { useLanguage } from '../i18n/LanguageContext';

/**
 * Audit H17b — surface a deferred payout and let the player claim it.
 *
 * Audit H17 gave the contract `pendingWithdrawals` + `withdraw()` so a payout
 * the token refused (Tether blacklist, a paused token, a contract that reverts
 * on receipt) is credited instead of reverting the whole settlement. Without
 * this card that money is on-chain and invisible: the player is owed it, the
 * contract will pay it, and nothing in the app says so.
 *
 * The card renders nothing when there is no escrow, no wallet, or nothing
 * pending — a permanent "0.00 pending" row would be noise, and a claim button
 * that always fails is worse than none.
 */
export const PendingPayoutCard: React.FC<{ address?: string }> = ({ address }) => {
  const { t } = useLanguage();
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!address || !escrowStatus().configured) {
      setPending(null);
      return;
    }
    try {
      const value = await getPendingWithdrawal(address);
      setPending(Number(value) > 0 ? value : null);
    } catch {
      // A read failure must not shout at the player; the card simply hides.
      setPending(null);
    }
  }, [address]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const claim = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await withdrawPending();
      setMessage(t('pendingPayoutClaimed'));
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!pending) return null;

  return (
    <div className="linear-card p-4 mt-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-400/20 flex items-center justify-center">
            <Coins className="w-4 h-4 text-amber-300" />
          </div>
          <div>
            <p className="text-xs font-bold text-white">{t('pendingPayoutTitle')}</p>
            <p className="text-[11px] text-zinc-400">{t('pendingPayoutDesc')}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm text-amber-300">{pending} USDT</span>
          <button
            type="button"
            onClick={claim}
            disabled={busy}
            aria-label={t('pendingPayoutClaim')}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/15 border border-amber-400/30 text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
          >
            {busy ? <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> : t('pendingPayoutClaim')}
          </button>
          <button
            type="button"
            onClick={() => void refresh()}
            aria-label={t('pendingPayoutRefresh')}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {message && <p className="text-[11px] text-zinc-400 mt-2">{message}</p>}
    </div>
  );
};
