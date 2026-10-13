import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { reportError } from '../lib/monitoring';
import { useLanguage } from '../i18n/LanguageContext';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Audit #11 M3 — the app had NO Error Boundary: one runtime error in any
 * lazy route unmounted the whole tree into a silent blank screen (worse on
 * the game route, where the match settles server-side anyway). This catches
 * render/lifecycle errors, reports them to the existing monitoring hook
 * (Sentry DSN when configured), and offers a themed recovery card.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportError(error, { componentStack: info.componentStack });
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  private handleBack = (): void => {
    this.setState({ error: null });
    try {
      window.history.pushState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch {
      window.location.assign('/');
    }
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <ErrorFallback
        message={this.state.error.message}
        onReload={this.handleReload}
        onBack={this.handleBack}
      />
    );
  }
}

/**
 * The fallback UI.
 *
 * Audit 8.9: it is a function component so it can use `useLanguage()` — a class
 * boundary cannot, which is why its copy was hardcoded English in an app that
 * ships five languages.
 */
const ErrorFallback: React.FC<{ message: string; onReload: () => void; onBack: () => void }> = ({
  message,
  onReload,
  onBack,
}) => {
  const { t } = useLanguage();
  return (
        <div className="min-h-screen bg-[#07080a] text-slate-100 flex items-center justify-center p-6 font-sans">
          <div className="max-w-sm w-full space-y-4 text-center">
            <div className="w-12 h-12 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center mx-auto">
              <span className="text-rose-400 text-xl font-bold">!</span>
            </div>
            <div className="space-y-1">
              <h1 className="text-base font-bold text-white">{t('errorTitle')}</h1>
              <p className="text-xs text-zinc-400 leading-relaxed">{t('errorBody')}</p>
            </div>
            {message ? (
              <p className="text-[10px] font-mono text-zinc-500 break-all">{message}</p>
            ) : null}
            <div className="flex flex-col gap-2 pt-2">
              <button
                onClick={onReload}
                className="btn-primary py-2 text-xs font-bold cursor-pointer"
              >
                {t('errorReload')}
              </button>
              <button
                onClick={onBack}
                className="btn-ghost py-2 text-xs font-bold cursor-pointer"
              >
                {t('errorBackHome')}
              </button>
            </div>
          </div>
        </div>
      );
};
