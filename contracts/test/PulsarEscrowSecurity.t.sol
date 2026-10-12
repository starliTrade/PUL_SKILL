// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/**
 * CT3, CT5-CT9, CT12 — the settlement-proof and state-machine gaps.
 *
 * These are not bug fixes: they are the cases the suite never exercised, which
 * is how a digest drift or a state-transition hole would reach production
 * unnoticed. Each one is a property the contract claims and nobody had checked.
 */
contract PulsarEscrowSecurityTest is Test {
    MockUSDT internal token;
    PulsarEscrow internal escrow;

    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    address internal alice = address(0xA11CE);
    address internal bob = address(0xB0B);

    uint256 internal constant STAKE = 5e6;

    // Solidity 0.8.20 cannot `emit PulsarEscrow.X(...)` (qualified event access
    // arrived in 0.8.21), so the events are re-declared with identical
    // signatures — topic0 is what `vm.expectEmit` matches on.
    event MatchCreated(bytes32 indexed matchId, address indexed player1, uint256 stakeAmount, uint256 totalPool);
    event MatchJoined(bytes32 indexed matchId, address indexed player2);
    event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizePaid, uint256 platformFee);
    event MatchCancelled(bytes32 indexed matchId, string reason);
    event MatchRefunded(bytes32 indexed matchId, uint256 refundPerPlayer);
    event TreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event OracleSignerUpdated(address indexed oldOracle, address indexed newOracle);
    event PayoutDeferred(address indexed to, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount);

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

    // --- helpers --------------------------------------------------------------
    function _digest(
        PulsarEscrow e,
        bytes32 id,
        address winner,
        uint256 winnerMs,
        uint256 loserMs,
        uint256 nonce,
        uint256 deadline
    ) internal view returns (bytes32) {
        return keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        id, winner, winnerMs, loserMs, nonce, deadline, block.chainid, address(e)
                    )
                )
            )
        );
    }

    function _proof(
        PulsarEscrow e,
        bytes32 id,
        address winner,
        uint256 deadline,
        bytes memory signature
    ) internal pure returns (PulsarEscrow.SettlementProof memory) {
        return PulsarEscrow.SettlementProof({
            matchId: id,
            winner: winner,
            winnerTimeMs: 220,
            loserTimeMs: 310,
            nonce: 1,
            deadline: deadline,
            signature: signature
        });
    }

    function _sign(PulsarEscrow e, bytes32 id, address winner, uint256 deadline) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oracleKey, _digest(e, id, winner, 220, 310, 1, deadline));
        return abi.encodePacked(r, s, v);
    }

    function _activeDuel(bytes32 id) internal {
        vm.prank(alice);
        escrow.createDuel(id, STAKE);
        vm.prank(bob);
        escrow.joinDuel(id);
    }

    function _status(PulsarEscrow e, bytes32 id) internal view returns (PulsarEscrow.MatchStatus) {
        (, , , , , , PulsarEscrow.MatchStatus status, , , ) = e.matches(id);
        return status;
    }

    function _settle(PulsarEscrow e, bytes32 id, address winner) internal {
        uint256 deadline = block.timestamp + 600;
        e.settleDuel(_proof(e, id, winner, deadline, _sign(e, id, winner, deadline)));
    }

    // --- CT3: what actually stops a replay ------------------------------------
    function test_replay_is_blocked_by_the_status_check_not_the_signature_map() public {
        bytes32 id = keccak256("ct3-replay");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        escrow.settleDuel(_proof(escrow, id, alice, deadline, sig));

        // Audit M25: the replay defence is the STATUS gate, not `usedSignatures`.
        // Asserting the actual reason is what makes this test meaningful — the
        // old one signed for a different match and called it a replay test.
        vm.expectRevert("Match is not active");
        escrow.settleDuel(_proof(escrow, id, alice, deadline, sig));
    }

    function test_the_signature_map_is_actually_populated() public {
        bytes32 id = keccak256("ct3-map");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;

        // `_digest` already applies the EIP-191 prefix — the contract's
        // `usedSignatures` key is exactly that value.
        bytes32 ethSigned = _digest(escrow, id, alice, 220, 310, 1, deadline);
        assertFalse(escrow.usedSignatures(ethSigned), "nothing should be marked before settlement");

        escrow.settleDuel(_proof(escrow, id, alice, deadline, _sign(escrow, id, alice, deadline)));

        assertTrue(escrow.usedSignatures(ethSigned), "the guard must record the signature it consumed");
    }

    // --- CT5: cross-contract and cross-chain ----------------------------------
    function test_a_proof_for_another_escrow_is_rejected() public {
        bytes32 id = keccak256("ct5-cross-contract");
        _activeDuel(id);

        PulsarEscrow other = new PulsarEscrow(address(token), treasury, oracle);
        vm.prank(alice);
        token.approve(address(other), type(uint256).max);
        vm.prank(bob);
        token.approve(address(other), type(uint256).max);
        vm.prank(alice);
        other.createDuel(id, STAKE);
        vm.prank(bob);
        other.joinDuel(id);

        uint256 deadline = block.timestamp + 600;
        bytes memory sigForEscrow = _sign(escrow, id, alice, deadline);

        // The same matchId, the same oracle, the same chain — but the digest
        // binds `address(this)`, so this must not be spendable elsewhere.
        vm.expectRevert("Invalid Oracle signature");
        other.settleDuel(_proof(other, id, alice, deadline, sigForEscrow));
    }

    function test_a_proof_for_another_chain_is_rejected() public {
        bytes32 id = keccak256("ct5-cross-chain");
        _activeDuel(id);

        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        vm.chainId(137); // the signature was minted for the current chain
        vm.expectRevert("Invalid Oracle signature");
        escrow.settleDuel(_proof(escrow, id, alice, deadline, sig));
    }

    // --- CT6: tampered proof --------------------------------------------------
    function test_tampering_with_the_winner_is_rejected() public {
        bytes32 id = keccak256("ct6-winner");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        vm.expectRevert("Invalid Oracle signature");
        escrow.settleDuel(_proof(escrow, id, bob, deadline, sig));
    }

    function test_tampering_with_the_times_is_rejected() public {
        bytes32 id = keccak256("ct6-times");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        PulsarEscrow.SettlementProof memory p = _proof(escrow, id, alice, deadline, sig);
        p.winnerTimeMs = 105; // a better time than the oracle signed for

        vm.expectRevert("Invalid Oracle signature");
        escrow.settleDuel(p);
    }

    function test_tampering_with_the_deadline_is_rejected() public {
        bytes32 id = keccak256("ct6-deadline");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        PulsarEscrow.SettlementProof memory p = _proof(escrow, id, alice, deadline, sig);
        p.deadline = deadline + 1; // extend the window

        vm.expectRevert("Invalid Oracle signature");
        escrow.settleDuel(p);
    }

    function test_tampering_with_the_nonce_is_rejected() public {
        bytes32 id = keccak256("ct6-nonce");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);

        PulsarEscrow.SettlementProof memory p = _proof(escrow, id, alice, deadline, sig);
        p.nonce = 2;

        vm.expectRevert("Invalid Oracle signature");
        escrow.settleDuel(p);
    }

    // --- CT7: boundaries ------------------------------------------------------
    function test_deadline_equal_to_now_is_accepted() public {
        bytes32 id = keccak256("ct7-boundary-now");
        _activeDuel(id);
        uint256 deadline = block.timestamp;
        escrow.settleDuel(_proof(escrow, id, alice, deadline, _sign(escrow, id, alice, deadline)));
        assertEq(uint8(_status(escrow, id)), uint8(PulsarEscrow.MatchStatus.Settled));
    }

    function test_a_short_signature_is_rejected() public {
        bytes32 id = keccak256("ct7-short-sig");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);
        bytes memory truncated = new bytes(64);
        for (uint256 i = 0; i < 64; i++) {
            truncated[i] = sig[i];
        }

        vm.expectRevert("Invalid signature length");
        escrow.settleDuel(_proof(escrow, id, alice, deadline, truncated));
    }

    function test_an_invalid_v_value_is_rejected() public {
        bytes32 id = keccak256("ct7-bad-v");
        _activeDuel(id);
        uint256 deadline = block.timestamp + 600;
        bytes memory sig = _sign(escrow, id, alice, deadline);
        sig[64] = bytes1(uint8(29)); // v must be 27 or 28

        vm.expectRevert("Invalid signature v value");
        escrow.settleDuel(_proof(escrow, id, alice, deadline, sig));
    }

    // --- CT8: admin guards ----------------------------------------------------
    function test_zero_address_admin_changes_are_rejected() public {
        vm.expectRevert("Zero address");
        escrow.setTreasuryWallet(address(0));

        vm.expectRevert("Zero address");
        escrow.setOracleSigner(address(0));
    }

    function test_applying_without_a_pending_change_is_rejected() public {
        vm.expectRevert("No pending treasury");
        escrow.applyTreasuryWallet();

        vm.expectRevert("No pending oracle");
        escrow.applyOracleSigner();
    }

    // --- CT9: events ----------------------------------------------------------
    function test_events_describe_what_actually_happened() public {
        bytes32 id = keccak256("ct9-events");

        vm.expectEmit(true, true, false, true, address(escrow));
        emit MatchCreated(id, alice, STAKE, 0);
        vm.prank(alice);
        escrow.createDuel(id, STAKE);

        vm.expectEmit(true, true, false, false, address(escrow));
        emit MatchJoined(id, bob);
        vm.prank(bob);
        escrow.joinDuel(id);

        uint256 fee = (STAKE * 2 * 200) / 10_000;
        vm.expectEmit(true, true, false, true, address(escrow));
        emit MatchSettled(id, alice, STAKE * 2 - fee, fee);
        _settle(escrow, id, alice);
    }

    function test_refund_events_describe_what_actually_happened() public {
        bytes32 id = keccak256("ct9-refund");
        _activeDuel(id);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MatchRefunded(id, STAKE);
        escrow.refundTimeoutMatch(id);
    }

    function test_cancel_event_describes_what_actually_happened() public {
        bytes32 id = keccak256("ct9-cancel");
        vm.prank(alice);
        escrow.createDuel(id, STAKE);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        vm.expectEmit(true, false, false, true, address(escrow));
        emit MatchCancelled(id, "Timeout cancelled");
        escrow.refundTimeoutMatch(id);
    }

    function test_admin_events_describe_what_actually_happened() public {
        address newTreasury = address(0x7EA6);
        escrow.setTreasuryWallet(newTreasury);
        vm.warp(block.timestamp + escrow.ADMIN_TIMELOCK() + 1);

        vm.expectEmit(true, true, false, false, address(escrow));
        emit TreasuryUpdated(treasury, newTreasury);
        escrow.applyTreasuryWallet();
    }

    // --- CT12: cross-state transitions ----------------------------------------
    function test_a_settled_duel_cannot_be_refunded() public {
        bytes32 id = keccak256("ct12-refund-after-settle");
        _activeDuel(id);
        _settle(escrow, id, alice);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        vm.expectRevert("Cannot refund");
        escrow.refundTimeoutMatch(id);
    }

    function test_a_refunded_duel_cannot_be_settled() public {
        bytes32 id = keccak256("ct12-settle-after-refund");
        _activeDuel(id);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        escrow.refundTimeoutMatch(id);

        uint256 deadline = block.timestamp + 600;
        vm.expectRevert("Match is not active");
        escrow.settleDuel(_proof(escrow, id, alice, deadline, _sign(escrow, id, alice, deadline)));
    }

    function test_an_active_duel_cannot_be_joined_again() public {
        bytes32 id = keccak256("ct12-join-twice");
        _activeDuel(id);

        address carol = address(0xCA201);
        token.faucet(carol, 100e6);
        vm.prank(carol);
        token.approve(address(escrow), type(uint256).max);
        vm.prank(carol);
        vm.expectRevert("Match not available");
        escrow.joinDuel(id);
    }

    function test_a_cancelled_match_id_cannot_be_reused() public {
        bytes32 id = keccak256("ct12-reuse-id");
        vm.prank(alice);
        escrow.createDuel(id, STAKE);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        escrow.refundTimeoutMatch(id);

        vm.prank(alice);
        vm.expectRevert("Match already exists");
        escrow.createDuel(id, STAKE);
    }

    function test_a_refunded_duel_cannot_be_refunded_twice() public {
        bytes32 id = keccak256("ct12-double-refund");
        _activeDuel(id);

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        escrow.refundTimeoutMatch(id);

        vm.expectRevert("Cannot refund");
        escrow.refundTimeoutMatch(id);
    }
}
