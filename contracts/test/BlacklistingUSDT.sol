// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "openzeppelin-contracts/contracts/token/ERC20/ERC20.sol";

/**
 * Test-only USDT variant that can block transfers TO specific addresses, like
 * the real Tether blacklist (and like any contract that reverts on receipt).
 *
 * Audit H17: `settleDuel` and `refundTimeoutMatch` performed both transfers in
 * one transaction, so a single failing recipient reverted the whole thing and
 * the OTHER party's funds were frozen indefinitely. This mock is what proves
 * that cannot happen.
 */
contract BlacklistingUSDT is ERC20 {
    mapping(address => bool) public blocked;

    constructor() ERC20("Blocked Tether USD", "bUSDT") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// Block (or unblock) transfers TO `who`, like Tether's blacklist.
    function setBlocked(address who, bool value) external {
        blocked[who] = value;
    }

    function faucet(address to, uint256 amount) external {
        _mint(to, amount);
    }

    // OZ v5 routes every transfer through _update.
    function _update(address from, address to, uint256 value) internal override {
        require(!blocked[to], "bUSDT: recipient blocked");
        super._update(from, to, value);
    }
}
