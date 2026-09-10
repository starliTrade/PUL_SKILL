// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "openzeppelin-contracts/token/ERC20/ERC20.sol";

/**
 * Test-only USDT-like token (6 decimals) for Amoy end-to-end rehearsals.
 * Anyone can mint to themselves from the faucet flow. Never deployed to mainnet.
 */
contract MockUSDT is ERC20 {
    uint8 private constant _DECIMALS = 6;

    constructor() ERC20("Mock Tether USD", "MockUSDT") {}

    function decimals() public view override returns (uint8) {
        return _DECIMALS;
    }

    /// Faucet: caller mints 10,000 MockUSDT to any address, capped to keep
    /// testnet economics sane.
    function faucet(address to, uint256 amount) external {
        require(amount <= 10_000e6, "faucet: max 10,000 per call");
        _mint(to, amount);
    }
}
