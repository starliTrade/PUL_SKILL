// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "openzeppelin-contracts/contracts/token/ERC20/ERC20.sol";
import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/// An 18-decimal payment token, to prove the escrow does not assume 6.
contract Decimals18Token is ERC20 {
    constructor() ERC20("Wrapped Ether", "WETH") {}

    function decimals() public pure override returns (uint8) {
        return 18;
    }

    function faucet(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/**
 * M22 / M23 / M24 / M25 - contract hardening.
 *
 * M22: `MIN_STAKE_UNITS` hard-coded 1e6, i.e. "1 USDT at 6 decimals". Deployed
 *      against any other token the anti-spam floor silently becomes dust while
 *      the server reads the real `decimals()` - the two disagree about what
 *      "1 USDT" means.
 * M23: `MatchCreated` emitted `received * 2` while the stored `totalPool` stays
 *      0 until the joiner pays. Indexers reading the event show a 2x pool for a
 *      duel that holds one stake.
 * M24: `setTreasuryWallet` / `setOracleSigner` were one-step and un-timelocked.
 *      A typo'd treasury routes every future fee to an unrecoverable address,
 *      and an oracle rotation instantly invalidates every outstanding signed
 *      settlement.
 * M25: `usedSignatures` is unreachable (the status check reverts first), but
 *      the comment and the test claimed it was the replay defence.
 */
contract PulsarEscrowHardeningTest is Test {
    // Solidity 0.8.20 cannot `emit PulsarEscrow.MatchCreated(...)` (qualified
    // event access arrived in 0.8.21), so the event is re-declared here with an
    // identical signature — the topic0 is what `vm.expectEmit` matches on.
    event MatchCreated(
        bytes32 indexed matchId,
        address indexed player1,
        uint256 stakeAmount,
        uint256 totalPool
    );

    MockUSDT internal token;
    PulsarEscrow internal escrow;

    address internal treasury = address(0x7EA5);
    address internal oracle = address(0x0AC1E);
    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    function setUp() public {
        token = new MockUSDT();
        escrow = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(escrow), type(uint256).max);
        vm.prank(bob);
        token.approve(address(escrow), type(uint256).max);
    }

    // --- M22 ------------------------------------------------------------------
    function test_min_stake_follows_the_token_decimals() public {
        Decimals18Token weth = new Decimals18Token();
        PulsarEscrow e18 = new PulsarEscrow(address(weth), treasury, oracle);

        assertEq(
            e18.MIN_STAKE_UNITS(),
            1e18,
            "the minimum stake must be one whole token, whatever its decimals (audit M22)"
        );
    }

    function test_a_dust_stake_on_an_18_decimal_token_is_rejected() public {
        Decimals18Token weth = new Decimals18Token();
        PulsarEscrow e18 = new PulsarEscrow(address(weth), treasury, oracle);

        weth.faucet(alice, 100e18);
        vm.prank(alice);
        weth.approve(address(e18), type(uint256).max);

        // 1e6 base units is 1 USDT at 6 decimals - dust at 18.
        vm.prank(alice);
        vm.expectRevert("Stake below minimum");
        e18.createDuel(keccak256("dust"), 1e6);
    }

    function test_a_whole_token_stake_on_an_18_decimal_token_is_accepted() public {
        Decimals18Token weth = new Decimals18Token();
        PulsarEscrow e18 = new PulsarEscrow(address(weth), treasury, oracle);

        weth.faucet(alice, 100e18);
        vm.prank(alice);
        weth.approve(address(e18), type(uint256).max);

        vm.prank(alice);
        e18.createDuel(keccak256("whole"), 1e18);
    }

    // --- M23 ------------------------------------------------------------------
    function test_match_created_reports_the_pool_that_actually_exists() public {
        bytes32 id = keccak256("event");
        uint256 stake = 5e6;

        vm.expectEmit(true, true, false, true, address(escrow));
        emit MatchCreated(id, alice, stake, 0);

        vm.prank(alice);
        escrow.createDuel(id, stake);
    }

    // --- M24 ------------------------------------------------------------------
    function test_treasury_rotation_is_not_instant() public {
        address newTreasury = address(0x7EA6);

        vm.prank(address(this));
        escrow.setTreasuryWallet(newTreasury);

        assertEq(
            escrow.treasuryWallet(),
            treasury,
            "a one-step rotation is live immediately - a typo is unrecoverable (audit M24)"
        );
        // The pending slot is asserted in the fix commit, once the timelock
        // API exists.
    }




    // The timelock API (`ADMIN_TIMELOCK`, `pendingTreasuryWallet`,
    // `applyTreasuryWallet`, `applyOracleSigner`, `cancelPendingAdminChanges`)
    // is exercised by the tests added with the fix — a red baseline that does
    // not compile would take the whole contract suite down with it.

    function test_admin_rotation_is_owner_only() public {
        vm.prank(alice);
        vm.expectRevert("Ownable: caller is not owner");
        escrow.setTreasuryWallet(address(0x7EA6));

        vm.prank(alice);
        vm.expectRevert("Ownable: caller is not owner");
        escrow.setOracleSigner(address(0x0AC2E));
    }
}
