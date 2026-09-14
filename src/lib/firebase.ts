import { initializeApp, getApps, getApp } from 'firebase/app';
import { getFirestore, Firestore } from 'firebase/firestore';

// Audit #7 R7 — Firebase web config now comes from Vite env vars instead of a
// committed JSON file (the file carried the database id + OAuth client id and
// was tracked in git). Web API keys are public by design, but committing the
// database id invited enumeration against open rule paths.
//
// Set these in the environment (dev: .env.local, prod: deploy env):
//   VITE_FIREBASE_API_KEY, VITE_FIREBASE_AUTH_DOMAIN, VITE_FIREBASE_PROJECT_ID,
//   VITE_FIREBASE_STORAGE_BUCKET, VITE_FIREBASE_MESSAGING_SENDER_ID,
//   VITE_FIREBASE_APP_ID, VITE_FIRESTORE_DATABASE_ID
//
// When the vars are absent the cloud layer is disabled HONESTLY: local-only
// play keeps working, the leaderboard simply reports "no matches yet", and a
// console warning names the missing configuration.

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};

const apiKey = env.VITE_FIREBASE_API_KEY;
const projectId = env.VITE_FIREBASE_PROJECT_ID;
const databaseId = env.VITE_FIRESTORE_DATABASE_ID;

let db: Firestore | null = null;

if (apiKey && projectId && databaseId) {
  const app =
    getApps().length === 0
      ? initializeApp({
          apiKey,
          authDomain: env.VITE_FIREBASE_AUTH_DOMAIN ?? `${projectId}.firebaseapp.com`,
          projectId,
          storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET ?? `${projectId}.appspot.com`,
          messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID ?? '',
          appId: env.VITE_FIREBASE_APP_ID ?? '',
        })
      : getApp();
  db = getFirestore(app, databaseId);
} else {
  console.warn(
    '[firebase] Cloud features disabled: VITE_FIREBASE_* / VITE_FIRESTORE_DATABASE_ID are not set. ' +
      'The app runs local-only until they are provided.'
  );
}

export { db };

/** Firestore handle for cloud-capable code paths.
 * Throws an honest, typed error when Firebase env vars are absent — callers
 * already wrap cloud work in try/catch, so the error degrades to local-only
 * mode instead of a silent failure. */
export function getDb(): Firestore {
  if (!db) {
    throw new Error('Cloud features are disabled: Firebase env vars are not set.');
  }
  return db;
}
