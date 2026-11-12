# PULSAR — Contract upgrade & migration path (audit M-11)

The escrow holds player money and **cannot be upgraded in place**. That is a
choice, not an oversight. This document records the decision, describes the one
procedure an operator is allowed to follow when the contract has to be replaced,
and states what the escrow can prove on chain while that happens.

Related: `docs/DEPLOYMENT.md` (§1 deploy, §6 readiness), `SECURITY.md`,
`docs/INCIDENT-RUNBOOK.md`.

---

## 0. TL;DR

| Question | Answer |
|---|---|
| Is the contract upgradeable? | **No.** `PulsarEscrow` is immutable, no proxy, no `delegatecall`. |
| How is a fix shipped? | Deploy a **new** escrow, `freeze()` the old one, drain it through normal settlement/refund/withdraw, point `ESCROW_ADDRESS` at the new one. |
| Can a freeze trap funds? | **No.** `freeze()` blocks `createDuel` and `joinDuel` only. `settleDuel`, `refundTimeoutMatch` and `withdraw` never read it. |
| How much does the escrow owe? | `totalLocked()` — open stakes + deferred payouts. Anything above it is `residualBalance()`. |
| Can the operator take player money? | **No.** The only transfer that is not a duel payout is `sweepResidual`, capped at `residualBalance()`, and only while `frozen`. |
| How does the server know which code it is calling? | `VERSION()` / `VERSION_CODE()` are read into `/api/health` and compared with `onchain.EXPECTED_ESCROW_VERSION`. |

---

## 1. Why not a proxy (the decision record)

A transparent/UUPS proxy was the alternative. It was rejected for this system:

1. **Blast radius.** With a proxy, whoever holds the upgrade key can replace the
   code that custodies every live stake in one transaction. The current admin
   surface (treasury, oracle) is already timelocked and cannot move player
   money; an upgrade key would be a strictly larger power than anything that
   exists today, held by a small team, on a contract that is weeks old.
2. **Invisible failure mode.** A storage-layout mistake in an upgrade does not
   revert — it silently reassigns fields. `DuelMatch` layout is decoded by
   `api/onchain._decode_match` and pinned by a parity test precisely because it
   is a cross-component contract; a proxy makes that layout permanent and makes
   every future change a potential silent corruption.
3. **Audit surface.** An immutable contract can be audited once and then trusted
   by hash. A proxy can only be audited "as deployed, until someone changes it",
   which is exactly the property a player cannot verify.
4. **Cost of the alternative is bounded.** A redeploy costs one deployment, a
   short freeze window, and a manual step for anybody holding a deferred credit.
   All of it is mechanical, and all of it is visible on chain.

What a proxy would genuinely have bought — a one-transaction fix with no
migration window — is not worth the above for an escrow of this size. If the
system grows to the point where a migration is impossible (millions in open
stakes, thousands of deferred credits), **revisit this decision before that
point**, not after: the correct moment to move to a proxy is while a migration
is still cheap.

---

## 2. What "versioned" means here

`PulsarEscrow` publishes two constants:

```solidity
string  public constant VERSION      = "2.0.0";
uint256 public constant VERSION_CODE = 2;
```

* Bump **both** on any deploy that changes behaviour, storage, or the ABI.
* `VERSION_CODE` is what the server compares against
  (`api/onchain.py: EXPECTED_ESCROW_VERSION`).
* `tests/unit/test_contract_version.py` fails if the contract and the server
  disagree, if the major of the string differs from the code, or if this
  document stops describing the mechanism.

The server reads both values and reports them in `/api/health`:

```json
"escrowVersion":        {"code": 2, "name": "2.0.0", "expected": 2, "compatible": true},
"escrowVersionProblem": null
```

A pre-2.0 escrow publishes nothing, so it reports `"compatible": false` with
`escrowVersionProblem` naming the mismatch. `scripts/rehearse_amoy_e2e.py` has
this as a **preflight check**, so a rehearsal cannot silently run against the
previous contract.

