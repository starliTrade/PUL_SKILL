import React, { useSyncExternalStore } from 'react';
import { Download } from 'lucide-react';

import { isUpdateWaiting, requestUpdate, subscribeSwUpdate, updateWasRequested } from '../lib/swUpdate';
import { useLanguage } from '../i18n/LanguageContext';

/**
 * Audit M-18 — "a new version is ready, reload when you want".
 *
 * The alternative (the old behaviour) was a worker that swapped itself in while
 * a duel was open. The player gets to choose the moment; until then the old
 * build keeps working against the old cache, which is still on disk because the
 * cache name is versioned.
 */
const subscribe = (fn: () => void) => subscribeSwUpdate(fn);
const snapshot = () => isUpdateWaiting();
const serverSnapshot = () => false;

export const UpdateBanner: React.FC = () => {
  const { t } = useLanguage();
  const waiting = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  if (!waiting) return null;
  const requested = updateWasRequested();

  return (
    <div
      data-testid="pulsar-update-available"
      role="status"
      className="w-full px-4 py-2 flex items-center gap-2 bg-sky-500/10 border-b border-sky-400/25 text-sky-200"
    >
      <Download className="w-3.5 h-3.5 shrink-0" />
      <p className="text-[11px] leading-snug flex-1">
        {requested ? t('updateReloading') : t('updateAvailable')}
      </p>
      {!requested && (
        <button
          type="button"
          onClick={() => requestUpdate()}
          className="text-[10px] uppercase tracking-wider px-2 py-1 rounded border border-sky-400/40 hover:bg-sky-400/10 shrink-0"
        >
          {t('updateNow')}
        </button>
      )}
    </div>
  );
};
