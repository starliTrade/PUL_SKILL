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
contract Deploy is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address treasury = vm.envAddress("TREASURY_ADDRESS");
        address oracleSigner = vm.envAddress("ORACLE_SIGNER_ADDRESS");
        // Optional: reuse an existing token (mainnet USDT). If unset on a
        // testnet chain, a fresh MockUSDT is deployed.
        address paymentToken = vm.envOr("PAYMENT_TOKEN_ADDRESS", address(0));

        vm.startBroadcast(deployerKey);
        if (paymentToken == address(0)) {
            MockUSDT mock = new MockUSDT();
            paymentToken = address(mock);
        }
        new PulsarEscrow(paymentToken, treasury, oracleSigner);
        vm.stopBroadcast();
    }
}
