// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {
    NoReturnUSDT,
    FalseReturnUSDT,
    FeeOnTransferUSDT,
    ReentrantUSDT
} from "./TokenVariants.sol";

/**
 * CT1 / CT2 — the token variants the escrow must survive.
 *
 * The contract inlines a SafeERC20-equivalent *because* real USDT does not
 * return a bool from `transfer`. That branch had never been exercised: MockUSDT
 * is an OpenZeppelin ERC20 that always returns true, so the code that exists
 * because of USDT was the one path with no coverage at all.
 */
contract PulsarEscrowTokensTest is Test {
    address internal treasury = address(0x7EA5);
    address internal oracle = address(0x0AC1E);
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    function setUp() public {
        oracle = vm.addr(oracleKey);
    }

    function _status(PulsarEscrow e, bytes32 id) internal view returns (PulsarEscrow.MatchStatus) {
        (, , , , , , PulsarEscrow.MatchStatus status, , , ) = e.matches(id);
        return status;
    }

    function _settle(PulsarEscrow e, bytes32 id, address winner) internal {
        uint256 deadline = block.timestamp + 600;
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        id, winner, uint256(220), uint256(310), uint256(1), deadline, block.chainid, address(e)
                    )
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oracleKey, digest);
        e.settleDuel(
            PulsarEscrow.SettlementProof({
                matchId: id,
                winner: winner,
                winnerTimeMs: 220,
                loserTimeMs: 310,
                nonce: 1,
                deadline: deadline,
                signature: abi.encodePacked(r, s, v)
            })
        );
    }

    // --- CT1a: the token that returns nothing (real USDT) ---------------------
    function test_no_return_token_full_lifecycle() public {
        NoReturnUSDT token = new NoReturnUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);

        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);
        vm.prank(bob);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("no-return");
        vm.prank(alice);
        e.createDuel(id, 5e6);
        vm.prank(bob);
        e.joinDuel(id);

        assertEq(token.balanceOf(address(e)), 10e6, "the escrow must hold both stakes");

        _settle(e, id, alice);

        assertEq(uint8(_status(e, id)), uint8(PulsarEscrow.MatchStatus.Settled));
        assertEq(token.balanceOf(alice), 100e6 - 5e6 + 9.8e6);
        assertEq(token.balanceOf(treasury), 0.2e6);
    }

    function test_no_return_token_refund_works() public {
        NoReturnUSDT token = new NoReturnUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("no-return-refund");
        vm.prank(alice);
        e.createDuel(id, 5e6);

        vm.warp(block.timestamp + e.MATCH_TIMEOUT() + e.REFUND_GRACE() + 1);
        e.refundTimeoutMatch(id);
        assertEq(token.balanceOf(alice), 100e6);
    }

    // --- CT1b: a token that returns false without reverting -------------------
    function test_false_returning_token_is_rejected_on_deposit() public {
        FalseReturnUSDT token = new FalseReturnUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);

        // The token silently refuses to move funds. Accepting that would create
        // a duel with no stake behind it.
        vm.prank(alice);
        vm.expectRevert("SafeTransfer: transferFrom failed");
        e.createDuel(keccak256("false-return"), 5e6);
    }

    function test_false_returning_token_is_rejected_on_payout() public {
        FalseReturnUSDT token = new FalseReturnUSDT();
        token.setFailTransfers(false); // deposits work normally...
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);
        vm.prank(bob);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("false-return-payout");
        vm.prank(alice);
        e.createDuel(id, 5e6);
        vm.prank(bob);
        e.joinDuel(id);

        // Now the token starts refusing payouts. The settlement must NOT report
        // success — it must credit the winner instead (audit H17).
        token.setFailTransfers(true);
        _settle(e, id, alice);

        assertEq(uint8(_status(e, id)), uint8(PulsarEscrow.MatchStatus.Settled));
        assertEq(e.pendingWithdrawals(alice), 9.8e6, "an undeliverable payout must be credited");
        assertEq(e.pendingWithdrawals(treasury), 0.2e6);
    }

    // --- CT1c: fee-on-transfer ------------------------------------------------
    function test_fee_on_transfer_deposit_is_rejected_at_join() public {
        FeeOnTransferUSDT token = new FeeOnTransferUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);
        vm.prank(bob);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("fee-on-transfer");
        vm.prank(alice);
        e.createDuel(id, 5e6);

        // The creator's stake landed short, so the stored stake is the RECEIVED
        // amount (F-19). The joiner's deposit must match it exactly — a
        // fee-on-transfer token cannot silently produce an unbalanced pool.
        (, , , uint256 stakeAmount, , , , , , ) = e.matches(id);
        assertLt(stakeAmount, 5e6, "the pool must reflect what actually arrived");

        vm.prank(bob);
        vm.expectRevert("Fee-on-transfer deposit rejected");
        e.joinDuel(id);
    }

    // --- CT2: reentrancy ------------------------------------------------------
    function test_reentrancy_through_the_token_is_blocked() public {
        ReentrantUSDT token = new ReentrantUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);
        vm.prank(bob);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("reentrancy");
        vm.prank(alice);
        e.createDuel(id, 5e6);
        vm.prank(bob);
        e.joinDuel(id);

        // Arm the token to call back into the escrow while it is paying out.
        token.arm(address(e), abi.encodeWithSelector(PulsarEscrow.withdraw.selector));
        _settle(e, id, alice);

        assertFalse(
            token.reentrySucceeded(),
            "the re-entrant call succeeded - the nonReentrant guard is not holding (audit CT2)"
        );
        // And the settlement itself is unaffected.
        assertEq(uint8(_status(e, id)), uint8(PulsarEscrow.MatchStatus.Settled));
        assertEq(token.balanceOf(alice), 100e6 - 5e6 + 9.8e6);
    }

    function test_reentrancy_cannot_drain_a_deferred_credit() public {
        ReentrantUSDT token = new ReentrantUSDT();
        PulsarEscrow e = new PulsarEscrow(address(token), treasury, oracle);
        token.faucet(alice, 100e6);
        token.faucet(bob, 100e6);
        vm.prank(alice);
        token.approve(address(e), type(uint256).max);
        vm.prank(bob);
        token.approve(address(e), type(uint256).max);

        bytes32 id = keccak256("reentrancy-credit");
        vm.prank(alice);
        e.createDuel(id, 5e6);
        vm.prank(bob);
        e.joinDuel(id);

        // Credit the winner first (a blocked payout), then let the token try to
        // pull that credit during a later transfer.
        token.arm(address(e), abi.encodeWithSelector(PulsarEscrow.withdraw.selector));
        _settle(e, id, alice);

        assertFalse(token.reentrySucceeded(), "the credit was drained by a re-entrant withdraw");
    }
}
