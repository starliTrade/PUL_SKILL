// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";
import {BlacklistingUSDT} from "./BlacklistingUSDT.sol";

/**
 * Audit M-11 — "the contract cannot be upgraded and has no migration path".
 *
 * The finding is real: `PulsarEscrow` is immutable and holds player money, so
 * every behavior fix means a new deployment while the old one may still owe
 * somebody. A proxy was considered and rejected (see the VERSION comment in
 * `PulsarEscrow.sol`): an upgrade key over live escrow is a bigger, permanent
 * risk than a redeploy.
 *
 * What is tested here is the migration procedure that replaces it, and the
 * three properties that make the procedure safe:
 *   1. a freeze stops NEW money but never stops an EXIT (settle / refund /
 *      withdraw keep working; the deferred-payout path included);
 *   2. the contract can prove what it owes (`totalLocked`) and therefore what
 *      it may safely give away (`residualBalance`), so the operator knows when
 *      the old escrow is empty;
 *   3. `sweepResidual` cannot reach player money — it moves the surplus only,
 *      and only while frozen.
 *
 * A migration that could strand one deferred payout would be worse than the
 * bug it fixes, which is why the freeze/exits cases below are the core of this
 * file.
 */
contract PulsarEscrowMigrationTest is Test {
    MockUSDT internal token;
    PulsarEscrow internal escrow;

    address internal owner = address(this);
    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    uint256 internal constant STAKE = 5e6;
    uint256 internal constant TIMEOUT = 30 minutes;
    uint256 internal constant GRACE = 10 minutes;

    function setUp() public {
        oracle = vm.addr(oracleKey);
        token = new MockUSDT();
        escrow = new PulsarEscrow(address(token), treasury, oracle);

        address[2] memory who = [alice, bob];
        for (uint256 i = 0; i < 2; i++) {
            token.faucet(who[i], 100e6);
            vm.prank(who[i]);
            token.approve(address(escrow), type(uint256).max);
        }
    }

    // --- helpers -----------------------------------------------------------

    function _create(bytes32 id) internal {
        vm.prank(alice);
        escrow.createDuel(id, STAKE);
    }

    function _join(bytes32 id) internal {
        vm.prank(bob);
        escrow.joinDuel(id);
    }

    function _sign(bytes32 id, address winner, uint256 deadline) internal view returns (bytes memory) {
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        id, winner, uint256(220), uint256(310), uint256(1), deadline, block.chainid, address(escrow)
                    )
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oracleKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _settle(bytes32 id, address winner, uint256 deadline) internal {
        escrow.settleDuel(
            PulsarEscrow.SettlementProof({
                matchId: id,
                winner: winner,
                winnerTimeMs: 220,
                loserTimeMs: 310,
                nonce: 1,
                deadline: deadline,
                signature: _sign(id, winner, deadline)
            })
        );
    }

    function _deadline(bytes32 id) internal view returns (uint256) {
        // The horizon is anchored on activation (H20) and capped at 30 minutes.
        return block.timestamp + 5 minutes + uint256(id) * 0;
    }

    function _balance() internal view returns (uint256) {
        return token.balanceOf(address(escrow));
    }

    // --- versioning --------------------------------------------------------

    function test_version_is_published_on_chain() public view {
        // The server reads these to refuse a stale escrow address; if they are
        // ever bumped silently, the parity test in tests/unit will fail.
        assertEq(escrow.VERSION(), "2.0.0");
        assertEq(escrow.VERSION_CODE(), 2);
    }

    function test_fresh_escrow_owes_nothing() public view {
        assertEq(escrow.totalLocked(), 0);
        assertEq(escrow.residualBalance(), 0);
        assertFalse(escrow.frozen());
        assertEq(escrow.frozenAt(), 0);
    }

    // --- freeze stops entries, never exits ---------------------------------

    function test_freeze_blocks_create() public {
        escrow.freeze();
        vm.prank(alice);
        vm.expectRevert("Escrow frozen");
        escrow.createDuel(bytes32(uint256(1)), STAKE);
    }

    function test_freeze_blocks_join() public {
        bytes32 id = bytes32(uint256(2));
        _create(id);
        escrow.freeze();
        vm.prank(bob);
        vm.expectRevert("Escrow frozen");
        escrow.joinDuel(id);
    }

    function test_freeze_does_not_block_settlement_of_an_active_duel() public {
        bytes32 id = bytes32(uint256(3));
        _create(id);
        _join(id);
        escrow.freeze();

        uint256 before = token.balanceOf(alice);
        // The settlement deadline is capped by the contract at activation +
        // MATCH_TIMEOUT; staying inside that window is what a live server does.
        _settle(id, alice, block.timestamp + 5 minutes);

        // 98% of a 10 USDT pool.
        assertEq(token.balanceOf(alice) - before, 9_800_000);
        assertEq(escrow.totalLocked(), 0);
    }

    function test_freeze_does_not_block_refund_of_an_abandoned_duel() public {
        bytes32 id = bytes32(uint256(4));
        _create(id);
        vm.warp(block.timestamp + TIMEOUT + GRACE + 1);
        escrow.freeze();

        uint256 before = token.balanceOf(alice);
        escrow.refundTimeoutMatch(id);
        assertEq(token.balanceOf(alice) - before, STAKE);
        assertEq(escrow.totalLocked(), 0);
    }

    function test_freeze_does_not_block_a_deferred_withdrawal() public {
        // The worst case for a freeze: a payout the token refused at
        // settlement, sitting in `pendingWithdrawals`. If a migration could
        // strand it, the freeze would be a theft primitive.
        BlacklistingUSDT blocked = new BlacklistingUSDT();
        PulsarEscrow esc = new PulsarEscrow(address(blocked), treasury, oracle);

        blocked.faucet(alice, 10e6);
        blocked.faucet(bob, 10e6);
        vm.prank(alice);
        blocked.approve(address(esc), type(uint256).max);
        vm.prank(bob);
        blocked.approve(address(esc), type(uint256).max);

        bytes32 id = bytes32(uint256(5));
        vm.prank(alice);
        esc.createDuel(id, STAKE);
        vm.prank(bob);
        esc.joinDuel(id);

        blocked.setBlocked(treasury, true); // the fee cannot be delivered
        esc.settleDuel(
            PulsarEscrow.SettlementProof({
                matchId: id,
                winner: bob,
                winnerTimeMs: 220,
                loserTimeMs: 310,
                nonce: 1,
                deadline: block.timestamp + 5 minutes,
                signature: _signFor(esc, id, bob, block.timestamp + 5 minutes)
            })
        );

        uint256 fee = (STAKE * 2 * 200) / 10000;
        assertEq(esc.pendingWithdrawals(treasury), fee, "fee deferred");
        assertEq(esc.totalLocked(), fee, "a deferred credit is still owed");

        esc.freeze();
        blocked.setBlocked(treasury, false);

        uint256 before = blocked.balanceOf(treasury);
        vm.prank(treasury);
        esc.withdraw();
        assertEq(blocked.balanceOf(treasury) - before, fee);
        assertEq(esc.totalLocked(), 0);
    }

    function test_freeze_and_unfreeze_are_owner_only() public {
        vm.prank(alice);
        vm.expectRevert();
        escrow.freeze();

        escrow.freeze();
        vm.prank(alice);
        vm.expectRevert();
        escrow.unfreeze();
    }

    function test_unfreeze_reopens_deposits_and_emits_both_events() public {
        bytes32 id = bytes32(uint256(6));

        vm.expectEmit(true, false, false, true, address(escrow));
        emit EscrowFrozen(owner, block.timestamp);
        escrow.freeze();
        assertTrue(escrow.frozen());
        assertEq(escrow.frozenAt(), block.timestamp);

        vm.warp(block.timestamp + 1 hours);
        vm.expectEmit(true, false, false, true, address(escrow));
        emit EscrowUnfrozen(owner, block.timestamp - 1 hours);
        escrow.unfreeze();
        assertFalse(escrow.frozen());
        assertEq(escrow.frozenAt(), 0);

        _create(id); // works again
        assertEq(escrow.totalLocked(), STAKE);
    }

    function test_freeze_twice_and_unfreeze_when_open_revert() public {
        vm.expectRevert("Not frozen");
        escrow.unfreeze();

        escrow.freeze();
        vm.expectRevert("Already frozen");
        escrow.freeze();
    }

    event EscrowFrozen(address indexed by, uint256 at);
    event EscrowUnfrozen(address indexed by, uint256 at);
    event ResidualSwept(address indexed to, uint256 amount);

    // --- locked-funds ledger ----------------------------------------------

    function test_total_locked_follows_the_lifecycle() public {
        bytes32 id = bytes32(uint256(7));

        _create(id);
        assertEq(escrow.totalLocked(), STAKE);
        assertEq(_balance(), STAKE);

        _join(id);
        assertEq(escrow.totalLocked(), STAKE * 2);
        assertEq(_balance(), STAKE * 2);

        _settle(id, bob, block.timestamp + 5 minutes);
        assertEq(escrow.totalLocked(), 0, "everything was paid out");
        assertEq(escrow.pendingWithdrawals(bob), 0);
        assertEq(escrow.residualBalance(), 0);
    }

    function test_total_locked_counts_deferred_payouts_until_withdrawn() public {
        BlacklistingUSDT blocked = new BlacklistingUSDT();
        PulsarEscrow esc = new PulsarEscrow(address(blocked), treasury, oracle);

        blocked.faucet(alice, 10e6);
        blocked.faucet(bob, 10e6);
        vm.prank(alice);
        blocked.approve(address(esc), type(uint256).max);
        vm.prank(bob);
        blocked.approve(address(esc), type(uint256).max);

        bytes32 id = bytes32(uint256(8));
        vm.prank(alice);
        esc.createDuel(id, STAKE);
        vm.prank(bob);
        esc.joinDuel(id);

        blocked.setBlocked(bob, true);
        esc.settleDuel(
            PulsarEscrow.SettlementProof({
                matchId: id,
                winner: bob,
                winnerTimeMs: 220,
                loserTimeMs: 310,
                nonce: 1,
                deadline: block.timestamp + 5 minutes,
                signature: _signFor(esc, id, bob, block.timestamp + 5 minutes)
            })
        );

        uint256 prize = STAKE * 2 - (STAKE * 2 * 200) / 10000;
        assertEq(esc.pendingWithdrawals(bob), prize);
        // The winner's prize is deferred, the fee left the contract: the ledger
        // must say exactly the prize is still owed, no more and no less.
        assertEq(esc.totalLocked(), prize);
        assertEq(blocked.balanceOf(address(esc)), prize);

        blocked.setBlocked(bob, false);
        vm.prank(bob);
        esc.withdraw();
        assertEq(esc.totalLocked(), 0);
        assertEq(blocked.balanceOf(address(esc)), 0);
    }

    // --- residual sweep ----------------------------------------------------

    function test_stray_transfer_is_residual_but_not_sweepable_unfrozen() public {
        token.faucet(address(escrow), 3e6); // somebody fat-fingers the escrow

        assertEq(escrow.residualBalance(), 3e6);
        assertEq(escrow.totalLocked(), 0);

        vm.expectRevert("Not frozen");
        escrow.sweepResidual(owner);
    }

    function test_sweep_moves_only_the_surplus_and_leaves_player_money() public {
        bytes32 id = bytes32(uint256(9));
        _create(id); // 5 USDT locked
        _join(id); // 10 USDT locked
        token.faucet(address(escrow), 3e6); // 13 on balance, 10 owed

        escrow.freeze();
        uint256 before = token.balanceOf(owner);
        escrow.sweepResidual(owner);

        assertEq(token.balanceOf(owner) - before, 3e6, "exactly the stray amount");
        assertEq(escrow.totalLocked(), 10e6);
        assertEq(_balance(), 10e6);

        // The duel still pays both sides in full after the sweep.
        uint256 winnerBefore = token.balanceOf(alice);
        _settle(id, alice, block.timestamp + 5 minutes);
        assertEq(token.balanceOf(alice) - winnerBefore, 9_800_000);
        assertEq(token.balanceOf(treasury), 200_000);
        assertEq(_balance(), 0);
    }

    function test_sweep_without_residual_reverts() public {
        escrow.freeze();
        vm.expectRevert("No residual");
        escrow.sweepResidual(owner);
    }

    function test_sweep_is_owner_only_and_rejects_the_zero_address() public {
        token.faucet(address(escrow), 1e6);
        escrow.freeze();

        vm.prank(alice);
        vm.expectRevert();
        escrow.sweepResidual(alice);

        vm.expectRevert("Zero address");
        escrow.sweepResidual(address(0));
    }

    function test_sweep_emits_the_amount() public {
        token.faucet(address(escrow), 2e6);
        escrow.freeze();

        vm.expectEmit(true, false, false, true, address(escrow));
        emit ResidualSwept(owner, 2e6);
        escrow.sweepResidual(owner);
    }

    /// A fee-on-transfer token is where a naive ledger says "10" while the
    /// escrow holds "9". Both deposit paths already read the balance delta;
    /// this pins the ledger to that same delta.
    function test_ledger_uses_received_amount_for_fee_on_transfer_tokens() public {
        FeeOnTransferUSDT fot = new FeeOnTransferUSDT();
        PulsarEscrow esc = new PulsarEscrow(address(fot), treasury, oracle);
        fot.faucet(alice, 10e6);
        vm.prank(alice);
        fot.approve(address(esc), type(uint256).max);

        vm.prank(alice);
        esc.createDuel(bytes32(uint256(10)), STAKE);

        // 1% burned by the token: the escrow must claim only what it received.
        assertEq(fot.balanceOf(address(esc)), STAKE - (STAKE / 100));
        assertEq(esc.totalLocked(), fot.balanceOf(address(esc)));
        assertEq(esc.residualBalance(), 0, "a fee-on-transfer deposit is not a surplus");
    }

    /// Independent oracle helper for the second escrow instance (its `address`
    /// is part of the digest, so the outer helper cannot be reused).
    function _signFor(PulsarEscrow esc, bytes32 id, address winner, uint256 deadline)
        internal
        view
        returns (bytes memory)
    {
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        id, winner, uint256(220), uint256(310), uint256(1), deadline, block.chainid, address(esc)
                    )
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oracleKey, digest);
        return abi.encodePacked(r, s, v);
    }
}

/// @dev 1% of every transfer is burned, so `received < sent`.
contract FeeOnTransferUSDT is MockUSDT {
    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 burn = value / 100;
            super._update(from, address(0), burn);
            super._update(from, to, value - burn);
            return;
        }
        super._update(from, to, value);
    }
}
