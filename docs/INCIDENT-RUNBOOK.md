# PULSAR — Incident Runbook (plan item 6.6)

Operator procedures for the failures that cost money or trust. Companion to
`DEPLOYMENT.md` (how to deploy) and `HOW-IT-WORKS.md` (how the protocol works).

Everything here is grounded in what the code actually does. Where a step depends
on a value, the value is named so you can confirm it before acting.

## 0. First: what does the server think is happening?

`GET /api/health` is unauthenticated and answers the three questions an operator
asks during an incident. It carries no secret and no RPC URL.

| Field | Meaning | Bad value |
|---|---|---|
| `ok` | the process is up | — |
| `matchStore` | `memory` or `firestore` | `memory` in production = **no durability** |
| `ledger.available` | the economy ledger is reachable | `false` = progression/leaderboard are not being written |
| `ledger.failures` | per-function failure counts | any non-zero means writes are being dropped |
| `chainId` | the chain the server signs for | must equal the client's `VITE_CHAIN_ID` and the contract's chain |
| `escrowConfigured` | real money is actually enabled | `false` while you expect money = the app is practice-only |
| `prodLike` | the server is in production mode | `false` in production = configuration is not being enforced |
| `sweep` | the maintenance sweep (see §5) | a rising failure count means prizes are not being rescued |
| `rpc.reachable` / `rpc.chainId` | the RPC endpoint | `false`, or a chain id that is not the expected one |
| `tokenDecimals` | the payment token's decimals | `"unread"` = the deposit gate cannot compare stakes |
| `oracleAddress` | the signer the server holds | must equal the contract's `oracleSigner` |
| `rateLimit.backend` / `fallbacks` | which limiter is enforcing | `firestore` with a rising `fallbacks` count |

`GET /api/metrics` carries the counters (Firestore reads, per-endpoint latency,
limiter fallbacks, signature failures).

Admin tooling (requires `X-Admin-Secret: $PULSAR_ADMIN_SECRET`; the endpoint
returns 404 when the secret is unset, so it fails closed):

```
GET  /api/admin/match/{matchId}          full match state
GET  /api/admin/players?q=0x…            a player's live matches
POST /api/admin/match/{matchId}/void     force-void
POST /api/admin/match/{matchId}/settle   force-settle
```

---

## 1. RPC is down or unreachable

**Symptoms.** `rpc.reachable: false`; `tokenDecimals: "unread"`; players report
"deposit could not be verified"; `/api/round/result` returns the deposit-gate error.

**What is at risk.** The deposit gate fails **closed** — a round cannot be
played until the stake is confirmed on chain. That is the correct direction: no
money moves on a guess. Duels already in progress are not voided by this; the
play clock keeps running.

**Do.**
1. Confirm the RPC URL (`ESCROW_RPC_URL`) and that the provider is not simply
   rate-limiting you. `rpc.chainId` should equal the expected chain.
2. Point `ESCROW_RPC_URL` at a second provider and restart. The token-decimals
   cache is deliberately *not* sticky: a failed read is not cached as a fact
   (audit C2), so it recovers on the next successful read.
3. Watch `sweep` — the re-sign sweep (§5) cannot run without RPC.

**Do not.** Do not disable the deposit gate to "unblock" players. That is the
one control that stops an unbacked duel from settling.

**If it stays down past the refund horizon** (`MATCH_TIMEOUT` 30 min from
activation + `REFUND_GRACE` 10 min = the refund opens at 40 minutes): tell
players to use the refund button. Refunds are permissionless and do not need
the server.

---

## 2. Firestore is down, or the ledger is dead

**Symptoms.** `ledger.available: false`, or `ledger.failures` climbing;
`matchStore: memory` when you expect `firestore`; the leaderboard stops moving;
progression stops updating.

**What is at risk.** The ledger is a **shadow of the money path** — it is
deliberately best-effort. Money still moves on chain; the recorded
wins/XP/prize rows may lag or be missing. The rate limiter degrades to the
in-process window (`rateLimit.backend`), which is per-process: with N replicas
the effective cap becomes N × limit.

**Do.**
1. Confirm credentials/network. `PULSAR_MATCH_STORE=firestore` is required for
   durability; if the server fell back to `memory`, **matches do not survive a
   restart** — treat that as the priority.
2. When Firestore returns, the ledger back-fills on the next settlement of each
   match (the `settlements/{settlementId}` gate makes it idempotent — a replay
   cannot double-count).
3. If you must keep serving money while Firestore is down, understand that
   rate limiting is weaker; watch `/api/metrics` for abuse.

**Do not.** Do not hand-edit `users/*` counters to "catch up" — the next
settlement writes server-computed progression and will overwrite you.

---

## 3. Oracle key compromise

**Symptoms.** You have reason to believe `ORACLE_PRIVATE_KEY` leaked. Assume any
signature it can produce is attacker-controlled.

**What is at risk.** The oracle signs settlement proofs. A leaked key lets an
attacker mint a valid proof for any active duel and take the pot.

**Do, in this order.**
1. **Rotate on chain first.** `setOracleSigner(newAddress)` is behind
   `ADMIN_TIMELOCK` (2 days) — start it immediately; the delay is the point.
   Until it lands, the compromised key is still accepted.
