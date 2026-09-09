/**
 * P2.4 — Error monitoring (Sentry), wired behind an env var.
 *
 * Behavior when VITE_SENTRY_DSN is absent (default): a no-op — the helpers
 * exist so call sites don't need feature checks. Nothing is fabricated or
 * sent anywhere; the app runs exactly as before.
 *
 * To activate: create a Sentry project, then set:
 *   VITE_SENTRY_DSN   — client DSN (public, safe for the browser)
 * In production also set on the game-server host:
 *   SENTRY_DSN        — server DSN (api/ monitoring, wired in api/main.py)
 */

import * as Sentry from "@sentry/react";

const DSN: string =
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_SENTRY_DSN || "";

let initialized = false;

export const initErrorMonitoring = (): void => {
  if (!DSN || initialized) return;
  initialized = true;
  try {
    Sentry.init({
      dsn: DSN,
      // Release quality guardrails: keep noise down, keep real errors up.
      release: "pulsar-web@" + ((import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_APP_VERSION || "dev"),
      environment: (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.MODE || "production",
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
  } catch {
    // Monitoring must never break the app.
  }
};

/** Report a handled-but-notable error (e.g., on-chain claim failure). */
export const reportError = (error: unknown, context?: Record<string, unknown>): void => {
  if (!initialized) return;
  try {
    Sentry.withScope((scope) => {
      if (context) scope.setContext("extra", context);
      Sentry.captureException(error);
    });
  } catch {
    /* ignore */
  }
};

export const errorMonitoringEnabled = (): boolean => initialized;
