# PULSAR — Economics & fee model (decision record for audit M-12)

**Status:** accepted risk, documented. **Owner:** product. **Last reviewed:** 2026-10-23.
**Code:** `contracts/PulsarEscrow.sol` (`PLATFORM_FEE_BPS`, `FEE_DENOMINATOR`,
`treasuryWallet`, `ADMIN_TIMELOCK`).

The audit finding (M-12) was: *`PLATFORM_FEE_BPS` is a constant and the treasury
is a single address, so the business model cannot change without a redeploy.*
That is true, and it is accepted on purpose. This document says what the model
is, why freezing it is the right call for now, what it costs, and what would
have to be true to change it.

---

## 1. The model as deployed

| Parameter | Value | Where |
|---|---|---|
| Fee on the **pool** (both stakes) | **200 bps = 2.00 %** | `PLATFORM_FEE_BPS` |
| Denominator | 10 000 | `FEE_DENOMINATOR` |
| Winner share | **98.00 %** | `pool − fee` |
| Fee recipient | `treasuryWallet` | timelocked rotation, 2 days |
| Deposit fee | **none** | — |
| Withdrawal fee | **none** — `withdraw()` pays the full deferred amount | — |
| Gas | paid by whoever sends the transaction (the player's own `createDuel` / `joinDuel` / `settleDuel`) | — |
| Rounding | `fee = floor(pool × 200 / 10 000)`, `prize = pool − fee` — dust goes to the **winner** | `settleDuel` |

The fee is charged once, on settlement, out of the escrowed pool. A duel that is
refunded (timeout) or cancelled charges **nothing**: both players get their own
stake back in full.

### Worked examples (stake is per player)

| Stake | Pool | Fee 2 % | Winner receives | Winner's net profit |
|---:|---:|---:|---:|---:|
| 1 USDT | 2.00 | 0.04 | **1.96** | +0.96 |
| 2 USDT | 4.00 | 0.08 | **3.92** | +1.92 |
| 5 USDT | 10.00 | 0.20 | **9.80** | +4.80 |
| 10 USDT | 20.00 | 0.40 | **19.60** | +9.60 |

`tests/unit/test_economics_doc.py` recomputes this table from the constants in
the contract and from the constants in the client, so the numbers in this file
cannot drift from the code that pays them.

---

## 2. Why the fee is a constant (and not an owner-settable parameter)

A `setFeeBps()` would be the obvious "flexibility" change. It is rejected:

1. **It is a rake on live money.** Whoever holds the key could raise the fee to
   100 % between a player's deposit and their settlement. A timelock helps only
   if players watch governance events, which they do not.
2. **The fee is part of the deal.** Every localization of the UI states
   "98 % payout · 2 % fee", as do the ToS. A mutable fee makes that copy a
   statement about the past.
3. **It shrinks the audit surface.** A constant cannot be misconfigured, cannot
   be set by a compromised key, and cannot drift between chains.

**Cost, stated plainly:** changing the business model — a lower rake for a
promotion, a referral share, a subscription tier — needs a new deployment and
the migration procedure in `docs/UPGRADE-PATH.md`. That is a few hours of
operator work, not a code rewrite.

**Revisit trigger:** if the product needs per-tier or promotional pricing, do
not add a setter to this contract. Deploy a versioned escrow whose fee schedule
is decided at construction and stated on chain at deploy time, and run the
migration. What must not happen is a fee that an operator can change while
duels are open. Revisit this document when the product or the chain changes; the decision is only good for the assumptions it was made under.

---

## 3. Treasury

* `treasuryWallet` receives the fee **inline at settlement**, not through a
  balance the operator withdraws later. There is no pot of fees sitting in the
  contract for somebody to take: `totalLocked` (see `docs/UPGRADE-PATH.md`)
  counts player money only, and the fee leaves the escrow in the same
  transaction.
* Rotation is **timelocked 2 days** (`setTreasuryWallet` → `applyTreasuryWallet`),
  so a typo or a compromised owner key cannot redirect tomorrow's fees instantly,
  and it can be cancelled (`cancelPendingAdminChanges`).
* If the token refuses the treasury transfer (a blacklist, a paused token), the
  fee is credited to `pendingWithdrawals[treasury]` instead of reverting the
  player's prize (audit H17). The treasury then calls `withdraw()`.
* **Recommendation for real money:** `treasuryWallet` must be a multisig
  (Safe on the target chain), not an EOA. The contract cannot enforce that; the
  deployment checklist should.

---

## 4. Unit economics (why this is testnet-only today)

The fee is 4 % of what a player stakes (2 % of a two-stake pool). Settlement is
sent by the **player**, so on a mainnet the winner's gas is a real cost against
a real prize. Measured gas from the test suite (`forge test --gas-report`,
local EVM, not Amoy):

| Operation | Gas (min–max) |
|---|---:|
| `createDuel` | ~209 000 |
| `joinDuel` | ~36 000 – 132 000 |
| `settleDuel` | ~38 000 – 225 000 |
| `refundTimeoutMatch` | ~34 000 – 64 000 |

Using 150 000 gas as a settlement round-trip and $3 000/ETH, the break-even
stake — where one settlement's gas equals the whole fee — is:

| Chain gas price | Cost of 150k gas | Stake where `fee == gas` | Stake for `fee ≥ 10 × gas` |
|---|---:|---:|---:|
| 30 gwei (Ethereum L1, quiet) | ≈ $13.50 | ≈ **$337** | ≈ **$3 375** |
| 5 gwei | ≈ $2.25 | ≈ $56 | ≈ $563 |
| 0.03 gwei (Polygon-class L2) | ≈ $0.014 | ≈ $0.34 | ≈ $3.40 |
| Amoy testnet | 0 (faucet) | n/a | n/a |

**Conclusion, stated without softening:** with the current stake ladder
(1 / 2 / 5 / 10 USDT), an Ethereum-L1 deployment is economically absurd — a
1 USDT duel costs the winner more in gas than the entire pool. The product is
viable on an L2/rollup (or a gasless relayer/account-abstraction setup that pays
gas on the player's behalf and charges for it), and it is free on Amoy, which is
what the current plan targets. **Do not deploy the current stake ladder to L1.**

This also bounds the keeper (`scripts/keeper.py`): it pays gas for timeout
refunds out of its own key. At ~50k gas per refund its cost is small, but it is
not zero, and on an L1 it would exceed the fee revenue from small duels. The
keeper must run with a funded key whose spend is monitored (see
`docs/INCIDENT-RUNBOOK.md`).

---

## 5. What a change to this model would look like

| Change | Requires | Migration |
|---|---|---|
| Different rake | new contract with a different `PLATFORM_FEE_BPS` | yes — `docs/UPGRADE-PATH.md` |
| Promo / referral share | new contracts (fee splitter), not a setter | yes, and a treasury that can split |
| Subscription instead of rake | off-chain billing + zero-fee escrow | a new deploy, or a version that reads a fee of 0 |
| Different stake ladder | **no contract change** — the ladder is server/UI config, bounded below by `MIN_STAKE_UNITS` | no |
| Different token | constructor parameter | new deploy (the token is immutable) |

The stake ladder is deliberately *not* on chain: the contract enforces a floor
(`MIN_STAKE_UNITS`, one whole unit of the payment token) and the server enforces
the ladder. That is the one economic knob that can change without a redeploy.

---

## 6. Test coverage for this document

| Claim | Proof |
|---|---|
| 200 bps of a 2× stake, floor rounding, dust to the winner | `contracts/test/PulsarEscrow*.t.sol` (settlement suites) + `tests/unit/test_economics_doc.py` recomputes the table |
| The fee leaves at settlement, no fee pot | `PulsarEscrowMigration.t.sol::test_total_locked_follows_the_lifecycle` (`totalLocked == 0` after settle) |
| A refused treasury transfer does not block the winner | `PulsarEscrowPayouts.t.sol` (H17 suites) |
| Treasury rotation is timelocked and cancellable | `contracts/test/PulsarEscrowSecurity.t.sol` (M24 suites) |
| There is no fee setter | `tests/unit/test_economics_doc.py::test_the_contract_has_no_fee_setter` |
| The UI copy matches the contract | `tests/unit/test_economics_doc.py::test_every_locale_states_the_real_split` |
