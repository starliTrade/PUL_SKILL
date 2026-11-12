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

    /// Why the campaign used to be weaker than its numbers (docs/CONTRACT-FUZZ-REPORT.md §4):
    /// `fail_on_revert = false` swallowed every revert, so 28% of `join` calls
    /// were spent on duels the contract correctly refused as expired and 2.3% of
    /// `settle` calls submitted a proof whose deadline was already past the
    /// horizon. Those calls cannot change state, and — the real problem — a NEW
    /// revert looked exactly like that background noise.
    ///
    /// Two changes fix it at the source:
    ///   * the handler now SKIPS what it can predict the contract will refuse
    ///     (an expired duel, a settlement window that has closed), so the budget
    ///     goes to reachable states;
    ///   * every call is wrapped in try/catch and any revert is RECORDED, and
    ///     `invariant_no_unexpected_reverts` asserts the record is empty.
    /// A revert is now a failing property, not a discarded call.
    uint256 public revertCount;
    bytes public firstRevert;
    string public firstRevertIn;

    uint256 public skippedExpiredJoins;
    uint256 public skippedPastHorizonSettles;

    /// Every invariant loops over the tracked matches, so the cost of ONE step is
    /// O(matches). Left unbounded that is O(n²) over a sequence: this handler let
    /// `matchIds` grow with every successful create, and the numbers measured on
    /// this machine were `ci` 96 s before the rewrite → 115 s after it, and a
    /// `nightly` run that used to take 21 minutes had not finished after 43.
    ///
    /// Capping is not a weakening. What the campaign hunts is a bad SEQUENCE
    /// (settle-then-refund, refund-then-settle, withdraw races) over live duels,
    /// not the existence of a thousand duels; a match in a terminal state stops
    /// being interesting. A 500-call sequence cannot meaningfully interleave more
    /// than a few dozen duels, so 64 is headroom rather than a limit the fuzzer
    /// feels — `skippedCreateAtCap` records how often it is hit.
    uint256 public constant MAX_TRACKED_MATCHES = 64;
    uint256 public skippedCreateAtCap;

    /// id -> the terminal status it first reached (0 = not terminal yet).
    /// Audit 2026-10-13: the "terminal" invariant used to assert only
    /// `status != None`, which is true for every match the handler ever touched
    /// — it could not fail, so it tested nothing. Recording the first terminal
    /// status is what makes "terminal" checkable.
    mapping(bytes32 => PulsarEscrow.MatchStatus) public terminalStatus;

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

    /// Remember the terminal status a match first reached, if it is terminal.
    function _recordTerminal(bytes32 id) internal {
        PulsarEscrow.MatchStatus status = statusOf(id);
        if (status == PulsarEscrow.MatchStatus.None) return;
        if (status == PulsarEscrow.MatchStatus.Created) return;
        if (status == PulsarEscrow.MatchStatus.Active) return;
        if (terminalStatus[id] == PulsarEscrow.MatchStatus.None) {
            terminalStatus[id] = status;
        }
    }

    function createdAtOf(bytes32 id) public view returns (uint256 createdAt) {
        (, , , , , createdAt, , , , ) = escrow.matches(id);
    }

    function clockOriginOf(bytes32 id) public view returns (uint256) {
        uint256 activated = escrow.activatedAt(id);
        uint256 created = createdAtOf(id);
        return activated > created ? activated : created;
    }

    function _recordRevert(string memory where, bytes memory reason) internal {
        revertCount++;
        if (firstRevert.length == 0) {
            firstRevert = reason;
            firstRevertIn = where;
        }
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
        if (matchIds.length >= MAX_TRACKED_MATCHES) {
            skippedCreateAtCap++;
            return;
        }
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
        // The contract's own rule (audit H20). Checking it here is not a weaker
        // test — it is the same rule, and it stops the fuzzer spending a third of
        // its budget on a call that cannot succeed. The contract still enforces
        // it; if this check ever disagrees with the contract, the try/catch below
        // records a revert and the invariant fails.
        if (block.timestamp >= createdAtOf(id) + escrow.MATCH_TIMEOUT()) {
            skippedExpiredJoins++;
            return;
        }
        vm.prank(a);
        try escrow.joinDuel(id) {
            // success: no bookkeeping needed, the invariants read the escrow
        } catch (bytes memory reason) {
            _recordRevert("join", reason);
        }
    }

    function settle(uint256 idSeed, uint256 winnerSeed) public {
        if (matchIds.length == 0) return;
        bytes32 id = matchIds[idSeed % matchIds.length];
        if (statusOf(id) != PulsarEscrow.MatchStatus.Active) return;
        _recordTerminal(id);

        address winner = _actor(winnerSeed) == player1Of(id) ? player1Of(id) : player2Of(id);

        // Mirror api/oracle.py: the proof deadline is `min(now + 600, horizon)`.
        // The old handler always minted `now + 600`, which after the handler's own
        // time-warp was routinely past `clockOrigin + MATCH_TIMEOUT` — the
        // contract rejected it with "deadline exceeds horizon", correctly. That
        // was the handler's bug, and it is what the 2.3% settle-revert column
        // was measuring.
        uint256 horizon = clockOriginOf(id) + escrow.MATCH_TIMEOUT();
        if (block.timestamp > horizon) {
            skippedPastHorizonSettles++;
            return;
        }
        uint256 deadline = block.timestamp + 600;
        if (deadline > horizon) deadline = horizon;
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
        try
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
            )
        {
            settledCount++;
        } catch (bytes memory reason) {
            _recordRevert("settle", reason);
        }
    }

    function refund(uint256 idSeed) public {
        if (matchIds.length == 0) return;
        bytes32 id = matchIds[idSeed % matchIds.length];
        _recordTerminal(id);
        PulsarEscrow.MatchStatus status = statusOf(id);
        if (status != PulsarEscrow.MatchStatus.Created && status != PulsarEscrow.MatchStatus.Active) return;

        vm.warp(block.timestamp + escrow.MATCH_TIMEOUT() + escrow.REFUND_GRACE() + 1);
        try escrow.refundTimeoutMatch(id) {
            if (status == PulsarEscrow.MatchStatus.Created) cancelledCount++;
            else refundedCount++;
        } catch (bytes memory reason) {
            _recordRevert("refund", reason);
        }
    }

    function withdraw(uint256 actorSeed) public {
        address a = _actor(actorSeed);
        if (escrow.pendingWithdrawals(a) == 0) return;
        vm.prank(a);
        try escrow.withdraw() {
            // nothing to record; the invariants read the escrow
        } catch (bytes memory reason) {
            _recordRevert("withdraw", reason);
        }
    }

    function matchCount() external view returns (uint256) {
        return matchIds.length;
    }

    /// Stake of every open duel plus the pool of every active one, in ONE call.
    ///
    /// This exists for cost, not for convenience. A Foundry invariant function
    /// runs after EVERY fuzzed call, so anything it reads is read `depth` times
    /// per sequence: the original check made four external calls per tracked match
    /// (`matchIds`, `statusOf`, then `stakeOf`/`poolOf`), and one `nightly`
    /// property (1024 x 500) measured 923 s — the check, not the contract, was the
    /// workload. Reading `matches(id)` once and destructuring is the same facts
    /// for a quarter of the calls; `ci` went 115 s -> 68 s.
    ///
    /// It is still an independent model: it re-derives the obligation from the
    /// per-match record and never asks the contract what `totalLocked` is.
    function obligationsFromEscrow() external view returns (uint256 total) {
        uint256 n = matchIds.length;
        for (uint256 i = 0; i < n; i++) {
            (
                ,
                ,
                ,
                uint256 stake,
                uint256 pool,
                ,
                PulsarEscrow.MatchStatus status,
                ,
                ,

            ) = escrow.matches(matchIds[i]);
            if (status == PulsarEscrow.MatchStatus.Created) {
                total += stake;
            } else if (status == PulsarEscrow.MatchStatus.Active) {
                total += pool;
            }
        }
    }

    /// Status, the first terminal status recorded, and the amount at stake — one
    /// read of `matches` plus one of `terminalStatus`, instead of three calls
    /// into the handler followed by three into the escrow.
    function snapshotOf(bytes32 id)
        external
        view
        returns (uint8 status, uint8 firstTerminal, uint256 amount)
    {
        (
            ,
            ,
            ,
            uint256 stake,
            uint256 pool,
            ,
            PulsarEscrow.MatchStatus live,
            ,
            ,

        ) = escrow.matches(id);
        status = uint8(live);
        firstTerminal = uint8(terminalStatus[id]);
        amount = live == PulsarEscrow.MatchStatus.Active ? pool : stake;
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
        assertGe(
            token.balanceOf(address(escrow)),
            _obligations(),
            "the escrow holds less than it owes - money was created or leaked"
        );
    }

    /// Audit M-11: `totalLocked` is what `sweepResidual` trusts, so it must be
    /// EXACTLY the obligations this test computes from the handler's own model,
    /// not merely a bound. A ledger that drifts on the high side would let a
    /// sweep miss recoverable funds; on the low side it would let a sweep take
    /// a player's money, which is the failure this whole feature has to avoid.
    function invariant_total_locked_equals_obligations() public view {
        assertEq(
            escrow.totalLocked(),
            _obligations(),
            "totalLocked drifted from the obligations it is supposed to track"
        );
    }

    /// Nothing in the handler sends tokens to the escrow directly, so every
    /// token in it is owed to somebody and the surplus must be zero at all
    /// times. A non-zero residual here means an increment or a decrement in the
    /// ledger was missed.
    function invariant_residual_is_zero_without_stray_transfers() public view {
        assertEq(
            escrow.residualBalance(),
            0,
            "the escrow believes it has unowned funds - the locked ledger is wrong"
        );
    }

    /// Stakes of open duels plus every deferred payout the escrow owes.
    function _obligations() internal view returns (uint256 obligations) {
        obligations = handler.obligationsFromEscrow() + _pendingTotal();
    }

    /// A settled or refunded duel is terminal: its status never changes again.
    function invariant_settled_and_refunded_are_terminal() public view {
        uint256 n = handler.matchCount();
        for (uint256 i = 0; i < n; i++) {
            bytes32 id = handler.matchIds(i);
            (uint8 status, uint8 first,) = handler.snapshotOf(id);
            assertTrue(
                status != uint8(PulsarEscrow.MatchStatus.None),
                "a created match lost its record"
            );
            // Audit 2026-10-13: the real property. Once a match reached a
            // terminal state it must still be in THAT state — a settled duel
            // must never become refundable, and a refunded one must never be
            // settled. The old body asserted only `status != None`, which is
            // true for every match the handler touched, so it could not fail.
            if (first != uint8(PulsarEscrow.MatchStatus.None)) {
                assertEq(status, first, "a terminal duel changed status");
            }
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

    /// Every state-changing call the handler makes must succeed.
    ///
    /// This is the property that makes the rest of the campaign mean something.
    /// With `fail_on_revert = false`, a revert is a discarded call: the six
    /// financial invariants above still pass, because they only observe state
    /// after successful calls. So a contract that started rejecting `join` for a
    /// NEW reason — a broken token transfer, a require nobody predicted — would
    /// sail through 3 million calls and report green.
    ///
    /// Now it cannot. Any revert is recorded, and this asserts the record is
    /// empty, naming the call and the raw reason.
    function invariant_no_unexpected_reverts() public view {
        // Written as an early branch, NOT `assertEq(..., string.concat(...))`.
        //
        // Foundry evaluates the message argument on EVERY check. `string.concat`
        // plus a hex encoder ran ~3.5 million times in the first version of this
        // invariant and turned a 21-minute campaign into one that had not
        // finished after 43 minutes. The deep run is the only evidence this repo
        // has for its financial invariants, so making it unusably slow is its own
        // kind of failure. On the happy path this now allocates nothing.
        uint256 reverts = handler.revertCount();
        if (reverts != 0) {
            revert(
                string.concat(
                    "a handler call reverted where none should: ",
                    handler.firstRevertIn(),
                    " / raw reason: ",
                    _hex(handler.firstRevert())
                )
            );
        }
    }

    function _hex(bytes memory data) internal pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";
        bytes memory out = new bytes(data.length * 2);
        for (uint256 i = 0; i < data.length; i++) {
            out[i * 2] = alphabet[uint8(data[i]) >> 4];
            out[i * 2 + 1] = alphabet[uint8(data[i]) & 0x0f];
        }
        return string(out);
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

/**
 * The negative control (2026-10-24).
 *
 * `invariant_no_unexpected_reverts` is only worth having if it can fail. A test
 * that asserts "nothing reverted" is indistinguishable from a test that cannot
 * observe reverts at all — which is exactly the hole this whole change closes,
 * so it must not be re-opened by an invariant that quietly does nothing.
 *
 * This contract drives a handler whose `join` reverts on purpose and asserts
 * that the tracked counter moves. It is a plain unit test, not a fuzz campaign:
 * the point is that the mechanism records, not that the contract is correct.
 */
contract EscrowHandlerRevertControl is Test {
    PulsarEscrow internal escrow;
    MockUSDT internal token;

    // The escrow's oracle is `vm.addr(CORRECT_KEY)`; this handler signs with a
    // DIFFERENT key, so a settlement it builds is a valid call with an invalid
    // signature — the one revert we can provoke without touching the handler's
    // own guards.
    uint256 internal constant CORRECT_KEY = 0xA11CE;
    uint256 internal constant WRONG_KEY = 0xBAD;

    function setUp() public {
        token = new MockUSDT();
        escrow = new PulsarEscrow(address(token), address(0x7EA5), vm.addr(CORRECT_KEY));
    }

    function test_the_revert_record_is_empty_when_nothing_reverts() public {
        EscrowHandler handler = new EscrowHandler(escrow, token, CORRECT_KEY);
        handler.create(0);
        handler.join(0, 1);
        assertEq(handler.revertCount(), 0, "a legal create+join was recorded as a revert");
        assertEq(handler.firstRevert().length, 0);
    }

    function test_a_revert_is_recorded_with_its_call_and_reason() public {
        EscrowHandler handler = new EscrowHandler(escrow, token, WRONG_KEY);
        handler.create(0);
        handler.join(0, 1);
        assertEq(handler.revertCount(), 0, "create/join must not revert");

        handler.settle(0, 0);
        assertEq(handler.revertCount(), 1, "the settlement revert was not recorded");
        assertEq(handler.firstRevertIn(), "settle");
        assertGt(handler.firstRevert().length, 0, "the reason bytes were not captured");
    }
}
