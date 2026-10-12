// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/**
 * H18 + H20 regression — the contract must enforce its own settlement window.
 *
 * H18: `settleDuel` accepted any `proof.deadline` the oracle signed. The
 * property "the signature expires before the permissionless refund opens" was
 * enforced ONLY off-chain, by the server's clamp. A single over-long deadline
 * (a bug, a key swap, clock skew, or a server `created_at` earlier than the
 * on-chain `createdAt`) let a settlement land after refunds were live, and the
 * two paths raced.
 *
 * H20: `joinDuel` had no cutoff and recorded no activation time, so the only
 * clock the contract had was `createdAt` (the deposit). A player could join at
 * T+29:59 and produce an Active duel that was refundable one second later, and
 * a duel activated late had its 30-minute refund clock started at deposit.
 */
contract PulsarEscrowLifecycleTest is Test {
    MockUSDT internal token;
    PulsarEscrow internal escrow;

    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    uint256 internal constant STAKE = 5e6;
    uint256 internal constant TIMEOUT = 30 minutes;

    function setUp() public {
        oracle = vm.addr(oracleKey);
        token = new MockUSDT();
        escrow = new PulsarEscrow(address(token), treasury, oracle);

        for (uint256 i = 0; i < 2; i++) {
            address who = i == 0 ? alice : bob;
            token.faucet(who, 100e6);
            vm.prank(who);
            token.approve(address(escrow), type(uint256).max);
        }
    }

    function _create(bytes32 id) internal {
        vm.prank(alice);
        escrow.createDuel(id, STAKE);
    }

    function _join(bytes32 id) internal {
        vm.prank(bob);
        escrow.joinDuel(id);
    }

    function _status(bytes32 id) internal view returns (PulsarEscrow.MatchStatus) {
        (, , , , , , PulsarEscrow.MatchStatus status, , , ) = escrow.matches(id);
        return status;
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

    function _settleWithDeadline(bytes32 id, address winner, uint256 deadline) internal {
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

    // --- H18 ------------------------------------------------------------------
    function test_deadline_beyond_the_refund_horizon_reverts() public {
        bytes32 id = keccak256("h18-long-deadline");
        _create(id);
        _join(id);

        // A perfectly valid oracle signature — but valid for far longer than the
        // contract's own refund horizon.
        uint256 overLong = block.timestamp + TIMEOUT + 1 hours;

        vm.expectRevert("deadline exceeds horizon");
        _settleWithDeadline(id, alice, overLong);
    }

    function test_deadline_inside_the_horizon_is_accepted() public {
        bytes32 id = keccak256("h18-ok-deadline");
        _create(id);
        _join(id);

        uint256 ok = block.timestamp + 10 minutes;
        _settleWithDeadline(id, alice, ok);

        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Settled));
    }

    function test_deadline_exactly_at_the_horizon_is_accepted() public {
        bytes32 id = keccak256("h18-boundary");
        _create(id);
        _join(id);

        uint256 boundary = block.timestamp + TIMEOUT;
        _settleWithDeadline(id, alice, boundary);

        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Settled));
    }

    // --- H20 ------------------------------------------------------------------
    function test_activation_is_recorded() public {
        bytes32 id = keccak256("h20-activated");
        _create(id);
        assertEq(escrow.activatedAt(id), 0, "an unpaired duel has no activation");

        uint256 joinedAt = block.timestamp;
        _join(id);
        assertEq(escrow.activatedAt(id), joinedAt);
    }
    function test_join_after_the_refund_horizon_reverts() public {
        bytes32 id = keccak256("h20-late-join");
        _create(id);

        vm.warp(block.timestamp + TIMEOUT + 1);

        vm.prank(bob);
        vm.expectRevert("Match expired");
        escrow.joinDuel(id);
    }


    function test_refund_window_starts_at_activation_not_deposit() public {
        bytes32 id = keccak256("h20-late-activation");
        _create(id);

        // The joiner pairs 20 minutes after the deposit — a slow queue.
        vm.warp(block.timestamp + 20 minutes);
        _join(id);

        // 11 minutes later the deposit is 31 minutes old, but the duel has only
        // been live for 11. Refunding now would rob the players of the play
        // window the design promises.
        vm.warp(block.timestamp + 11 minutes);
        vm.expectRevert("Match not timed out");
        escrow.refundTimeoutMatch(id);

        // Once the full window has passed from ACTIVATION, the refund opens.
        vm.warp(block.timestamp + TIMEOUT);
        escrow.refundTimeoutMatch(id);
        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Refunded));
    }

    function test_an_unpaired_duel_still_refunds_on_the_deposit_clock() public {
        // No activation ever happened, so `createdAt` remains the anchor.
        bytes32 id = keccak256("h20-unpaired");
        _create(id);

        vm.warp(block.timestamp + TIMEOUT + 1);
        escrow.refundTimeoutMatch(id);
        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Cancelled));
    }
}
