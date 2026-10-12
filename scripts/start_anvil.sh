#!/usr/bin/env bash
# PULSAR — local EVM chain with the escrow deployed (plan item 0.8).
#
# Why: phase 3 changes the contract, and phase 11 needs a rehearsal. Neither can
# be verified by unit tests alone — the settlement digest, the EIP-191 preimage
# and the struct layout are a THREE-way contract between api/oracle.py,
# api/onchain.py and PulsarEscrow.sol. Only a real EVM proves they still agree.
#
# Usage:
#   scripts/start_anvil.sh          # foreground (Ctrl-C to stop)
#   scripts/start_anvil.sh --bg     # background + deploy, writes the manifest
#   scripts/start_anvil.sh --stop   # stop a background instance
#
# Writes contracts/deployments/local.json:
#   {rpcUrl, chainId, token, escrow, treasury, oracle, deployer, players[]}
#
# The accounts are anvil's well-known deterministic set — never real keys.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PULSAR_ANVIL_PORT:-8545}"
RPC="http://127.0.0.1:${PORT}"
CHAIN_ID="${PULSAR_ANVIL_CHAIN_ID:-31337}"
MANIFEST="$ROOT/contracts/deployments/local.json"
PIDFILE="/tmp/pulsar-anvil.pid"
LOGFILE="/tmp/pulsar-anvil.log"

# anvil's default mnemonic: "test test test test test test test test test test test junk"
DEPLOYER_KEY="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
DEPLOYER_ADDR="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PLAYER1_KEY="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
PLAYER1_ADDR="0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
PLAYER2_KEY="0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
PLAYER2_ADDR="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
ORACLE_KEY="0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
ORACLE_ADDR="0x90F79bf6EB2c4f870365E785982E1f101E93b906"
TREASURY_ADDR="$DEPLOYER_ADDR"

for candidate in "$HOME/.foundry/bin" /root/workspace/.foundry/bin; do
  [[ -x "$candidate/forge" ]] && export PATH="$candidate:$PATH"
done
command -v anvil >/dev/null || { echo "ERROR: anvil not found (install Foundry)" >&2; exit 1; }
command -v forge >/dev/null || { echo "ERROR: forge not found (install Foundry)" >&2; exit 1; }

case "${1:-}" in
  --stop)
    if [[ -f "$PIDFILE" ]]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "stopped"
    else
      echo "no background anvil recorded"
    fi
    exit 0
    ;;
esac

deploy() {
  cd "$ROOT/contracts"
  # Solidity deps are gitignored; the CI workflow installs them the same way.
  if [[ ! -f lib/forge-std/src/Test.sol || ! -f lib/openzeppelin-contracts/contracts/token/ERC20/ERC20.sol ]]; then
    echo "ERROR: contract deps missing. Run:" >&2
    echo "  cd contracts && forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts --no-commit" >&2
    exit 1
  fi

  local token escrow
  token="$(forge create test/MockUSDT.sol:MockUSDT \
      --rpc-url "$RPC" --private-key "$DEPLOYER_KEY" --broadcast 2>/dev/null \
      | awk '/Deployed to:/ {print $3}')"
  [[ -n "$token" ]] || { echo "ERROR: MockUSDT deploy failed" >&2; exit 1; }

  escrow="$(forge create PulsarEscrow.sol:PulsarEscrow \
      --rpc-url "$RPC" --private-key "$DEPLOYER_KEY" --broadcast \
      --constructor-args "$token" "$TREASURY_ADDR" "$ORACLE_ADDR" 2>/dev/null \
      | awk '/Deployed to:/ {print $3}')"
  [[ -n "$escrow" ]] || { echo "ERROR: PulsarEscrow deploy failed" >&2; exit 1; }

  mkdir -p "$(dirname "$MANIFEST")"
  cat >"$MANIFEST" <<JSON
{
  "rpcUrl": "$RPC",
  "chainId": $CHAIN_ID,
  "token": "$token",
  "escrow": "$escrow",
  "treasury": "$TREASURY_ADDR",
  "oracle": "$ORACLE_ADDR",
  "deployer": {"address": "$DEPLOYER_ADDR", "privateKey": "$DEPLOYER_KEY"},
  "players": [
    {"address": "$PLAYER1_ADDR", "privateKey": "$PLAYER1_KEY"},
    {"address": "$PLAYER2_ADDR", "privateKey": "$PLAYER2_KEY"}
  ],
  "oracleKey": "$ORACLE_KEY"
}
JSON
  echo "token=$token"
  echo "escrow=$escrow"
  echo "manifest=$MANIFEST"
}

if curl -sf -o /dev/null -X POST -H 'Content-Type: application/json' \
     --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' "$RPC" 2>/dev/null; then
  echo "anvil already running on $RPC"
  deploy
  exit 0
fi

if [[ "${1:-}" == "--bg" ]]; then
  nohup anvil --port "$PORT" --chain-id "$CHAIN_ID" --silent >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 1 30); do
    curl -sf -o /dev/null -X POST -H 'Content-Type: application/json' \
      --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' "$RPC" && break
    sleep 1
  done
  echo "anvil up on $RPC (pid $(cat "$PIDFILE"))"
  deploy
  exit 0
fi

echo "starting anvil on $RPC (Ctrl-C to stop)…"
anvil --port "$PORT" --chain-id "$CHAIN_ID"
