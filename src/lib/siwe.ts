/**
 * P0.5 — SIWE (EIP-4361) sign-in with replay protection.
 *
 * The wallet signature is the only proof of address ownership. It gates every
 * Firestore write and is the root of trust for future payout authorization.
 *
 * Replay protection: the message is bound to the exact domain + a UTC time
 * window, and a nonce can be supplied by a backend once the game server
 * exists (P1.11). The same signed message cannot be replayed elsewhere or
 * later, because domain and issued-at are part of the signed payload.
 */

export interface SIWESession {
  address: string;
  issuedAt: number;
  expiresAt: number;
}

const SIWE_SESSION_KEY = 'pulsar_siwe_session';
const SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24h re-verification cadence

export function buildSiweMessage(
  address: string,
  domain: string,
  chainId: number = 137,
  nonce?: string
): string {
  const issuedAt = new Date().toISOString();
  const expirationTime = new Date(Date.now() + SESSION_TTL_MS).toISOString();
  const lines = [
    `${domain} wants you to sign in with your Polygon account:`,
    address,
    '',
    'Prove you own this wallet. This signature grants no permission to move funds or spend tokens.',
    '',
    `URI: https://${domain}`,
    'Version: 1',
    `Chain ID: ${chainId}`,
    `Nonce: ${nonce || Math.random().toString(36).slice(2).padEnd(12, '0')}`,
    `Issued At: ${issuedAt}`,
    `Expiration Time: ${expirationTime}`,
  ];
  return lines.join('\n');
}

export async function verifySignedSiwe(
  message: string,
  signature: string,
  expectedAddress: string
): Promise<boolean> {
  try {
    const { ethers } = await import('ethers');
    const recovered = ethers.verifyMessage(message, signature);
    if (recovered.toLowerCase() !== expectedAddress.toLowerCase()) return false;

    const domainMatch = message.match(/^(?<domain>[^\s]+) wants you to sign in/);
    const uriMatch = message.match(/URI: https:\/\/(?<uri>[^\s]+)/);
    const domain = domainMatch?.groups?.domain;
    if (!domain || !uriMatch || uriMatch.groups?.uri !== domain) return false;
    if (typeof window !== 'undefined' && window.location.host !== domain) return false;

    const expirationMatch = message.match(/Expiration Time: (?<exp>[^\s]+)/);
    if (!expirationMatch?.groups?.exp) return false;
    return Date.now() < Date.parse(expirationMatch.groups.exp);
  } catch {
    return false;
  }
}

export function loadPersistedSiweSession(): SIWESession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(SIWE_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SIWESession;
    if (parsed?.address && parsed.expiresAt > Date.now()) return parsed;
    localStorage.removeItem(SIWE_SESSION_KEY);
  } catch {}
  return null;
}
