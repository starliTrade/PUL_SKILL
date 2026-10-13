// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/**
 * H19 regression — the winner's settlement window must be uncontested.
 *
 * `refundTimeoutMatch` is permissionless and opened at exactly the instant the
 * settlement proof expired. A losing player who stalls past the horizon can
 * therefore call it — or pay a bot to front-run the winner's `settleDuel` in
 * the same block — and recover their full stake. The symmetric refund makes
 * timing out a FREE OPTION for the party that is losing, and the winner's
 * signed proof becomes worthless.
 *
 * Decision (D2, option A): an exclusive settlement window. Settlement is the
 * only exit until MATCH_TIMEOUT, and the permissionless refund opens only after
 * an additional grace period. The winner gets a full, uncontested window; the
 * loser cannot deny them by stalling.
 */
contract PulsarEscrowRefundRaceTest is Test {
    MockUSDT internal token;
    PulsarEscrow internal escrow;

    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    uint256 internal constant STAKE = 5e6;
    uint256 internal constant TIMEOUT = 30 minutes;
    // The fix exposes this as `GRACE`; the red baseline uses a
    // local value so it still compiles (a red baseline that breaks compilation
    // would take the whole contract suite down with it).
    uint256 internal constant GRACE = 10 minutes;

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

    function _activeDuel(bytes32 id) internal {
        vm.prank(alice);
        escrow.createDuel(id, STAKE);
        vm.prank(bob);
        escrow.joinDuel(id);
    }

    function _status(bytes32 id) internal view returns (PulsarEscrow.MatchStatus) {
        (, , , , , , PulsarEscrow.MatchStatus status, , , ) = escrow.matches(id);
        return status;
    }

    function _settle(bytes32 id, address winner, uint256 deadline) internal {
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
        escrow.settleDuel(
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

    // --- the finding ---------------------------------------------------------
    function test_the_loser_cannot_refund_while_the_winner_can_still_settle() public {
        bytes32 id = keccak256("h19-race");
        _activeDuel(id);

        // One second past the settlement horizon. The winner's proof is now
        // expired, but the refund must NOT be open yet — otherwise the losing
        // player simply stalls and takes their stake back.
        vm.warp(block.timestamp + TIMEOUT + 1);

        vm.expectRevert("Match not timed out");
        escrow.refundTimeoutMatch(id);
    }

    function test_the_winner_can_settle_at_the_last_instant_of_the_window() public {
        bytes32 id = keccak256("h19-last-instant");
        _activeDuel(id);

        uint256 deadline = block.timestamp + TIMEOUT;
        vm.warp(deadline);

        _settle(id, alice, deadline);
        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Settled));
    }

    function test_the_grace_is_not_optional() public {
        // A zero grace would put the refund back in the same block as the
        // expiry, which is the race this fixes.
        assertGt(escrow.REFUND_GRACE(), 0, "the settlement grace must be non-zero");
    }

    function test_the_refund_opens_after_the_grace() public {
        bytes32 id = keccak256("h19-after-grace");
        _activeDuel(id);

        vm.warp(block.timestamp + TIMEOUT + GRACE + 1);
        escrow.refundTimeoutMatch(id);

        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Refunded));
    }


    function test_an_unpaired_duel_also_waits_for_the_grace() public {
        bytes32 id = keccak256("h19-unpaired");
        vm.prank(alice);
        escrow.createDuel(id, STAKE);

        vm.warp(block.timestamp + TIMEOUT + 1);
        vm.expectRevert("Match not timed out");
        escrow.refundTimeoutMatch(id);

        vm.warp(block.timestamp + GRACE + 1);
        escrow.refundTimeoutMatch(id);
        assertEq(uint8(_status(id)), uint8(PulsarEscrow.MatchStatus.Cancelled));
    }
}
