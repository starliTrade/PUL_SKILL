# Security policy

PULSAR moves real money: a settlement signature authorises a payout from an
escrow contract, and the game server holds the key that mints it. Security
reports are treated as production incidents, not tickets.

## Reporting a vulnerability

**Do not open a public issue.** Email `security@<your-domain>` (replace before
launch) with:

- what you did, and what happened;
- the affected endpoint/contract and the environment (Amoy/mainnet, commit);
- whether money or a player's session could be affected;
- a proof of concept if you have one.

You will get an acknowledgement within **72 hours**. Please give us up to
**90 days** before public disclosure, or less if a fix ships sooner.

## Scope

In scope:

- `api/` — authentication (SIWE), session handling, the match engine's commit →
  reveal → submit protocol, the settlement signer, the economy ledger, rate
  limits, the admin surface;
- `contracts/PulsarEscrow.sol` — settlement verification, refunds, payouts;
- the client's wallet/signing flow (`src/lib/web3*`, `escrowFlow`), session
  storage and CSP-relevant rendering;
- data exposure: any way to read another player's profile, history or session.

Out of scope:

- denial of service by volume alone, unless it is cheap and asymmetric;
- issues that require a compromised device, a malicious wallet extension or
  physical access;
- testnet-only deployments losing test tokens;
- reports produced solely by an automated scanner.

## What we already know (do not spend your time)

The public audit `docs/audit/RUTHLESS-AUDIT-2026-10-22.md` lists the known
weaknesses, including the ones that are **accepted until launch**: the signer
authority is centralised (one key decides a winner; KMS removes it from the
process but not the authority), the anti-cheat is statistical detection rather
than proof of humanity, and the admin surface is a shared secret. See
`docs/audit/REMEDIATION-TODO-2026-10-22.md` for the tracked fixes.

## What we will never ask for

A seed phrase, a private key, or a signature you did not initiate. The game
server never needs a player's key: it verifies SIWE statements and reads the
chain. Anyone asking for a seed phrase in the name of PULSAR is attacking you.

## Safe harbour

We will not pursue legal action against researchers who follow this policy,
stay within the scope, avoid privacy violations and data destruction, and give
us reasonable time to fix an issue before disclosure.
