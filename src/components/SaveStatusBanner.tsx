import React, { useSyncExternalStore } from 'react';
import { AlertTriangle } from 'lucide-react';

import { clearSaveFailure, getSaveFailures, subscribeSaveStatus } from '../lib/saveStatus';
import { useLanguage } from '../i18n/LanguageContext';

/**
 * Audit M-24 — the banner that says a save did not reach the server.
 *
 * Renders nothing when everything is fine. When a save failed, it names the area
 * and offers a dismiss that only clears the banner, not the underlying state:
 * the next successful save clears it for real (the data layer calls
 * `clearSaveFailure`).
 */
export const SaveStatusBanner: React.FC = () => {
  const { t } = useLanguage();
  const failures = useSyncExternalStore(subscribeSaveStatus, getSaveFailures, getSaveFailures);
  if (failures.length === 0) return null;

  return (
    <div
      data-testid="pulsar-save-status"
      role="alert"
      className="w-full px-4 py-2 flex flex-col gap-1 bg-rose-500/10 border-b border-rose-400/25 text-rose-200"
    >
      {failures.map((f) => (
        <div key={`${f.area}-${f.kind}`} className="flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <p className="text-[11px] leading-snug flex-1">
            {f.kind === 'read' ? t('saveReadFailed') : t('saveWriteFailed')}
            {f.count > 1 ? ` (${t('saveAttempts', { count: f.count })})` : ''}
          </p>
          <button
            type="button"
            onClick={() => clearSaveFailure(f.area, f.kind)}
            className="text-[10px] uppercase tracking-wider opacity-70 hover:opacity-100 shrink-0"
            aria-label={`${t('saveDismiss')} — ${f.area}`}
          >
            {t('saveDismiss')}
          </button>
        </div>
      ))}
    </div>
  );
};
