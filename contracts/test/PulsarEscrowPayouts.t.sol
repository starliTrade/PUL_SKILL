// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {BlacklistingUSDT} from "./BlacklistingUSDT.sol";

/**
 * H17 regression — one failing recipient must never block the other party.
 *
 * `settleDuel` and `refundTimeoutMatch` performed both transfers in one
 * transaction. Real USDT can pause and blacklist addresses, and a participant
 * can be a contract that reverts on receipt, so a single failing transfer
 * reverted the whole call and froze the counterparty's funds indefinitely —
 * with no partial payout, no pull path and no admin sweep.
 *
 * The invariant pinned here: a payout that cannot be delivered is CREDITED to
 * the beneficiary for a later pull, and the other party is paid in the same
 * transaction.
 */
contract PulsarEscrowPayoutsTest is Test {
    BlacklistingUSDT internal token;
    PulsarEscrow internal escrow;

    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    uint256 internal constant STAKE = 5e6; // 5 USDT at 6 decimals
    uint256 internal constant FEE_BPS = 200;
    uint256 internal constant DENOM = 10_000;

    function setUp() public {
        oracle = vm.addr(oracleKey);
        token = new BlacklistingUSDT();
        escrow = new PulsarEscrow(address(token), treasury, oracle);

        for (uint256 i = 0; i < 2; i++) {
            address who = i == 0 ? alice : bob;
            token.faucet(who, 100e6);
            vm.prank(who);
            token.approve(address(escrow), type(uint256).max);
        }
    }

    function _duel(bytes32 id) internal returns (uint256 pool) {
        vm.prank(alice);
        escrow.createDuel(id, STAKE);
        vm.prank(bob);
        escrow.joinDuel(id);
        pool = STAKE * 2;
    }

    function _settle(bytes32 id, address winner) internal {
        uint256 deadline = block.timestamp + 600;
        uint256 nonce = 1;
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        id, winner, uint256(220), uint256(310), nonce, deadline, block.chainid, address(escrow)
                    )
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oracleKey, digest);
        escrow.settleDuel(
            PulsarEscrow.SettlementProof({
                matchId: id,
                winner: winner,
                winnerTimeMs: 220,
                loserTimeMs: 310,
                nonce: nonce,
                deadline: deadline,
                signature: abi.encodePacked(r, s, v)
            })
        );
    }

    // --- the finding ---------------------------------------------------------
    function test_blocked_winner_does_not_block_the_treasury() public {
        bytes32 id = keccak256("blocked-winner");
        uint256 pool = _duel(id);

        token.setBlocked(alice, true); // the winner cannot receive
        uint256 treasuryBefore = token.balanceOf(treasury);

        _settle(id, alice);

        uint256 fee = (pool * FEE_BPS) / DENOM;
        assertEq(
            token.balanceOf(treasury) - treasuryBefore,
            fee,
            "the treasury fee must be paid even when the winner cannot receive (audit H17)"
        );
    }


    function test_blocked_treasury_does_not_block_the_winner() public {
        bytes32 id = keccak256("blocked-treasury");
        uint256 pool = _duel(id);

        token.setBlocked(treasury, true);
        uint256 aliceBefore = token.balanceOf(alice);

        _settle(id, alice);

        uint256 prize = pool - (pool * FEE_BPS) / DENOM;
        assertEq(
            token.balanceOf(alice) - aliceBefore,
            prize,
            "the winner must be paid even when the treasury cannot receive (audit H17)"
        );
        assertEq(
            escrow.pendingWithdrawals(treasury),
            (pool * FEE_BPS) / DENOM,
            "the undeliverable fee must be credited, not lost (audit H17)"
        );
    }

    // --- the pull path -------------------------------------------------------
    function test_blocked_winner_can_withdraw_later() public {
        bytes32 id = keccak256("blocked-winner-withdraw");
        uint256 pool = _duel(id);

        token.setBlocked(alice, true);
        _settle(id, alice);

        uint256 prize = pool - (pool * FEE_BPS) / DENOM;
        assertEq(escrow.pendingWithdrawals(alice), prize);

        // The block is lifted (Tether un-blacklists) and the winner pulls.
        token.setBlocked(alice, false);
        uint256 before = token.balanceOf(alice);
        vm.prank(alice);
        escrow.withdraw();
        assertEq(token.balanceOf(alice) - before, prize);
        assertEq(escrow.pendingWithdrawals(alice), 0);
    }

    function test_withdraw_requires_a_credit() public {
        vm.prank(alice);
        vm.expectRevert("Nothing to withdraw");
        escrow.withdraw();
    }

    function test_withdraw_cannot_be_replayed() public {
        bytes32 id = keccak256("withdraw-replay");
        uint256 pool = _duel(id);
        token.setBlocked(alice, true);
        _settle(id, alice);
        token.setBlocked(alice, false);

        vm.prank(alice);
        escrow.withdraw();

        vm.prank(alice);
        vm.expectRevert("Nothing to withdraw");
        escrow.withdraw();

        uint256 prize = pool - (pool * FEE_BPS) / DENOM;
        assertEq(token.balanceOf(alice), 100e6 - STAKE + prize);
    }

    function test_an_unblocked_recipient_is_paid_directly_with_no_credit() public {
        // The normal path must not leave anything pending — `withdraw()` is a
        // recovery path, not the default one.
        bytes32 id = keccak256("normal-path");
        uint256 pool = _duel(id);
        _settle(id, alice);

        assertEq(escrow.pendingWithdrawals(alice), 0);
        assertEq(escrow.pendingWithdrawals(treasury), 0);
        assertEq(token.balanceOf(alice), 100e6 - STAKE + pool - (pool * FEE_BPS) / DENOM);
    }

    // --- the refund path has the same shape ----------------------------------
    function test_refund_survives_one_blocked_player() public {
        bytes32 id = keccak256("blocked-refund");
        _duel(id);

        token.setBlocked(bob, true);
        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);

        uint256 aliceBefore = token.balanceOf(alice);
        escrow.refundTimeoutMatch(id);

        assertEq(
            token.balanceOf(alice) - aliceBefore,
            STAKE,
            "player1's refund must not be blocked by player2's failed transfer (audit H17)"
        );
        assertEq(escrow.pendingWithdrawals(bob), STAKE);
    }


}