> The check is visible, not enforcing: a mismatch does not stop the server. That
> is deliberate. Blocking every settlement because a health read failed would
> hand an RPC blip the power to freeze payouts. The gate belongs in the
> rehearsal and in the operator's preflight, where a human is watching.

---

## 3. The migration window

Three on-chain pieces make a migration safe:

### 3.1 `freeze()` / `unfreeze()` — owner only, not timelocked

```
freeze()   -> frozen = true, frozenAt = now, emits EscrowFrozen(by, at)
unfreeze() -> frozen = false, frozenAt = 0, emits EscrowUnfrozen(by, at)
```

* **Freeze is instant on purpose.** It can only stop NEW money from entering.
  Timelocking it would mean watching an abandoned contract accept deposits for
  two more days.
* **Unfreeze is instant too.** It restores the pre-freeze, already-audited
  behaviour and cannot move a token.
* `frozen` is checked in exactly two places: `createDuel` and `joinDuel`.
  `tests/unit/test_contract_version.py::test_freeze_guards_the_two_deposit_paths_and_nothing_else`
  fails if anyone ever adds a third.

### 3.2 `totalLocked` — what the escrow owes

Incremented by the received amount on `createDuel` and `joinDuel`; decremented
only when a token transfer actually leaves the contract (`_pay` success and
`withdraw`). A **deferred** payout keeps the obligation: the money is still
there, it just moved from "open duel" to `pendingWithdrawals`.

Two invariants in `contracts/test/PulsarEscrowInvariants.t.sol` hold after any
random sequence of actions (6400 calls each):

* `totalLocked == stakes of open duels + Σ pendingWithdrawals`
* `residualBalance() == 0`

### 3.3 `residualBalance()` / `sweepResidual(to)`

`residualBalance() = balanceOf(escrow) − totalLocked`, i.e. tokens nobody is
owed. `sweepResidual` moves **exactly** that amount and only while `frozen`.

The freeze requirement is the honest trade: dust is recoverable only during a
migration. Any other time, a token arriving at the escrow is indistinguishable
from a late deposit, and "the operator recovered the surplus" is how a player's
stake disappears.

---

## 4. Procedure

> Do this with the **new** escrow deployed and verified first. The freeze window
> is the time between "old contract stops taking money" and "server points at
> the new one"; every minute of it is downtime for new duels.

### Step 1 — preflight

```bash
cd contracts && forge test                       # must be green before you touch anything
python3 ../scripts/rehearse_amoy_e2e.py          # includes the escrow-version check
```

Record, from the **old** escrow (`$OLD`):

```bash
cast call $OLD "VERSION()(string)"
cast call $OLD "totalLocked()(uint256)"
cast call $OLD "residualBalance()(uint256)"
```

### Step 2 — deploy the replacement

Follow `docs/DEPLOYMENT.md` §1. Keep the old address; you will need it in
step 6 and forever afterwards.

```bash
NEW=<address printed by the deploy script>
cast call $NEW "VERSION()(string)"        # must be the version this server expects
```

### Step 3 — freeze the old escrow

```bash
cast send $OLD "freeze()" --private-key $OWNER_KEY --rpc-url $RPC
cast call $OLD "frozen()(bool)"           # true
cast call $OLD "frozenAt()(uint256)"
```

New duels on the old contract now revert with `Escrow frozen`. **Settlements,
refunds and withdrawals keep working.** Players already in a duel finish it
normally.

### Step 4 — cut the server over

```bash
# game server
ESCROW_ADDRESS=$NEW            # + the matching ESCROW_RPC_URL / chain id
# web client
VITE_ESCROW_ADDRESS=$NEW
VITE_CHAIN_ID=...
```

Restart, then confirm the server agrees with the contract:

```bash
curl -s $SERVER/api/health | jq '.escrowVersion, .escrowVersionProblem'
# -> {"code": 2, "name": "2.0.0", "expected": 2, "compatible": true}
# -> null
```

### Step 5 — drain the old escrow

Nothing to do for duels that were already open: they settle or time out on
their own schedule (30 min + 10 min grace after activation). Watch it empty:

