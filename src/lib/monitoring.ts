/**
 * P2.4 — Error monitoring (Sentry), wired behind an env var.
 *
 * Behavior when VITE_SENTRY_DSN is absent (default): a no-op — the helpers
 * exist so call sites don't need feature checks. Nothing is fabricated or
 * sent anywhere; the app runs exactly as before.
 *
 * Audit M44: the SDK is loaded LAZILY. A top-level
 * `import * as Sentry from "@sentry/react"` shipped the entire SDK — one of
 * the largest client dependencies — in every bundle, even for the default
 * deployment that has no DSN and never reports anything. The import now
 * happens inside `initErrorMonitoring()`, and only when a DSN exists.
 *
 * To activate: create a Sentry project, then set:
 *   VITE_SENTRY_DSN   — client DSN (public, safe for the browser)
 * In production also set on the game-server host:
 *   SENTRY_DSN        — server DSN (api/ monitoring, wired in api/main.py)
 */

type SentryModule = typeof import("@sentry/react");

const ENV = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;

const DSN: string = ENV?.VITE_SENTRY_DSN || "";

let sentry: SentryModule | null = null;
let initPromise: Promise<void> | null = null;

/**
 * Initialise error monitoring. No-op unless a DSN is configured.
 *
 * `dsnOverride` exists so tests (and embedders) can exercise the load path
 * without a build-time env var; production calls pass nothing.
 */
export const initErrorMonitoring = (dsnOverride?: string): Promise<void> => {
  const dsn = dsnOverride ?? DSN;
  if (!dsn) return Promise.resolve();
  if (initPromise) return initPromise;
  initPromise = (async () => {
    try {
      const Sentry = await import("@sentry/react");
      Sentry.init({
        dsn,
        // Release quality guardrails: keep noise down, keep real errors up.
        release: "pulsar-web@" + (ENV?.VITE_APP_VERSION || "dev"),
        environment: ENV?.MODE || "production",
        // Never send wallet addresses or other obvious identifiers.
        beforeSend(event) {
          if (event.user) {
            delete event.user.ip_address;
            if (event.user.username && /^0x[0-9a-fA-F]{40}$/.test(event.user.username)) {
              delete event.user.username;
            }
          }
          return event;
        },
      });
      sentry = Sentry;
    } catch {
      // Monitoring must never break the app. Allow a later retry.
      initPromise = null;
    }
  })();
  return initPromise;
};

/** Report a handled-but-notable error (e.g., on-chain claim failure). */
export const reportError = (error: unknown, context?: Record<string, unknown>): void => {
  if (!sentry) return;
  try {
    sentry.withScope((scope) => {
      if (context) scope.setContext("extra", context);
      sentry?.captureException(error);
    });
  } catch {
    /* ignore */
  }
};

export const errorMonitoringEnabled = (): boolean => sentry !== null;
