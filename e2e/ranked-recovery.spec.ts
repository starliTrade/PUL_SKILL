/**
 * Recovery after a reload (plan items 10.1: "refresh mid-match → resume" and
 * "refresh after settlement → auto-settle (H11)").
 *
 * A player who reloads mid-duel must not lose their match, and a player who
 * reloads after it settled must still be settled — their stake is on-chain, so
 * "the tab was closed" cannot mean "the money is stuck".
 *
 * The match is created through the REAL API and the REAL escrow, then the
 * browser is seeded with exactly what a reload leaves behind: the SIWE session
 * and the active-match pointer in localStorage. Nothing else is faked.
 */
import { expect, test, type Page } from '@playwright/test';
import { installMockWallet, ANVIL_ACCOUNTS } from './wallet';
import { clearEligibilityGate } from './helpers';
import { mintTestUSDT } from './chain';
import { readManifest } from './chain';
import { API_ORIGIN } from './helpers';

const API = API_ORIGIN;
const SESSION_KEY = 'pulsar.server.session.v1';
const ACTIVE_MATCH_KEY = 'pulsar_active_ranked_match';
const STAKE = 1;

interface Session {
  address: string;
  token: string;
  issuedAt: number;
}

async function signIn(privateKey: string): Promise<Session> {
  const { privateKeyToAccount } = await import('viem/accounts');
  const account = privateKeyToAccount(privateKey as `0x${string}`);
  const nonceRes = await fetch(`${API}/api/auth/nonce`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address: account.address.toLowerCase() }),
  });
  const nonce = (await nonceRes.json()) as { message: string };
  const signature = await account.signMessage({ message: nonce.message });
  const verifyRes = await fetch(`${API}/api/auth/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: nonce.message, signature }),
  });
  const verified = (await verifyRes.json()) as { token: string };
  // Plan item 11.3/G2: staked play requires a SERVER-RECORDED eligibility
  // attestation. The gate is on `/api/queue` — the entry — not on the
  // round/settle/claim endpoints, so committed money is never trapped.
  const confirmed = await fetch(`${API}/api/eligibility/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${verified.token}` },
    body: JSON.stringify({ ageConfirmed: true }),
  });
  if (!confirmed.ok) throw new Error(`eligibility confirm failed: ${confirmed.status}`);
  return { address: account.address.toLowerCase(), token: verified.token, issuedAt: Date.now() };
}

async function queue(session: Session): Promise<Record<string, unknown>> {
  const res = await fetch(`${API}/api/queue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.token}` },
    body: JSON.stringify({ stake: STAKE, rttMs: 40 }),
  });
  // Read the body ONCE: an eager message would consume it and leave `.json()`
  // with "Body is unusable: Body has already been read".
  const text = await res.text();
  expect(res.ok, `queue failed: ${res.status} ${text}`).toBeTruthy();
  return JSON.parse(text) as Record<string, unknown>;
}

/**
 * Connect the mock wallet, exactly as a player would.
 *
 * A reload leaves the SESSION and the match pointer in localStorage, but the
 * wallet connection itself is not persisted — so the recovery path only runs
 * once the player reconnects. Without this the app correctly refuses to enter a
 * staked duel and shows "Web3 Wallet Required for Staked Duels".
 */
async function connectWallet(page: Page): Promise<void> {
  await page.goto('/lobby');
  await clearEligibilityGate(page);
  await page.getByRole('button', { name: /Connect Wallet/i }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole('button', { name: /MetaMask/i }).first().click();
  await page.waitForTimeout(3000);
}

/** Seed the browser with exactly what a reload leaves behind. */
async function seed(page: Page, session: Session, matchId: string): Promise<void> {
  await page.addInitScript(
    ([sessionKey, matchKey, s, m]) => {
      localStorage.setItem(sessionKey, s);
      localStorage.setItem(matchKey, m);
    },
    [
      SESSION_KEY,
      ACTIVE_MATCH_KEY,
      JSON.stringify(session),
      JSON.stringify({ matchId, stake: STAKE, savedAt: Date.now() }),
    ] as const
  );
}

const UNITS = STAKE * 1_000_000;

/** Both players lock the stake in the escrow — the deposit gate requires it. */
async function lockStakes(
  manifest: ReturnType<typeof readManifest>,
  matchId: string,
  playerKeys: [string, string]
): Promise<void> {
  const { keccak256, toHex } = await import('viem');
  const { createWalletClient, http } = await import('viem');
  const { privateKeyToAccount } = await import('viem/accounts');
  const { anvil } = await import('viem/chains');
  void keccak256;
  void toHex;

  const key = `0x${await sha256Hex(matchId)}`;
  const amount = BigInt(UNITS);
  // The SAME identities that signed in. The deposit gate compares the duel's
  // participants to the match's, so depositing from a different pair is refused
  // with "On-chain duel does not match this match (stake or participants differ)".
  const accounts = playerKeys.map((k) => privateKeyToAccount(k as `0x${string}`));
  const clients = accounts.map((a) =>
    createWalletClient({ account: a, chain: anvil, transport: http(manifest.rpcUrl) })
  );

  for (const client of clients) {
    await client.writeContract({
      address: manifest.token as `0x${string}`,
      abi: [
        {
          name: 'approve',
          type: 'function',
          stateMutability: 'nonpayable',
          inputs: [{ name: 's', type: 'address' }, { name: 'a', type: 'uint256' }],
          outputs: [{ type: 'bool' }],
        },
      ] as const,
      functionName: 'approve',
      args: [manifest.escrow as `0x${string}`, amount],
    });
  }
  const escrowAbi = [
    {
      name: 'createDuel',
      type: 'function',
      stateMutability: 'nonpayable',
      inputs: [{ name: 'm', type: 'bytes32' }, { name: 's', type: 'uint256' }],
      outputs: [],
    },
    {
      name: 'joinDuel',
      type: 'function',
      stateMutability: 'nonpayable',
      inputs: [{ name: 'm', type: 'bytes32' }],
      outputs: [],
    },
  ] as const;
  await clients[0].writeContract({
    address: manifest.escrow as `0x${string}`,
    abi: escrowAbi,
    functionName: 'createDuel',
    args: [key as `0x${string}`, amount],
  });
  await clients[1].writeContract({
    address: manifest.escrow as `0x${string}`,
    abi: escrowAbi,
    functionName: 'joinDuel',
    args: [key as `0x${string}`],
  });
}

async function sha256Hex(text: string): Promise<string> {
  const { createHash } = await import('node:crypto');
  return createHash('sha256').update(text).digest('hex');
}

/** Play the best-of-three through the API, waiting like a player does. */
async function playRounds(creator: Session, joiner: Session, matchId: string): Promise<void> {
  const post = async (path: string, body: Record<string, unknown>, token: string) => {
    const res = await fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, body: text ? JSON.parse(text) : {} };
  };

  for (let round = 0; round < 3; round += 1) {
    const view = await fetch(`${API}/api/match/${matchId}`, {
      headers: { Authorization: `Bearer ${creator.token}` },
    }).then((r) => r.json() as Promise<Record<string, unknown>>);
    if (view.status !== 'active') break; // 2-0 is a legitimate finish

    for (const [session, measured] of [
      [creator, 240 + round],
      [joiner, 300 + round],
    ] as const) {
      const commit = await post(
        '/api/round/commit',
        { matchId, roundIndex: round, intentHash: `0x${'ab'.repeat(32)}` },
        session.token
      );
      expect(commit.ok, `commit: ${commit.status} ${JSON.stringify(commit.body)}`).toBeTruthy();
      const reveal = await post('/api/round/target', { matchId, roundIndex: round }, session.token);
      expect(reveal.ok, `target: ${reveal.status} ${JSON.stringify(reveal.body)}`).toBeTruthy();
      // The server measures the REAL elapsed time and refuses a claim faster
      // than it observed, so a driver must wait like a player.
      await new Promise((r) => setTimeout(r, (reveal.body.targetMs as number) + measured));
      const result = await post(
        '/api/round/result',
        {
          matchId,
          roundIndex: round,
          measuredMs: measured,
          resultProof: reveal.body.resultProof,
        },
        session.token
      );
      expect(result.ok, `result: ${result.status} ${JSON.stringify(result.body)}`).toBeTruthy();
    }
  }
}

test.describe('the ranked duel survives a reload', () => {
  test.setTimeout(180_000);

  test('a reload mid-match resumes the duel, and a reload after it settles still settles', async ({
    browser,
  }) => {
    const manifest = readManifest();
    // A DIFFERENT pair from the other ranked specs. The suite reuses anvil's
    // deterministic accounts, so sharing them means `/api/queue` hands this spec
    // a match left by an earlier one — and the server's in-process cache cannot
    // be reset from a test. The escrow does not care which addresses play, so
    // using its own pair makes this spec independent.
    //
    // Note the index: `manifest.players[0]` is anvil account **1** (the deployer
    // is account 0), and reading it as `accountIndex: 0` once made the app sign
    // in as a different address than the match's creator — every
    // `/api/match/{id}` read came back 403, which looked like a recovery bug.
    const creatorIndex = 2;
    const joinerIndex = 3;
    const creatorKey = ANVIL_ACCOUNTS[creatorIndex].key as string;
    const joinerKey = ANVIL_ACCOUNTS[joinerIndex].key as string;

    for (const index of [creatorIndex, joinerIndex]) {
      await mintTestUSDT(ANVIL_ACCOUNTS[index].address, 50);
    }

    // A real match, through the real API.
    const creator = await signIn(creatorKey);
    const joiner = await signIn(joinerKey);
    const first = await queue(creator);
    // The suite reuses anvil's deterministic players, so a match from an
    // earlier spec is still in the store and `/api/queue` hands it back. That is
    // the same stale-state footgun the Python flow test documents; skip rather
    // than fail, because the test cannot reset the server's in-process cache.
    test.skip(
      first.status !== 'waiting',
      `the server is holding a match for this player from an earlier spec (${String(
        first.status
      )}) — restart the API (scripts/start_e2e_stack.sh --stop && scripts/start_e2e_stack.sh)`
    );
    const second = await queue(joiner);
    expect(second.status).toBe('active');
    const matchId = second.matchId as string;

    // --- Item 1: reload mid-match resumes -----------------------------------
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await installMockWallet(page, { accountIndex: creatorIndex });
    await seed(page, creator, matchId);
    await connectWallet(page);
    await page.goto('/game/reaction');

    // The recovery runs when the player taps the verify node — that is the
    // entry point (`handleVerifyNodeClick` calls `recoverServerMatch` before
    // starting a new match), so a reload lands on the handshake, not the arena.
    await expect(page.getByTestId('pulsar-verify-node')).toBeVisible({ timeout: 45_000 });
    await page.getByTestId('pulsar-verify-node').click();

    // The duel is back: the round counter is live and the arena is server
    // verified, which can only come from `recoverServerMatch` having fetched
    // the match and restored the best-of-three state.
    await expect(page.getByText(/Ranked · Server verified/i).first()).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText(/Round \d of 3/i).first()).toBeVisible({ timeout: 45_000 });
    await ctx.close();

    // --- Item 2: reload after settlement still settles ----------------------
    // The match must actually be terminal, so lock both stakes on-chain and
    // play the rounds — the deposit gate refuses a round otherwise, and the
    // server refuses to settle a match that is still in progress.
    await lockStakes(manifest, matchId, [creatorKey, joinerKey]);
    await playRounds(creator, joiner, matchId);
    const settle = await fetch(`${API}/api/match/${matchId}/settle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${creator.token}` },
      body: JSON.stringify({}),
    });
    const settleText = await settle.text();
    expect(settle.ok, `settle failed: ${settle.status} ${settleText}`).toBeTruthy();

    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    await installMockWallet(page2, { accountIndex: creatorIndex });
    await seed(page2, creator, matchId);
    await connectWallet(page2);
    await page2.goto('/game/reaction');
    await expect(page2.getByTestId('pulsar-verify-node')).toBeVisible({ timeout: 45_000 });
    await page2.getByTestId('pulsar-verify-node').click();
    // A settled match must land on a terminal screen, not on the arena and not
    // on an error shell.
    await expect(
      // Audit 2026-10-16: this used to accept `Match voided|refunds` as well.
      // The test's purpose is H11 — refresh after settlement → AUTO-SETTLE, i.e.
      // the winner must be PAID. A void returns BOTH stakes and pays nobody, so
      // accepting it meant a payout bug could ship green. Assert the outcome the
      // test is named for.
      page2.getByText(/MATCH VICTORY|MATCH DEFEAT/i).first()
    ).toBeVisible({ timeout: 60_000 });
    await ctx2.close();
  });
});
