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

        // Audit #7 anti-regression: fund the test contract so it can pay the
        // 2% settlement fee (kept in sync with the contract constant below).
        usdt.faucet(address(this), STAKE);
    }

    // ---------- cross-module convention pins (the class of bug that audit #6
    // C1 / audit #7's meta-review found: two modules drifting apart while each
    // side's own tests still passed) ----------

    uint256 constant EXPECTED_FEE_BPS = 200; // must equal PulsarEscrow.PLATFORM_FEE_BPS

    function test_Pin_ContractFeeMatchesEconomyConstant() public pure {
        assertEq(
            escrow.PLATFORM_FEE_BPS(),
            EXPECTED_FEE_BPS,
            "contract fee drifted from the platform economy constant"
        );
    }

    function test_Pin_DuelMatchStructLayoutMatchesServerDecoder() public view {
        // api/onchain.py decodes matches(bytes32) as 10 static words with
        // `status` at word index 6 (matchId, player1, player2, stakeAmount,
        // totalPool, createdAt, status, winner, winnerReactionMs,
        // loserReactionMs). createDuel+joinDuel must produce exactly that
        // layout, or the server's deposit gate reads the wrong field.
        bytes32 mid = keccak256("struct-layout-pin");
        _createAndJoin(mid);
        (
            bytes32 matchId_,
            address player1_,
            address player2_,
            ,
            ,
            ,
            PulsarEscrow.MatchStatus status_,
            ,
            ,

        ) = escrow.matches(mid);
        assertEq(uint256(matchId_), uint256(mid), "word 0 must be matchId");
        assertEq(player1_, p1, "word 1 must be player1 (creator)");
        assertEq(player2_, p2, "word 2 must be player2 (joiner)");
        assertEq(uint8(status_), 2, "word 6 must be status (Active=2 after both stakes)");
    }

    function test_Pin_RefundHorizonIs30Minutes() public pure {
        assertEq(escrow.MATCH_TIMEOUT(), 30 minutes, "server copy promises a 30-min refund horizon");
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

        // External struct getters return an unnamed 10-tuple — destructure
        // with exact types (no named member access, no struct assignment).
        (,,,,uint256 poolBefore,, PulsarEscrow.MatchStatus stBefore,,,) = escrow.matches(matchId);
        assertEq(uint8(stBefore), uint8(PulsarEscrow.MatchStatus.Active));
        assertEq(poolBefore, STAKE * 2);

        (bytes memory sig,) = _sign(matchId, p1, wMs, lMs, nonce, deadline);
        _settle(matchId, p1, wMs, lMs, nonce, deadline, sig);

        (,,,,,, PulsarEscrow.MatchStatus stSettled, address winner_,,) = escrow.matches(matchId);
        assertEq(uint8(stSettled), uint8(PulsarEscrow.MatchStatus.Settled));
        assertEq(winner_, p1);

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
        (bytes32 matchId, uint256 wMs, uint256 lMs, uint256 nonce,) = _defaultProofParams();
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

        // MATCH_TIMEOUT is 30 minutes (raised from 10 in P1.16) — the refund
        // horizon must be warped past its CURRENT value, not a stale constant.
        vm.warp(block.timestamp + 30 minutes + 1);
        escrow.refundTimeoutMatch(matchId);

        (,,,,,, PulsarEscrow.MatchStatus stCancelled,,,) = escrow.matches(matchId);
        assertEq(uint8(stCancelled), uint8(PulsarEscrow.MatchStatus.Cancelled));
        assertEq(usdt.balanceOf(p1), STAKE);
        assertEq(usdt.balanceOf(address(escrow)), 0);
    }

    function test_RefundTimeout_RefundedForActiveDuel() public {
        bytes32 matchId = keccak256("timeout-active");
        _createAndJoin(matchId);

        // MATCH_TIMEOUT is 30 minutes (raised from 10 in P1.16) — the refund
        // horizon must be warped past its CURRENT value, not a stale constant.
        vm.warp(block.timestamp + 30 minutes + 1);
        escrow.refundTimeoutMatch(matchId);

        (,,,,,, PulsarEscrow.MatchStatus stRefunded,,,) = escrow.matches(matchId);
        assertEq(uint8(stRefunded), uint8(PulsarEscrow.MatchStatus.Refunded));
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

    function test_OwnershipHandoverRequiresAccept() public {
        address next = makeAddr("nextOwner");
        vm.prank(deployer);
        escrow.transferOwnership(next);
        // Not transferred yet — fat-finger safe.
        assertEq(escrow.owner(), deployer);
        assertEq(escrow.pendingOwner(), next);
        vm.prank(next);
        escrow.acceptOwnership();
        assertEq(escrow.owner(), next);
        assertEq(escrow.pendingOwner(), address(0));
    }

    function test_RevertWhen_DustStakeBelowMinimum() public {
        vm.prank(p1);
        vm.expectRevert("Stake below minimum");
        escrow.createDuel(keccak256("dust"), 1);
    }

    // ---------- fuzz / property tests (audit #5, item 6) ----------

    /// The fee split is EXACT for every pool: fee + prize == pool, escrow ends
    /// empty, and no wei... no unit of token is ever created or lost.
    function testFuzz_FeeMathIsExact(uint256 stake) public {
        stake = bound(stake, 1_000_000, 1_000e6);
        usdt.faucet(p1, stake);
        usdt.faucet(p2, stake);
        vm.prank(p1);
        usdt.approve(address(escrow), stake);
        vm.prank(p2);
        usdt.approve(address(escrow), stake);

        bytes32 matchId = keccak256(abi.encodePacked("fuzz-exact", stake));
        vm.prank(p1);
        escrow.createDuel(matchId, stake);
        vm.prank(p2);
        escrow.joinDuel(matchId);

        (bytes memory sig,) = _sign(matchId, p1, 200, 300, 1, block.timestamp + 10 minutes);
        _settle(matchId, p1, 200, 300, 1, block.timestamp + 10 minutes, sig);

        uint256 pool = stake * 2;
        uint256 fee = (pool * 200) / 10_000;
        assertEq(usdt.balanceOf(treasury), fee, "fee");
        assertEq(usdt.balanceOf(p1), pool - fee, "prize");
        assertEq(usdt.balanceOf(address(escrow)), 0, "escrow must be empty");
        assertEq(usdt.balanceOf(p2), 0, "loser paid everything");
    }

    /// A settled duel can NEVER be settled, joined, or re-created.
    function testFuzz_SettledIsTerminal(uint8 action, uint256 stake) public {
        stake = bound(stake, 1_000_000, 1_000e6);
        usdt.faucet(p1, stake);
        usdt.faucet(p2, stake);
        vm.prank(p1);
        usdt.approve(address(escrow), stake);
        vm.prank(p2);
        usdt.approve(address(escrow), stake);

        bytes32 matchId = keccak256(abi.encodePacked("fuzz-terminal", stake));
        vm.prank(p1);
        escrow.createDuel(matchId, stake);
        vm.prank(p2);
        escrow.joinDuel(matchId);
        (bytes memory sig,) = _sign(matchId, p2, 150, 400, 1, block.timestamp + 10 minutes);
        _settle(matchId, p2, 150, 400, 1, block.timestamp + 10 minutes, sig);

        action = uint8(bound(action, 0, 2));
        if (action == 0) {
            vm.prank(p1);
            vm.expectRevert("Match already exists");
            escrow.createDuel(matchId, stake);
        } else if (action == 1) {
            vm.prank(p1);
            vm.expectRevert("Match not available");
            escrow.joinDuel(matchId);
        } else {
            vm.expectRevert("Match is not active");
            _settle(matchId, p1, 100, 500, 2, block.timestamp + 10 minutes, sig);
        }
    }

    /// joinDuel only ever transitions Created → Active; player1 can never join
    /// their own duel for any stake.
    function testFuzz_SelfJoinAndGhostJoinRevert(uint256 stake, uint8 state) public {
        stake = bound(stake, 1_000_000, 1_000e6);
        usdt.faucet(p1, stake);
        vm.prank(p1);
        usdt.approve(address(escrow), stake);
        bytes32 matchId = keccak256(abi.encodePacked("fuzz-join", stake));

        state = uint8(bound(state, 0, 2));
        if (state == 0) {
            // Ghost join: never created.
            vm.prank(p1);
            vm.expectRevert("Match not available");
            escrow.joinDuel(matchId);
        } else if (state == 1) {
            vm.prank(p1);
            escrow.createDuel(matchId, stake);
            vm.prank(p1);
            vm.expectRevert("Cannot play against self");
            escrow.joinDuel(matchId);
        } else {
            // Cancelled (timeout refund) duel cannot be joined.
            vm.prank(p1);
            escrow.createDuel(matchId, stake);
            // MATCH_TIMEOUT is 30 minutes — warp past the CURRENT constant.
            vm.warp(block.timestamp + 30 minutes + 1);
            escrow.refundTimeoutMatch(matchId);
            vm.prank(p1);
            vm.expectRevert("Match not available");
            escrow.joinDuel(matchId);
        }
    }

    /// Zero/negative-equivalent stakes are impossible; every accepted stake
    /// locks exactly 2×stake in the escrow pool.
    function testFuzz_StakeGateAndPoolAccounting(uint96 stake) public {
        if (stake < 1_000_000) {
            vm.prank(p1);
            vm.expectRevert("Stake below minimum");
            escrow.createDuel(keccak256("zero"), stake);
            return;
        }
        vm.assume(stake <= 1_000e6);
        usdt.faucet(p1, stake);
        usdt.faucet(p2, stake);
        vm.prank(p1);
        usdt.approve(address(escrow), stake);
        vm.prank(p2);
        usdt.approve(address(escrow), stake);

        bytes32 matchId = keccak256(abi.encodePacked("fuzz-pool", stake));
        vm.prank(p1);
        escrow.createDuel(matchId, stake);
        // F-19: totalPool is finalized on JOIN (balance-delta accounting),
        // not at create time — the pool is only real once both stakes landed.
        (,,,,uint256 poolCreated,,,,,) = escrow.matches(matchId);
        assertEq(poolCreated, 0, "pool set on join");
        assertEq(usdt.balanceOf(address(escrow)), stake);
        vm.prank(p2);
        escrow.joinDuel(matchId);
        (,,,,uint256 poolJoined,,,,,) = escrow.matches(matchId);
        assertEq(poolJoined, stake * 2, "pool after join");
        assertEq(usdt.balanceOf(address(escrow)), stake * 2, "both stakes locked");
    }

    /// A non-participant can never be declared winner, for any signature.
    function testFuzz_OutsiderWinnerImpossible(uint256 stake) public {
        stake = bound(stake, 1_000_000, 1_000e6);
        usdt.faucet(p1, stake);
        usdt.faucet(p2, stake);
        vm.prank(p1);
        usdt.approve(address(escrow), stake);
        vm.prank(p2);
        usdt.approve(address(escrow), stake);
        bytes32 matchId = keccak256(abi.encodePacked("fuzz-outsider", stake));
        vm.prank(p1);
        escrow.createDuel(matchId, stake);
        vm.prank(p2);
        escrow.joinDuel(matchId);

        address outsider = makeAddr("fuzz-outsider");
        (bytes memory sig,) = _sign(matchId, outsider, 100, 600, 1, block.timestamp + 10 minutes);
        vm.expectRevert("Winner not participant");
        _settle(matchId, outsider, 100, 600, 1, block.timestamp + 10 minutes, sig);
    }
}
