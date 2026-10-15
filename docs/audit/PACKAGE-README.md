# PULSAR — external audit package

This document orients an external auditor. It states what the system is, what the
trust model is, **what has already been found and fixed**, and **what has not been
verified** — so your time goes to the parts nobody has looked at yet.

The contract is `contracts/PulsarEscrow.sol` (613 lines). It custodies real USDT
on Polygon. Everything else exists to make that custody safe.

---

## 1. What the system does

Two players stake equal USDT into the escrow, play a best-of-three reaction duel,
and the winner is paid 98% of the pool with 2% to the treasury. If the duel
cannot be decided, both stakes are refunded after a timeout.

The trust model, stated plainly:

| Party | Can | Cannot |
|---|---|---|
| **Server** | decide *when* a round starts, verify reaction times, sign the settlement | move funds without the escrow's checks; invent a winner not signed by the oracle |
| **Oracle** (server-held key) | sign a settlement naming a winner and times | sign for a winner who is not a participant; sign past the deadline; sign after the refund window |
| **Player** | play, claim, refund | settle a duel they did not win; withdraw another player's stake |
| **Escrow** | hold stakes, pay the signed winner, refund on timeout | be drained by a non-participant |

**The single most important invariant:** *funds move only to a participant, only
against an oracle signature, and only once.* Everything below is in service of it.

---

## 2. Where to look first

| File | Why |
|---|---|
| `contracts/PulsarEscrow.sol` | the custody. Start here. |
| `contracts/test/PulsarEscrowSecurity.t.sol` | the adversarial cases already covered |
| `contracts/test/PulsarEscrowInvariants.t.sol` | the invariants the suite asserts |
| `api/oracle.py` | the signing path — digest construction, deadline clamping |
| `api/onchain.py` | the deposit gate and its fail-closed behaviour |
| `api/store.py` | transactional match state; the schema versioning guard |

---

## 3. What has ALREADY been found and fixed

Do not spend your budget re-finding these. Each was found, fixed, and has a test.

### Critical / high, in the contract and money path

| # | Finding | Status |
|---|---|---|
| C1 | The client, server and oracle each derived the on-chain `matchId` differently — the gate read a duel that did not exist | fixed, all three now use `sha256(raw id)` |
| C2 | A failed token-decimals read was cached as a fact, so a transient RPC failure poisoned the stake comparison | fixed, negatives are not cached |
| C3 | The deposit gate was enforced on a **fixed 2.5s poll**, which exceeded the rate limit and 429'd honest players out of matchmaking | fixed, exponential backoff |
| C4 | `createDuel` was **not idempotent** — any retry re-created a funded duel and reverted, leaving the stake in escrow | fixed, the creator reads on-chain state first |
| H10 | The deposit gate ran **inside** the store lock, so one slow RPC stalled every match in the process | fixed, gate moved outside the lock |
| H17 | A payout the token refused (blacklist, pause) reverted the whole settlement | fixed, credited to `pendingWithdrawals` |
| H19 | A stalling loser could deny the winner their payout | fixed, exclusive settlement window |
| H20 | A duel that paired late got a shortened play window | fixed, the clock anchors on activation |
| H24 | Voiding a stalled duel was a free option for the trailing player | fixed, the rule favours the leader |

### Found by the phase-10 harness (all fixed, all with tests)

- The API returned **403 on every request** in the split topology its own runbook describes (`ALLOWED_DOMAIN` was reused as the `TrustedHost` allowlist).
- `/api/health` returned **500** when the oracle key was absent → a crash loop instead of a report.
- `chain_reachable()` returned **true with a dead RPC**.
- `ledger_available()` was a config check surfaced as a reachability check.
- **Store contention returned HTTP 500** (157/157 queue requests at 1000 concurrent pollers) instead of a retryable 503.
- The app reported **wallet** errors as "server error".
- Firestore does not preserve map key order, so deriving the creator from "the first key" could name the **wrong player** as the one who deposits first.

### Known and NOT fixed — please look here

| Item | Why it is open |
|---|---|
| **The oracle's settlement deadline uses the SERVER's clock; the contract enforces the CHAIN's.** A drift > 600s makes every proof arrive expired. | Found by a time-travel test. The fix belongs in `api/oracle.py` (clamp against chain time) and is not done. |
| **`readsPerMatch` is 35 against a plan target of <20**, and excludes the client's polling. | Measured, recorded as an `xfail` with the number. Not optimised further. |
| **The deposit gate's cold path returned 200, not 409, on a dead RPC** in one chaos run. | Recorded as a NOTE in `scripts/chaos_suite.py`. Not explained. |
| **No KYC/AML, no geo-blocking, no fiat on-ramp.** | Product/legal decisions, not engineering. |

---

## 4. What has NOT been verified at all

Stated so you can price the work:

- **No external audit has ever been performed.** Every finding above was found by the same author who wrote the code.
- **No penetration test.** The API has rate limiting, SIWE auth and an admin secret, and none of it has been attacked by anyone but its author.
- **No production load test.** The 1000-poller run was against a Firestore **emulator**; the application's behaviour at 1000 concurrent users on real Firestore is unknown.
- **No mainnet rehearsal.** The full lifecycle has been driven on a local chain and is scripted for Amoy (`scripts/rehearse_amoy_e2e.py`), but has not run against a public network with real wallets.

---

## 5. How to build and test

```bash
# contracts
cd contracts && forge test            # 80 test functions, 8 files
forge coverage                        # gate: PulsarEscrow.sol >= 95% lines

# server
python3 -m pytest tests/ -q           # 334 tests
python3 -m mypy api                   # clean

# the whole gate
bash scripts/verify.sh                # 21 gates, 0 fail, 0 skip
```

`scripts/verify.sh` is the single entry point. It runs typecheck, unit tests on
both sides, the contract suite, the chain suite against a real anvil, the browser
E2E against the real stack, the chaos suite, the runbook drill, and a coverage
ratchet. If it is green, the claims in this document are reproducible.

---

## 6. Questions worth asking us

1. Can a non-participant cause a payout to anyone?
2. Can a settlement be replayed, or applied twice?
3. Can the oracle's key be used to pay a winner the players did not agree to?
4. What happens to both stakes if the server dies mid-duel?
5. Is there any path where a stake is neither paid nor refundable?
6. Can a player be griefed into a loss by an opponent who never plays?
7. Does the deadline logic hold if the chain's clock and the server's disagree?

Question 7 is the one we already know is weak. The rest are the ones we would ask.
