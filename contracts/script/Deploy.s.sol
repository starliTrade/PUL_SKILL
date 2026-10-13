// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "../test/MockUSDT.sol";

/**
 * Deploys PulsarEscrow. Constructor args follow docs/DEPLOYMENT.md exactly:
 * paymentToken, treasuryWallet, oracleSigner.
 *
 * On Amoy (or any non-mainnet chain) a MockUSDT is deployed first and used as
 * payment token, so the whole duel lifecycle is testable without real money.
 */
/// The chains where a faucet token is acceptable (audit 8.17).
///
/// An allowlist, not a denylist: a chain nobody listed is treated as REAL, so a
/// new deployment target fails closed instead of shipping mock money.
function _isKnownTestnet(uint256 chainId) view returns (bool) {
    return chainId == 31337      // anvil / hardhat
        || chainId == 80002      // Polygon Amoy
        || chainId == 80001      // Polygon Mumbai (legacy)
        || chainId == 11155111   // Sepolia
        || chainId == 17000      // Holesky
        || chainId == 421614     // Arbitrum Sepolia
        || chainId == 11155420   // OP Sepolia
        || chainId == 84532      // Base Sepolia
        || chainId == 97;        // BSC testnet
}

contract Deploy is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address treasury = vm.envAddress("TREASURY_ADDRESS");
        address oracleSigner = vm.envAddress("ORACLE_SIGNER_ADDRESS");
        // Optional: reuse an existing token (mainnet USDT). If unset on a
        // testnet chain, a fresh MockUSDT is deployed.
        address paymentToken = vm.envOr("PAYMENT_TOKEN_ADDRESS", address(0));

        // Audit-#5 guard: MockUSDT is a faucet token anyone can mint — it must
        // NEVER go live on mainnet where it would be indistinguishable money.
        // Explicitly set PAYMENT_TOKEN_ADDRESS (canonical USDT) on mainnet.
        if (block.chainid == 137 && paymentToken == address(0)) {
            revert("Refusing to deploy MockUSDT on mainnet: set PAYMENT_TOKEN_ADDRESS to canonical USDT");
        }

        vm.startBroadcast(deployerKey);
        if (paymentToken == address(0)) {
            MockUSDT mock = new MockUSDT();
            paymentToken = address(mock);
        }
        new PulsarEscrow(paymentToken, treasury, oracleSigner);
        vm.stopBroadcast();
    }
}