2. Generate a new key, store it as a platform secret, and set
   `ORACLE_PRIVATE_KEY` + `ORACLE_ADDRESS` on the server. The server will refuse
   to start without `ORACLE_SIGNING_SECRET` and will sign with whatever key it
   is given, so verify `oracleAddress` on `/api/health` after the restart.
3. While the timelock runs: consider pausing new real-money duels by unsetting
   `VITE_ESCROW_ADDRESS` on the client (the app reverts to honest practice-only
   mode instantly, see §8).
4. `usedSignatures` on chain prevents replaying a *specific* proof, but the
   attacker can mint fresh ones — it is not a mitigation for a leaked key.

**Do not.** Do not rotate only the server env and assume you are safe; the
contract still trusts the old address until the timelock lands.

---

## 4. Stuck funds

Four distinct cases. Identify which one you have before acting.

### 4a. A winner's prize is unclaimed

The proof is valid for 10 minutes; after that the server's re-sign path mints a
fresh one (same result, new deadline + nonce) — but only while the duel is
inside `MATCH_TIMEOUT` (30 min from activation). Past that horizon the contract
refuses any settlement and the only exit is a refund.

**Do.** Have the winner open the result screen and press **Retry on-chain
claim**. The client re-submits the stored proof; the server re-signs if it
expired. If the re-sign window has passed, the duel is refundable — see 4b.

### 4b. The refund window has opened and nobody has claimed

`refundTimeoutMatch` is permissionless and opens at `MATCH_TIMEOUT` +
`REFUND_GRACE` (40 minutes from activation). Either player can call it; each
gets their own stake back.

**Do.** Press **Refund after 40-min timeout** in the UI, or call
`refundTimeoutMatch(matchId)` directly. Note the settlement window is
*exclusive* until `MATCH_TIMEOUT`: a refund before that reverts by design
(audit H19) so a loser cannot refund a match they lost.

### 4c. A payout was deferred

If the token refused a direct transfer (Tether blacklist, paused token), the
contract credits `pendingWithdrawals` instead of reverting the whole
settlement. The money is on chain and reachable.

**Do.** The player presses **Claim** on the *Pending payout* card in their
profile. The client checks gas before claiming.

**If the token refuses the recipient permanently** (a Tether blacklist), the
credit is held, not lost — and that is deliberate. The escrow will not pay an
alternate address (that would route around the token issuer's own control) and
there is no admin sweep (that would be a seizure). The money stays on
`pendingWithdrawals[recipient]` until the token allows the transfer; if the
blacklist is lifted, the claim pays in full. The other side of the duel is
unaffected: the fee still reaches the treasury, and the loser's stake was
genuinely lost. Do not "fix" this by editing the contract — the correct answer
to a token-level block is to leave it in force.

### 4d. Funds are in a duel whose match record is gone

**Do.** Find the duel with `GET /api/admin/match/{matchId}`. If the record is
missing entirely, the on-chain state is the authority: read `matches(bytes32)`
on the escrow. A duel that is `Active` past the horizon is refundable by either
player; a `Settled` duel has already paid out.

---

## 5. Settlement stalled / the sweep is dead

**Symptoms.** `sweep` failures climbing; players report a decided match that
never settles; prizes unclaimed with no retry working.

**What the sweep does.** Every authenticated queue poll runs, at most once per
`SWEEP_MIN_INTERVAL_SECONDS` (15 s): (a) finalizes matches whose grace window
passed, (b) re-signs settled matches whose envelope expired while both clients
were offline. It is the rescue path for "both players closed their tabs".

**Most likely cause.** A missing Firestore composite index on
`pulsar_matches (status, settled_at)`. Without it the query is rejected — and
this used to be swallowed. It is now counted and surfaced in `sweep`.

**Do.**
1. Check the sweep's reported error.
2. Deploy `firestore.indexes.json` (it declares exactly that index).
3. Confirm the failure count stops rising.

---

## 6. Rate limiter degraded

**Symptoms.** `rateLimit.backend: firestore` with a rising `fallbacks` count.

**What is at risk.** The in-process fallback is per-replica, so the effective
limit is multiplied by the replica count. It is a safety net, not the control.

**Do.** Restore the Firestore path (§2). Treat a sustained fallback as an
availability incident for the anti-abuse controls on settle/claim/auth.

---

## 7. Chain-id mismatch

**Symptoms.** Every settlement signature is rejected on chain; `chainId` on
`/api/health` differs from the client's `VITE_CHAIN_ID` or the deployed
contract's chain.

**Do.** Fix the configuration and restart. The digest binds `block.chainid` and
the contract address, so a mismatch is not recoverable at runtime. Note the
client's `ESCROW_TIMING`/chain constants are pinned to the Solidity source by a
test — if that test is failing, the layers have already drifted.

---

## 8. Emergency stop / rollback

**To disable real money immediately:** unset `VITE_ESCROW_ADDRESS` on the client
and redeploy. The app reverts to honest practice-only mode: no deposits, no
settlements, no prize claims. Money already in escrow is unaffected and remains
recoverable via §4 (the escrow does not need the client).

**To stop new duels but keep the UI:** leave the escrow configured and refuse
new queue entries at the edge (or set `PULSAR_MATCH_STORE` to an unconfigured
value and accept the durability loss — not recommended).

**To roll back a deploy:** the client and server are independently deployable.
Rolling the client back does not affect settled money; rolling the server back
does not affect on-chain state. The one thing you cannot roll back is a
settlement.
