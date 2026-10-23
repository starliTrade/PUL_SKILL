/**
 * Report a match for review (phase 6.4 / G8).
 *
 * Audit 2026-10-13: `POST /api/dispute` existed and was tested but had no client
 * path at all — the "user reports a match" feature could not be used by a user.
 * This is the H22b class (a mechanism in one layer with no consumer in another),
 * and it is why the endpoint is wired here rather than left as an API surface.
 *
 * A report is a REQUEST FOR REVIEW: it never touches match state or the money
 * path, and the server accepts it only from a participant.
 */
import React, { useState } from 'react';
import { Flag } from 'lucide-react';
import { ensureSession, fetchDisputeStatus, reportDispute, type DisputeReport } from '../lib/gameServerClient';
import { realWeb3Manager } from '../lib/realWeb3';
import { useLanguage } from '../i18n/LanguageContext';

interface DisputeReportButtonProps {
  matchId: string;
  address: string;
}

export const DisputeReportButton: React.FC<DisputeReportButtonProps> = ({ matchId, address }) => {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  // Audit L-09: the report used to end in a thank-you note. It now has a
  // lifecycle the player can read — and a decision an operator made is visible
  // here instead of only in a server log.
  const [reports, setReports] = useState<DisputeReport[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkFailed, setCheckFailed] = useState(false);

  const submit = async () => {
    if (reason.trim().length < 3) return;
    setStatus('sending');
    try {
      const session = await ensureSession(address, async (message: string) => {
        const provider = realWeb3Manager.getActiveEip1193Provider();
        if (!provider) throw new Error('No active wallet to sign in with.');
        return await provider.request({ method: 'personal_sign', params: [message, address] });
      });
      const res = await reportDispute(session, matchId, reason.trim());
      setStatus('sent');
      setOpen(false);
      setReason('');
      setReports([
        { id: res.disputeId, reason: reason.trim(), filedAt: Math.floor(Date.now() / 1000), status: res.status },
      ]);
    } catch {
      setStatus('error');
    }
  };

  const checkStatus = async () => {
    setChecking(true);
    setCheckFailed(false);
    try {
      const session = await ensureSession(address, async (message: string) => {
        const provider = realWeb3Manager.getActiveEip1193Provider();
        if (!provider) throw new Error('No active wallet to sign in with.');
        return await provider.request({ method: 'personal_sign', params: [message, address] });
      });
      const res = await fetchDisputeStatus(session, matchId);
      setReports(res.disputes);
      if (res.count === 0) setStatus('sent');
    } catch {
      setCheckFailed(true);
    } finally {
      setChecking(false);
    }
  };

  const statusLabel = (value: string) =>
    value === 'resolved'
      ? t('disputeStatusResolved')
      : value === 'dismissed'
        ? t('disputeStatusDismissed')
        : t('disputeStatusOpen');

  const statusTone = (value: string) =>
    value === 'resolved'
      ? 'text-emerald-300 border-emerald-500/30'
      : value === 'dismissed'
        ? 'text-zinc-400 border-white/10'
        : 'text-amber-300 border-amber-500/30';

  if (status === 'sent') {
    return (
      <div className="space-y-1.5" data-testid="dispute-sent">
        <p className="text-[10px] font-mono text-zinc-400">{t('disputeFiledCheck')}</p>
        {reports && reports.length > 0 ? (
          <ul className="space-y-1">
            {reports.map((report) => (
              <li
                key={report.id}
                data-testid="dispute-status-row"
                className={`rounded-lg border px-2 py-1 text-[10px] font-mono ${statusTone(report.status)}`}
              >
                <span className="font-bold">{statusLabel(report.status)}</span>
                {report.resolution ? <span className="text-zinc-400"> — {report.resolution}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[10px] font-mono text-zinc-500">{t('disputeNone')}</p>
        )}
        <button
          type="button"
          data-testid="dispute-check"
          onClick={checkStatus}
          disabled={checking}
          className="text-[10px] font-mono text-sky-300 hover:text-sky-200 underline underline-offset-2 disabled:opacity-50"
        >
          {checking ? t('disputeSending') : t('disputeCheckStatus')}
        </button>
        {checkFailed && (
          <p className="text-[10px] font-mono text-rose-400" data-testid="dispute-check-error">
            {t('disputeFailed')}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="w-full">
      {!open ? (
        <button
          type="button"
          data-testid="dispute-open"
          onClick={() => setOpen(true)}
          className="w-full py-2 px-3 rounded-xl bg-transparent border border-white/10 text-zinc-400 hover:text-zinc-200 text-[11px] font-mono flex items-center justify-center gap-1.5 cursor-pointer transition-colors"
        >
          <Flag className="w-3 h-3" />
          {t('disputeReport')}
        </button>
      ) : (
        <div className="space-y-2 p-2.5 rounded-xl bg-zinc-950/70 border border-white/10">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('disputePlaceholder')}
            maxLength={1000}
            rows={3}
            data-testid="dispute-reason"
            className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-[11px] text-zinc-200 resize-none focus:outline-none focus:border-sky-500/40"
          />
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="dispute-submit"
              onClick={submit}
              disabled={reason.trim().length < 3 || status === 'sending'}
              className="flex-1 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-30 text-black text-[11px] font-bold cursor-pointer transition-colors"
            >
              {status === 'sending' ? t('disputeSending') : t('disputeSubmit')}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-300 text-[11px] cursor-pointer transition-colors"
            >
              {t('disputeCancel')}
            </button>
          </div>
          {status === 'error' && (
            <p className="text-[10px] font-mono text-rose-400" data-testid="dispute-error">
              {t('disputeFailed')}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
