// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/**
 * Full lifecycle tests for PulsarEscrow — mirrors scripts/test_game_server.py
 * (the oracle signature digests are produced with eth-account, exactly as the
 * production oracle does, so contract and oracle stay provably in lockstep).
 */
contract PulsarEscrowTest is Test {
    PulsarEscrow internal escrow;
    MockUSDT internal usdt;

    uint256 internal constant ORACLE_KEY = 0xA11CE;
    uint256 internal constant DEPLOYER_KEY = 0xB0B;
    address internal deployer = vm.addr(DEPLOYER_KEY);
    address internal oracle = vm.addr(ORACLE_KEY);
    address internal treasury = makeAddr("treasury");
    address internal p1 = makeAddr("player1");
    address internal p2 = makeAddr("player2");

    uint256 internal constant STAKE = 1_000e6; // 1,000 USDT

    function setUp() public {
        vm.startPrank(deployer);
        usdt = new MockUSDT();
        escrow = new PulsarEscrow(address(usdt), treasury, oracle);
        vm.stopPrank();

        usdt.faucet(p1, STAKE);
        usdt.faucet(p2, STAKE);
        vm.prank(p1);
        usdt.approve(address(escrow), type(uint256).max);
        vm.prank(p2);
        usdt.approve(address(escrow), type(uint256).max);
    }

    // ---------- helpers ----------

    function _createAndJoin(bytes32 matchId) internal {
        vm.prank(p1);
        escrow.createDuel(matchId, STAKE);
        vm.prank(p2);
        escrow.joinDuel(matchId);
    }

    function _sign(
        bytes32 matchId,
        address winner,
        uint256 winnerTimeMs,
        uint256 loserTimeMs,
        uint256 nonce,
        uint256 deadline
    ) internal view returns (bytes memory sig, bytes32 digest) {
        bytes32 preimage = keccak256(
            abi.encodePacked(
                matchId, winner, winnerTimeMs, loserTimeMs, nonce, deadline, block.chainid, address(escrow)
            )
        );
        digest = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", preimage));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ORACLE_KEY, digest);
        sig = abi.encodePacked(r, s, v);
    }

    function _defaultProofParams()
        internal
        view
        returns (bytes32 matchId, uint256 winnerTimeMs, uint256 loserTimeMs, uint256 nonce, uint256 deadline)
    {
        matchId = keccak256("test-match");
        winnerTimeMs = 180;
        loserTimeMs = 240;
        nonce = 1;
        deadline = block.timestamp + 10 minutes;
    }

    function _settle(
        bytes32 matchId,
        address winner,
        uint256 winnerTimeMs,
        uint256 loserTimeMs,
        uint256 nonce,
        uint256 deadline,
        bytes memory sig
    ) internal {
        PulsarEscrow.SettlementProof memory proof = PulsarEscrow.SettlementProof({
            matchId: matchId,
            winner: winner,
            winnerTimeMs: winnerTimeMs,
            loserTimeMs: loserTimeMs,
            nonce: nonce,
            deadline: deadline,
            signature: sig
        });
        escrow.settleDuel(proof);
    }

    // ---------- tests ----------

    function test_ConstructorRejectsZeroAddresses() public {
        vm.startPrank(deployer);
        vm.expectRevert("Invalid payment token");
        new PulsarEscrow(address(0), treasury, oracle);
        vm.expectRevert("Invalid treasury wallet");
        new PulsarEscrow(address(usdt), address(0), oracle);
        vm.expectRevert("Invalid oracle signer");
        new PulsarEscrow(address(usdt), treasury, address(0));
        vm.stopPrank();
    }

    function test_FullLifecycle_CreateJoinSettle() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce, uint256 deadline) = _defaultProofParams();
        _createAndJoin(matchId);

        assertEq(uint8(escrow.matches(matchId).status), uint8(PulsarEscrow.MatchStatus.Active));
        assertEq(escrow.matches(matchId).totalPool, STAKE * 2);

        (bytes memory sig,) = _sign(matchId, p1, wMs, lMs, nonce, deadline);
        _settle(matchId, p1, wMs, lMs, nonce, deadline, sig);

        PulsarEscrow.DuelMatch memory m = escrow.matches(matchId);
        assertEq(uint8(m.status), uint8(PulsarEscrow.MatchStatus.Settled));
        assertEq(m.winner, p1);

        // 2% rake to treasury, 98% to winner
        uint256 fee = (STAKE * 2 * 200) / 10_000; // 40
        assertEq(usdt.balanceOf(treasury), fee);
        assertEq(usdt.balanceOf(p1), STAKE - fee + STAKE); // returned stake + prize minus fee
        assertEq(usdt.balanceOf(address(escrow)), 0);
        assertEq(escrow.totalFeesCollected(), fee);
    }

    function test_RevertWhen_ReplaySameSettlement() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce, uint256 deadline) = _defaultProofParams();
        _createAndJoin(matchId);
        (bytes memory sig,) = _sign(matchId, p1, wMs, lMs, nonce, deadline);
        _settle(matchId, p1, wMs, lMs, nonce, deadline, sig);

        // Fresh active match, same signed payload → digest is in usedSignatures
        bytes32 matchId2 = keccak256("test-match-2");
        usdt.faucet(p1, STAKE);
        vm.prank(p1);
        escrow.createDuel(matchId2, STAKE);
        vm.prank(p2);
        escrow.joinDuel(matchId2);

        vm.expectRevert("Signature already used");
        _settle(matchId2, p1, wMs, lMs, nonce, deadline, sig);
    }

    function test_RevertWhen_ForgedSignature() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce, uint256 deadline) = _defaultProofParams();
        _createAndJoin(matchId);

        // Attacker signs with their own key — recovers to attacker, not oracle
        bytes32 preimage = keccak256(
            abi.encodePacked(matchId, p1, wMs, lMs, nonce, deadline, block.chainid, address(escrow))
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", preimage));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xDEAD, digest);
        bytes memory forged = abi.encodePacked(r, s, v);

        vm.expectRevert("Invalid Oracle signature");
        _settle(matchId, p1, wMs, lMs, nonce, deadline, forged);
    }

    function test_RevertWhen_HighS_Malleability() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce, uint256 deadline) = _defaultProofParams();
        _createAndJoin(matchId);

        (bytes memory sig, bytes32 digest) = _sign(matchId, p1, wMs, lMs, nonce, deadline);
        // Craft the high-s twin: s' = n - s, v' = 1 - v. Recovers to the same
        // address but MUST be rejected by the low-s check.
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        bytes32 n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
        bytes32 sHigh = bytes32(uint256(n) - uint256(s));
        uint8 vHigh = v == 27 ? 28 : 27;
        bytes memory twin = abi.encodePacked(r, sHigh, vHigh);

        // Sanity: twin would recover the same signer
        assertEq(ecrecover(digest, vHigh, r, sHigh), oracle, "twin should recover same address");

        vm.expectRevert("Signature s-value too high");
        _settle(matchId, p1, wMs, lMs, nonce, deadline, twin);
    }

    function test_RevertWhen_ExpiredDeadline() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce) = _defaultProofParams();
        uint256 deadline = block.timestamp - 1;
        _createAndJoin(matchId);
        (bytes memory sig,) = _sign(matchId, p1, wMs, lMs, nonce, deadline);

        vm.expectRevert("Settlement proof expired");
        _settle(matchId, p1, wMs, lMs, nonce, deadline, sig);
    }

    function test_RevertWhen_WinnerNotParticipant() public {
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce, uint256 deadline) = _defaultProofParams();
        _createAndJoin(matchId);
        address outsider = makeAddr("outsider");
        (bytes memory sig,) = _sign(matchId, outsider, wMs, lMs, nonce, deadline);

        vm.expectRevert("Winner not participant");
        _settle(matchId, outsider, wMs, lMs, nonce, deadline, sig);
    }

    function test_RefundTimeout_CancelledForCreatedDuel() public {
        bytes32 matchId = keccak256("timeout-created");
        vm.prank(p1);
        escrow.createDuel(matchId, STAKE);

        vm.warp(block.timestamp + 10 minutes + 1);
        escrow.refundTimeoutMatch(matchId);

        assertEq(uint8(escrow.matches(matchId).status), uint8(PulsarEscrow.MatchStatus.Cancelled));
        assertEq(usdt.balanceOf(p1), STAKE);
        assertEq(usdt.balanceOf(address(escrow)), 0);
    }

    function test_RefundTimeout_RefundedForActiveDuel() public {
        bytes32 matchId = keccak256("timeout-active");
        _createAndJoin(matchId);

        vm.warp(block.timestamp + 10 minutes + 1);
        escrow.refundTimeoutMatch(matchId);

        assertEq(uint8(escrow.matches(matchId).status), uint8(PulsarEscrow.MatchStatus.Refunded));
        assertEq(usdt.balanceOf(p1), STAKE);
        assertEq(usdt.balanceOf(p2), STAKE);
        assertEq(usdt.balanceOf(address(escrow)), 0);
    }

    function test_RevertWhen_RefundBeforeTimeout() public {
        bytes32 matchId = keccak256("early-refund");
        _createAndJoin(matchId);
        vm.expectRevert("Match not timed out");
        escrow.refundTimeoutMatch(matchId);
    }

    function test_OnlyOwnerCanRotateSigners() public {
        vm.expectRevert(); // Ownable: caller is not owner
        escrow.setOracleSigner(makeAddr("evil"));

        vm.prank(deployer);
        escrow.setOracleSigner(makeAddr("newOracle"));
        assertEq(escrow.oracleSigner(), makeAddr("newOracle"));
    }
}
