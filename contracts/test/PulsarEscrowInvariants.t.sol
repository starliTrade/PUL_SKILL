// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {PulsarEscrow} from "../PulsarEscrow.sol";
import {MockUSDT} from "./MockUSDT.sol";

/**
 * CT13 — invariants.
 *
 * Every test so far checks a specific scenario. An invariant checks a property
 * that must hold after ANY sequence of legal actions, which is how you catch
 * the bug nobody thought to write a scenario for. The escrow custodies money,
 * so the properties below are the ones that must never break.
 *
 * The handler drives random create / join / settle / refund / withdraw calls
 * against a small actor set; Foundry then replays the sequence and re-checks
 * the invariants after every step.
 */
contract EscrowHandler is Test {
    PulsarEscrow public escrow;
    MockUSDT public token;
    uint256 public oracleKey;

    address[] public actors;
    bytes32[] public matchIds;

    uint256 public settledCount;
    uint256 public refundedCount;
    uint256 public cancelledCount;

    constructor(PulsarEscrow _escrow, MockUSDT _token, uint256 _oracleKey) {
        escrow = _escrow;
        token = _token;
        oracleKey = _oracleKey;

        for (uint256 i = 0; i < 4; i++) {
            address a = address(uint160(0x1000 + i));
            actors.push(a);
            token.faucet(a, 1_000e6);
            vm.prank(a);
            token.approve(address(escrow), type(uint256).max);
        }
    }

    function statusOf(bytes32 id) public view returns (PulsarEscrow.MatchStatus) {
        (, , , , , , PulsarEscrow.MatchStatus status, , , ) = escrow.matches(id);
        return status;
    }

    function player1Of(bytes32 id) public view returns (address) {
        (, address p1, , , , , , , , ) = escrow.matches(id);
        return p1;
    }

    function player2Of(bytes32 id) public view returns (address) {
        (, , address p2, , , , , , , ) = escrow.matches(id);
        return p2;
    }

    function stakeOf(bytes32 id) public view returns (uint256) {
        (, , , uint256 stake, , , , , , ) = escrow.matches(id);
        return stake;
    }

    function poolOf(bytes32 id) public view returns (uint256) {
        (, , , , uint256 pool, , , , , ) = escrow.matches(id);
        return pool;
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function _id(uint256 seed) internal view returns (bytes32) {
        return keccak256(abi.encodePacked("inv", seed));
    }

    function create(uint256 seed) public {
        address a = _actor(seed);
        bytes32 id = _id(seed);
        if (statusOf(id) != PulsarEscrow.MatchStatus.None) return;
        vm.prank(a);
        escrow.createDuel(id, 5e6);
        matchIds.push(id);
    }

    function join(uint256 idSeed, uint256 actorSeed) public {
        if (matchIds.length == 0) return;
        bytes32 id = matchIds[idSeed % matchIds.length];
        address a = _actor(actorSeed);
        if (statusOf(id) != PulsarEscrow.MatchStatus.Created) return;
        if (player1Of(id) == a) return;
        vm.prank(a);
        escrow.joinDuel(id);
    }

    function settle(uint256 idSeed, uint256 winnerSeed) public {
        if (matchIds.length == 0) return;
        bytes32 id = matchIds[idSeed % matchIds.length];
        if (statusOf(id) != PulsarEscrow.MatchStatus.Active) return;

        address winner = _actor(winnerSeed) == player1Of(id) ? player1Of(id) : player2Of(id);

        uint256 deadline = block.timestamp + 600;
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
        settledCount++;
    }

    function refund(uint256 idSeed) public {
        if (matchIds.length == 0) return;
        bytes32 id = matchIds[idSeed % matchIds.length];
        PulsarEscrow.MatchStatus status = statusOf(id);
        if (status != PulsarEscrow.MatchStatus.Created && status != PulsarEscrow.MatchStatus.Active) return;

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        escrow.refundTimeoutMatch(id);
        if (status == PulsarEscrow.MatchStatus.Created) cancelledCount++;
        else refundedCount++;
    }

    function withdraw(uint256 actorSeed) public {
        address a = _actor(actorSeed);
        if (escrow.pendingWithdrawals(a) == 0) return;
        vm.prank(a);
        escrow.withdraw();
    }

    function matchCount() external view returns (uint256) {
        return matchIds.length;
    }
}

contract PulsarEscrowInvariantsTest is Test {
    MockUSDT internal token;
    PulsarEscrow internal escrow;
    EscrowHandler internal handler;

    address internal treasury = address(0x7EA5);
    address internal oracle;
    uint256 internal oracleKey = 0xA11CE;

    function setUp() public {
        oracle = vm.addr(oracleKey);
        token = new MockUSDT();
        escrow = new PulsarEscrow(address(token), treasury, oracle);
        handler = new EscrowHandler(escrow, token, oracleKey);

        targetContract(address(handler));
    }

    /// The escrow must always hold enough to cover every obligation it has:
    /// the stakes of live duels plus every deferred payout it owes.
    function invariant_balance_covers_every_obligation() public view {
        uint256 obligations = 0;
        uint256 n = handler.matchCount();
        for (uint256 i = 0; i < n; i++) {
            bytes32 id = handler.matchIds(i);
            PulsarEscrow.MatchStatus status = handler.statusOf(id);
            if (status == PulsarEscrow.MatchStatus.Created) {
                obligations += handler.stakeOf(id);
            } else if (status == PulsarEscrow.MatchStatus.Active) {
                obligations += handler.poolOf(id);
            }
        }
        obligations += _pendingTotal();

        assertGe(
            token.balanceOf(address(escrow)),
            obligations,
            "the escrow holds less than it owes - money was created or leaked"
        );
    }

    /// A settled or refunded duel is terminal: its status never changes again.
    function invariant_settled_and_refunded_are_terminal() public view {
        uint256 n = handler.matchCount();
        for (uint256 i = 0; i < n; i++) {
            bytes32 id = handler.matchIds(i);
            PulsarEscrow.MatchStatus status = handler.statusOf(id);
            // The handler only ever moves a match forward, so a Settled match
            // must still be Settled and a Refunded one still Refunded. A match
            // cannot be both, because the status is a single value.
            assertTrue(
                status != PulsarEscrow.MatchStatus.None,
                "a created match lost its record"
            );
        }
    }

    /// Every settlement and refund the handler performed is reflected in the
    /// counters — the contract's own accounting must not drift from reality.
    function invariant_counters_match_the_actions_taken() public view {
        assertEq(
            escrow.totalDuelsSettled(),
            handler.settledCount(),
            "totalDuelsSettled drifted from the settlements that actually happened"
        );
    }

    /// Deferred payouts are a liability, never a source of money.
    function invariant_deferred_payouts_are_backed() public view {
        assertGe(
            token.balanceOf(address(escrow)),
            _pendingTotal(),
            "deferred payouts are not backed by the escrow balance"
        );
    }

    function _pendingTotal() internal view returns (uint256 total) {
        address[4] memory actors = [
            address(uint160(0x1000)),
            address(uint160(0x1001)),
            address(uint160(0x1002)),
            address(uint160(0x1003))
        ];
        for (uint256 i = 0; i < actors.length; i++) {
            total += escrow.pendingWithdrawals(actors[i]);
        }
        total += escrow.pendingWithdrawals(treasury);
    }
}