```bash
watch -n 60 'cast call $OLD "totalLocked()(uint256)"; cast call $OLD "residualBalance()(uint256)"'
```

`totalLocked == 0` and `residualBalance == 0` means the old contract owes
nobody. **Do not** sweep while `totalLocked > 0` — the function will refuse if
the balance is exactly what is owed, but the check you actually want is that
`totalLocked` is zero.

If somebody holds a deferred payout (token blacklist, contract that rejects
tokens), `totalLocked` stays above zero until the token lets them withdraw.
That is correct: the money is theirs, the old contract pays it whenever
`withdraw()` succeeds. Never "recover" it.

### Step 6 — record and keep

* Add the new address, its version, and the block of deployment to the release
  notes and to `docs/DEPLOYMENT.md`.
* **Keep the old contract reachable forever.** It has no admin exit that could
  be closed, no `selfdestruct`, and `withdraw()` is permissionless. Deleting it
  from documentation is how a deferred credit becomes unrecoverable.
* Sweep the residual, if any, *after* step 5:

  ```bash
  cast send $OLD "sweepResidual(address)" $TREASURY --private-key $OWNER_KEY --rpc-url $RPC
  ```

  `ResidualSwept(to, amount)` is emitted. This moves only what nobody was owed.

### Step 7 — unfreeze only if you abort

If the replacement turns out to be wrong (misconfigured token, wrong oracle,
failed rehearsal), point the server back at `$OLD` and:

```bash
cast send $OLD "unfreeze()" --private-key $OWNER_KEY --rpc-url $RPC
```

The old escrow is exactly where it was: nothing was migrated out, no player was
touched. This is the reason the freeze does not move funds.

---

## 5. What this does NOT solve

Be explicit about the limits, because they are what a future engineer will trip
over:

1. **Deferred credits are per-contract.** A player whose payout was deferred on
   the old escrow must call `withdraw()` on the OLD address. The UI must not
   hide that (see the ledger/withdraw flow and `docs/INCIDENT-RUNBOOK.md`).
2. **Settlement proofs are bound to `address(this)`.** A proof signed for the
   old escrow is invalid on the new one — the digest includes the escrow
   address. Any duel left Active on the old contract must be settled there or
   refunded; it cannot be migrated.
3. **The server's expectation is one number.** Running one server against two
   escrows is not supported; `/api/health` reports one `escrowVersion` because
   there is one `ESCROW_ADDRESS`.
4. **Strategy/parameter changes are still a redeploy.** `PLATFORM_FEE_BPS` and
   `MATCH_TIMEOUT` are constants (audit M-12 accepts this deliberately for the
   fee; see `docs/ECONOMICS.md`).
5. **No automatic drain.** Nothing here writes to the old contract for the
   operator. Draining is normal player/keeper traffic plus time.

---

## 6. Test coverage for this document

| Claim | Executable proof |
|---|---|
| Freeze blocks deposits | `contracts/test/PulsarEscrowMigration.t.sol::test_freeze_blocks_create/_join` |
| Freeze never blocks exits | `…::test_freeze_does_not_block_settlement_of_an_active_duel`, `…refund_of_an_abandoned_duel`, `…a_deferred_withdrawal` |
| Freeze/unfreeze are owner-only and reversible | `…::test_freeze_and_unfreeze_are_owner_only`, `…test_unfreeze_reopens_deposits_and_emits_both_events` |
| The ledger matches the obligations | `contracts/test/PulsarEscrowInvariants.t.sol::invariant_total_locked_equals_obligations` |
| The surplus is zero in normal operation | `…::invariant_residual_is_zero_without_stray_transfers` |
| Sweep cannot touch player money | `…Migration::test_sweep_moves_only_the_surplus_and_leaves_player_money` |
| A fee-on-transfer token cannot inflate the ledger | `…Migration::test_ledger_uses_received_amount_for_fee_on_transfer_tokens` |
| The server reads and reports the version | `tests/unit/test_contract_version.py` |
| The rehearsal refuses an unversioned escrow | `scripts/rehearse_amoy_e2e.py` preflight |
