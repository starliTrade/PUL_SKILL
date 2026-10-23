// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title PulsarEscrow - Non-Custodial Real Web3 Skill Battle Escrow & Oracle Settlement
 * @author Pulsar Protocol Team
 * @notice Optimized to prevent Stack Too Deep on all standard Solidity EVM compilers.
 */

interface IERC20Metadata {
    function decimals() external view returns (uint8);
}

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
}

/**
 * F-19 — SafeERC20-equivalent helpers, inlined (the contract is
 * dependency-free by design). Wraps the optional-bool-return reality of
 * real USDT: if the token returns data it MUST decode to true; if it returns
 * nothing, success is the absence of revert.
 */
library SafeTransfer {
    function _callAndCheck(bool success, bytes memory data) private pure returns (bool) {
        if (!success) {
            // Solidity ≥0.8 bubbles revert reasons automatically.
            assembly {
                revert(add(data, 0x20), mload(data))
            }
        }
        if (data.length == 0) {
            return true; // non-standard token (e.g. USDT): no return value
        }
        require(data.length >= 32, "SafeTransfer: short return");
        bool ok;
        assembly {
            ok := mload(add(data, 0x20))
        }
        return ok;
    }

    /**
     * @dev Non-reverting transfer: returns false instead of bubbling a revert.
     *
     * Audit H17: the escrow must be able to attempt a payout without the whole
     * transaction reverting, because a single undeliverable recipient would
     * otherwise freeze the counterparty's funds too.
     */
    function tryTransfer(IERC20 token, address to, uint256 amount) internal returns (bool) {
        (bool success, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transfer.selector, to, amount)
        );
        if (!success) {
            return false;
        }
        if (data.length == 0) {
            return true; // non-standard token (e.g. USDT): no return value
        }
        if (data.length < 32) {
            return false;
        }
        bool ok;
        assembly {
            ok := mload(add(data, 0x20))
        }
        return ok;
    }

    function safeTransfer(IERC20 token, address to, uint256 amount) internal {
        (bool success, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transfer.selector, to, amount)
        );
        require(_callAndCheck(success, data), "SafeTransfer: transfer failed");
    }

    function safeTransferFrom(IERC20 token, address from, address to, uint256 amount) internal {
        (bool success, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transferFrom.selector, from, to, amount)
        );
        require(_callAndCheck(success, data), "SafeTransfer: transferFrom failed");
    }
}

abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }
}

abstract contract Ownable is Context {
    address private _owner;
    address private _pendingOwner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);

    function pendingOwner() public view virtual returns (address) {
        return _pendingOwner;
    }

    constructor(address initialOwner) {
        require(initialOwner != address(0), "Ownable: zero owner");
        _transferOwnership(initialOwner);
    }

    function owner() public view virtual returns (address) {
        return _owner;
    }

    modifier onlyOwner() {
        require(owner() == _msgSender(), "Ownable: caller is not owner");
        _;
    }

    function transferOwnership(address newOwner) public virtual onlyOwner {
        require(newOwner != address(0), "Ownable: zero address");
        // P0-fix: two-step handover — a fat-fingered address no longer bricks
        // admin forever. The new owner must call acceptOwnership().
        _pendingOwner = newOwner;
        emit OwnershipTransferStarted(_owner, newOwner);
    }

    function acceptOwnership() public virtual {
        require(msg.sender == _pendingOwner, "Ownable: not pending owner");
        _transferOwnership(msg.sender);
        _pendingOwner = address(0);
    }

    function _transferOwnership(address newOwner) internal virtual {
        address oldOwner = _owner;
        _owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }
}

abstract contract ReentrancyGuard {
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;
    uint256 private _status;

    constructor() {
        _status = _NOT_ENTERED;
    }

    modifier nonReentrant() {
        require(_status != _ENTERED, "ReentrancyGuard: reentrant call");
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }
}

contract PulsarEscrow is Ownable, ReentrancyGuard {
    using SafeTransfer for IERC20;
    uint256 public constant FEE_DENOMINATOR = 10000; // 100.00%
    uint256 public constant PLATFORM_FEE_BPS = 200;  // 2.00% (98% to winner)
    // Refund opens 30 minutes after the FIRST deposit. The oracle signature is
    // valid for 10 minutes AFTER match end (signing), and a match can run up
    // to ~10 minutes after the deposit — so the winner's settle window can
    // extend to ~20 minutes post-deposit. A 10-minute MATCH_TIMEOUT opened
    // refund before settlement could close, letting a losing player refund
    // both stakes and negate the loss. 30 min guarantees the settle window is
    // provably closed (deadline expired) before any refund can open.
    uint256 public constant MATCH_TIMEOUT = 30 minutes;
    /**
     * @dev Audit H19 (decision D2, option A) — the exclusive settlement window.
     *
     * `refundTimeoutMatch` is permissionless and used to open at exactly the
     * instant the settlement proof expired, so a losing player could stall past
     * the horizon and refund — or front-run the winner's `settleDuel` in the
     * same block — recovering their full stake and destroying the winner's
     * prize. Timing out was a free option for the party that was losing.
     *
     * Settlement is now the ONLY exit until MATCH_TIMEOUT, and the refund opens
     * this much later. The winner gets a full, uncontested window.
     */
    uint256 public constant REFUND_GRACE = 10 minutes;
    // Anti-dust/anti-spam floor: one whole payment token. Permissionless
    // createDuel with `stake > 0` let anyone squat matchIds and spam Created
    // duels for ~1 wei.
    //
    // Audit M22: this used to be the literal 1_000_000, i.e. "1 USDT at 6
    // decimals". Deployed against any other token the floor silently became
    // dust while the server read the real `decimals()` — the two disagreed
    // about what "1 USDT" means. Derived from the token in the constructor.
    uint256 public immutable MIN_STAKE_UNITS;

    /**
     * @dev Audit M24 — admin changes are timelocked.
     *
     * `setTreasuryWallet` / `setOracleSigner` used to take effect immediately.
     * A typo'd treasury routes every future fee to an unrecoverable address,
     * and an oracle rotation instantly invalidates every outstanding signed
     * settlement — a winner mid-claim loses their proof with no warning.
     */
    uint256 public constant ADMIN_TIMELOCK = 2 days;

    /**
     * @dev Audit M-11 — the escrow is NOT upgradeable, and this is the
     * deliberately chosen alternative to a proxy.
     *
     * A proxy would let a key change the code that custodies live money: one
     * bad upgrade and every stake in the contract is gone, and the storage
     * layout becomes a permanent, invisible constraint on every future change.
     * For a two-week-old contract holding player money, an immutable escrow
     * plus an explicit migration procedure is the smaller risk.
     *
     * What a migration needs, and what is implemented below:
     *   - `VERSION`/`VERSION_CODE`: an address can be checked against the code
     *     it is supposed to be running (`api/onchain.py` does exactly that);
     *   - `freeze()`: stop NEW deposits while the replacement is deployed;
     *     settlements, refunds and withdrawals stay open, so a freeze can
     *     never trap funds — this is the migration window;
     *   - `totalLocked` + `residualBalance()`: the contract can prove on-chain
     *     how much of its balance belongs to players, so the operator knows
     *     when the old escrow is empty and whether a stray transfer is
     *     sweepable without touching player money.
     *
     * Bump BOTH on any behavior-changing deploy; `tests/unit/test_contract_version.py`
     * pins them together with the server's expectation.
     */
    string public constant VERSION = "2.0.0";
    uint256 public constant VERSION_CODE = 2;

    IERC20 public immutable paymentToken;
    address public treasuryWallet;
    address public oracleSigner;
    address public pendingTreasuryWallet;
    uint256 public treasuryEffectiveAt;
    address public pendingOracleSigner;
    uint256 public oracleEffectiveAt;

    enum MatchStatus {
        None,
        Created,
        Active,
        Settled,
        Cancelled,
        Refunded
    }

    struct DuelMatch {
        bytes32 matchId;
        address player1;
        address player2;
        uint256 stakeAmount;
        uint256 totalPool;
        uint256 createdAt;
        MatchStatus status;
        address winner;
        uint256 winnerReactionMs;
        uint256 loserReactionMs;
    }

    struct SettlementProof {
        bytes32 matchId;
        address winner;
        uint256 winnerTimeMs;
        uint256 loserTimeMs;
        uint256 nonce;
        uint256 deadline;   // P1.17: settlement must be submitted before this Unix time
        bytes signature;
    }

    mapping(bytes32 => DuelMatch) public matches;
    /**
     * @dev Audit M25 — this is DEFENCE IN DEPTH, not the replay defence.
     *
     * It is unreachable in practice: a replay of the same proof hits the
     * `status == Active` check first and reverts there, so the mapping is only
     * ever consulted if that check is ever relaxed. The comment and the test
     * used to claim it was what stopped replays, which overstated it.
     *
     * Kept because it is cheap insurance for a future change to the status
     * gate; the test that exercises it now says what it actually proves.
     */
    mapping(bytes32 => bool) public usedSignatures;

    /**
     * @dev Audit H17 — payouts that could not be delivered at settlement time.
     *
     * Real USDT can pause and blacklist addresses, and a participant can be a
     * contract that reverts on receipt. Settling both sides in one transaction
     * meant one bad recipient reverted the whole call and froze the other
     * party's funds indefinitely. An undeliverable payout is credited here
     * instead, and the beneficiary pulls it later with `withdraw()`.
     */
    mapping(address => uint256) public pendingWithdrawals;

    /**
     * @dev Audit H20 — when the joiner paired, i.e. when the duel became
     * playable. Kept OUT of DuelMatch on purpose: the struct layout is decoded
     * by the server (`onchain._decode_match`) and pinned by a test, so adding a
     * field would be a cross-component change for a value only the contract
     * needs.
     *
     * Zero means "never activated" — an unpaired duel, whose refund clock stays
     * anchored to `createdAt`.
     */
    mapping(bytes32 => uint256) public activatedAt;

    uint256 public totalDuelsSettled;
    uint256 public totalVolumeDistributed;
    uint256 public totalFeesCollected;

    /**
     * @dev Audit M-11 — how much of `paymentToken.balanceOf(this)` is owed to
     * someone: open stakes plus deferred payouts. Anything above it is a stray
     * transfer (someone sent USDT to the escrow by mistake), and it is the ONLY
     * amount `sweepResidual` may move.
     *
     * Before this, the contract had no idea what it owed: an accidental
     * transfer was indistinguishable from player money, so there was no safe
     * way to recover it, and nothing on-chain to check a migration against.
     */
    uint256 public totalLocked;

    /**
     * @dev Audit M-11 — the migration window.
     *
     * `frozen` blocks `createDuel` and `joinDuel` only. Settlement, refund and
     * withdrawal never consult it: freezing must never be able to hold a
     * player's money hostage, otherwise "the operator paused the escrow" and
     * "the operator stole the escrow" look the same from the outside.
     */
    bool public frozen;
    uint256 public frozenAt;

    event MatchCreated(bytes32 indexed matchId, address indexed player1, uint256 stakeAmount, uint256 totalPool);
    event MatchJoined(bytes32 indexed matchId, address indexed player2);
    event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizePaid, uint256 platformFee);
    event MatchCancelled(bytes32 indexed matchId, string reason);
    event MatchRefunded(bytes32 indexed matchId, uint256 refundPerPlayer);
    event TreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event PayoutDeferred(address indexed to, uint256 amount);
    event TreasuryChangeScheduled(address indexed newTreasury, uint256 effectiveAt);
    event OracleChangeScheduled(address indexed newOracle, uint256 effectiveAt);
    event PendingAdminChangesCancelled();
    event Withdrawn(address indexed to, uint256 amount);
    event OracleSignerUpdated(address indexed oldOracle, address indexed newOracle);
    event EscrowFrozen(address indexed by, uint256 at);
    event EscrowUnfrozen(address indexed by, uint256 at);
    event ResidualSwept(address indexed to, uint256 amount);

    constructor(
        address _paymentToken,
        address _treasuryWallet,
        address _oracleSigner
    ) Ownable(msg.sender) {
        require(_paymentToken != address(0), "Invalid payment token");
        require(_treasuryWallet != address(0), "Invalid treasury wallet");
        require(_oracleSigner != address(0), "Invalid oracle signer");

        paymentToken = IERC20(_paymentToken);
        treasuryWallet = _treasuryWallet;
        oracleSigner = _oracleSigner;

        // Audit M22: read the token's own decimals rather than assuming 6.
        uint8 decimals = IERC20Metadata(_paymentToken).decimals();
        require(decimals <= 36, "Invalid token decimals");
        MIN_STAKE_UNITS = 10 ** uint256(decimals);
    }

    function createDuel(bytes32 matchId, uint256 stakeAmount) external nonReentrant {
        require(!frozen, "Escrow frozen");
        require(stakeAmount >= MIN_STAKE_UNITS, "Stake below minimum");
        require(matches[matchId].status == MatchStatus.None, "Match already exists");

        uint256 beforeBalance = paymentToken.balanceOf(address(this));
        SafeTransfer.safeTransferFrom(paymentToken, msg.sender, address(this), stakeAmount);
        uint256 received = paymentToken.balanceOf(address(this)) - beforeBalance;
        require(received >= MIN_STAKE_UNITS, "Received below minimum");

        // Audit M-11: the escrow now tracks what it owes, not just what it holds.
        totalLocked += received;

        matches[matchId] = DuelMatch({
            matchId: matchId,
            player1: msg.sender,
            player2: address(0),
            // F-19: account for fee-on-transfer tokens — the POOL is what
            // actually sits in escrow, never the nominal amount.
            stakeAmount: received,
            totalPool: 0, // set to 2× stake on join
            createdAt: block.timestamp,
            status: MatchStatus.Created,
            winner: address(0),
            winnerReactionMs: 0,
            loserReactionMs: 0
        });

        // Audit M23: the pool is 0 until the joiner pays; emitting `received*2`
        // showed indexers a 2x pool for a duel holding one stake.
        emit MatchCreated(matchId, msg.sender, received, 0);
    }

    function joinDuel(bytes32 matchId) external nonReentrant {
        require(!frozen, "Escrow frozen");
        DuelMatch storage duel = matches[matchId];
        require(duel.status == MatchStatus.Created, "Match not available");
        require(duel.player1 != msg.sender, "Cannot play against self");
        // Audit H20: joining a duel that is already refundable would produce an
        // Active match that can be unwound one second later.
        require(block.timestamp < duel.createdAt + MATCH_TIMEOUT, "Match expired");

        uint256 beforeBalance = paymentToken.balanceOf(address(this));
        SafeTransfer.safeTransferFrom(paymentToken, msg.sender, address(this), duel.stakeAmount);
        uint256 received = paymentToken.balanceOf(address(this)) - beforeBalance;
        require(received == duel.stakeAmount, "Fee-on-transfer deposit rejected");

        totalLocked += received;

        duel.player2 = msg.sender;
        duel.status = MatchStatus.Active;
        duel.totalPool = duel.stakeAmount * 2;
        // Audit H20: the refund clock starts when the duel becomes playable,
        // not when the first stake was deposited.
        activatedAt[matchId] = block.timestamp;

        emit MatchJoined(matchId, msg.sender);
    }

    /**
     * @notice Settle match with compact Struct parameter to prevent EVM stack limits
     */
    function settleDuel(SettlementProof calldata proof) external nonReentrant {
        DuelMatch storage duel = matches[proof.matchId];
        require(duel.status == MatchStatus.Active, "Match is not active");
        require(proof.winner == duel.player1 || proof.winner == duel.player2, "Winner not participant");

        // P1.17: a signed settlement expires — the referee must re-sign with
        // fresh state if submission is delayed past the deadline.
        require(block.timestamp <= proof.deadline, "Settlement proof expired");
        // Audit H18: the contract must enforce its OWN horizon. Without this,
        // "the signature expires before the permissionless refund opens" was
        // guaranteed only by the server's clamp — one over-long deadline and a
        // settlement could land after refunds were live, racing them.
        //
        // Audit 2026-10-13: the horizon must use the SAME anchor as
        // `refundTimeoutMatch`. H20 moved the refund clock to ACTIVATION but
        // left this one on `createdAt`, so the two disagreed by exactly the
        // queue wait. The server's `settlement_deadline` follows the refund, so
        // every proof it minted more than 20 minutes after the deposit — and
        // EVERY F-12 re-sign, whose whole purpose is the late winner — was
        // rejected here. The winner could only get a refund.
        uint256 clockOrigin = activatedAt[proof.matchId] > duel.createdAt
            ? activatedAt[proof.matchId]
            : duel.createdAt;
        require(
            proof.deadline <= clockOrigin + MATCH_TIMEOUT,
            "deadline exceeds horizon"
        );

        // Verify cryptographic oracle signature
        // NOTE: preimage MUST stay byte-identical to api/oracle.py
        // build_settlement_digest(). They are one protocol.
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(
                    abi.encodePacked(
                        proof.matchId,
                        proof.winner,
                        proof.winnerTimeMs,
                        proof.loserTimeMs,
                        proof.nonce,
                        proof.deadline,
                        block.chainid,
                        address(this)
                    )
                )
            )
        );

        require(!usedSignatures[ethSignedHash], "Signature already used");
        usedSignatures[ethSignedHash] = true;

        require(recoverSigner(ethSignedHash, proof.signature) == oracleSigner, "Invalid Oracle signature");

        // Calculate 2% platform fee & 98% prize pool
        uint256 platformFee = (duel.totalPool * PLATFORM_FEE_BPS) / FEE_DENOMINATOR;
        uint256 winnerPrize = duel.totalPool - platformFee;

        // Update match state
        duel.status = MatchStatus.Settled;
        duel.winner = proof.winner;
        duel.winnerReactionMs = proof.winnerTimeMs;
        duel.loserReactionMs = proof.loserTimeMs;

        totalDuelsSettled++;
        totalVolumeDistributed += winnerPrize;
        totalFeesCollected += platformFee;

        // Execute Non-Custodial Token Transfers (F-19: SafeERC20 semantics).
        // Audit H17: `_pay` credits instead of reverting, so a blocked winner
        // cannot stop the treasury fee and vice versa.
        _pay(proof.winner, winnerPrize);
        _pay(treasuryWallet, platformFee);

        emit MatchSettled(proof.matchId, proof.winner, winnerPrize, platformFee);
    }

    function refundTimeoutMatch(bytes32 matchId) external nonReentrant {
        DuelMatch storage duel = matches[matchId];
        require(duel.status == MatchStatus.Created || duel.status == MatchStatus.Active, "Cannot refund");
        // Audit H20: anchor on ACTIVATION when there was one, so a duel that
        // paired late still gets its full play window. An unpaired duel keeps
        // the deposit clock.
        uint256 clockOrigin = activatedAt[matchId] > duel.createdAt
            ? activatedAt[matchId]
            : duel.createdAt;
        require(
            block.timestamp >= clockOrigin + MATCH_TIMEOUT + REFUND_GRACE,
            "Match not timed out"
        );

        uint256 refundAmount = duel.stakeAmount;

        if (duel.status == MatchStatus.Created) {
            duel.status = MatchStatus.Cancelled;
            // Audit H17: credit instead of reverting (see _pay).
            _pay(duel.player1, refundAmount);
            emit MatchCancelled(matchId, "Timeout cancelled");
        } else {
            duel.status = MatchStatus.Refunded;
            _pay(duel.player1, refundAmount);
            _pay(duel.player2, refundAmount);
            emit MatchRefunded(matchId, refundAmount);
        }
    }

    /**
     * @dev Deliver `amount` to `to`, or credit it for a later pull (audit H17).
     *
     * The direct transfer is attempted first — the normal path, no extra gas
     * and no extra transaction for the recipient. Only when the token rejects
     * it is the amount credited, so that the OTHER party's payout still lands
     * in the same transaction.
     */
    function _pay(address to, uint256 amount) internal {
        if (amount == 0) {
            return;
        }
        if (SafeTransfer.tryTransfer(paymentToken, to, amount)) {
            // Audit M-11: the money left the escrow, so the obligation ends
            // here. A DEFERRED credit is deliberately NOT subtracted — it is
            // still owed, just to `pendingWithdrawals` instead of the duel.
            totalLocked -= amount;
            return;
        }
        pendingWithdrawals[to] += amount;
        emit PayoutDeferred(to, amount);
    }

    /**
     * @dev Pull a payout that could not be delivered when the duel settled.
     *
     * Deliberately reverting when there is nothing to withdraw: a silent no-op
     * would look like a successful claim.
     */
    /**
     * @dev Claim a payout the token refused at settlement time (audit H17).
     *
     * Audit 2026-10-13 — the deferred credit is held, not lost, and that is
     * deliberate. A recipient the TOKEN refuses (a Tether blacklist, a paused
     * token, a contract that reverts on receipt) cannot be paid by this escrow,
     * and this function reverts for them exactly as `settleDuel` would have.
     * Two alternatives were considered and rejected:
     *
     *   - paying an ALTERNATE address: that would let a blacklisted recipient
     *     route around the token issuer's own control. The escrow must not
     *     defeat a sanctions/blacklist decision;
     *   - an admin sweep of stuck credits: that is a seizure of a player's
     *     money by the operator.
     *
     * So the credit stays on `pendingWithdrawals[recipient]` until the token
     * allows the transfer. If the blacklist is lifted, this call pays in full —
     * the money is not destroyed, it is waiting. The duel's other side is
     * unaffected: the fee still reaches the treasury, and the loser's stake was
     * genuinely lost (pre-H17 the whole settlement reverted, which handed the
     * loser a free option — see the H17 note on `_pay`).
     */
    function withdraw() external nonReentrant {
        uint256 amount = pendingWithdrawals[msg.sender];
        require(amount > 0, "Nothing to withdraw");
        pendingWithdrawals[msg.sender] = 0;
        SafeTransfer.safeTransfer(paymentToken, msg.sender, amount);
        // Audit M-11: the deferred credit was part of `totalLocked`; now it is
        // in the player's hands instead of the escrow's.
        totalLocked -= amount;
        emit Withdrawn(msg.sender, amount);
    }

    // --- Audit M-11: versioning + migration window --------------------------

    /**
     * @notice Stop new stakes from entering this escrow.
     *
     * The first step of a migration: deploy the replacement, freeze this one so
     * no new duel can be funded into the old code, let the open duels settle or
     * time out, then point the server at the new address. The old escrow stays
     * deployed forever for anyone who still holds a deferred credit — nothing
     * below is time-limited.
     *
     * Deliberately NOT timelocked. Freezing is the *safe* direction: it can
     * only stop deposits, never a payout. A two-day delay on "stop taking money
     * into a contract you are abandoning" would defeat the purpose, and every
     * freeze/unfreeze lands in the event log.
     */
    function freeze() external onlyOwner {
        require(!frozen, "Already frozen");
        frozen = true;
        frozenAt = block.timestamp;
        emit EscrowFrozen(msg.sender, block.timestamp);
    }

    /**
     * @notice Re-open this escrow for new stakes (aborted migration).
     *
     * Also instant: re-opening only restores the pre-freeze behavior, and the
     * deposits it allows are the ordinary, audited path. An admin cannot use
     * unfreeze to move money — there is no such function.
     */
    function unfreeze() external onlyOwner {
        require(frozen, "Not frozen");
        frozen = false;
        uint256 at = frozenAt;
        frozenAt = 0;
        emit EscrowUnfrozen(msg.sender, at);
    }

    /// @notice Balance that is NOT owed to any player or to the treasury.
    ///
    /// Zero in normal operation. Non-zero means someone sent tokens to the
    /// escrow by mistake (or a fee-on-transfer token left dust), and the amount
    /// is exactly what `sweepResidual` may move.
    function residualBalance() public view returns (uint256) {
        uint256 balance = paymentToken.balanceOf(address(this));
        return balance > totalLocked ? balance - totalLocked : 0;
    }

    /**
     * @notice Recover tokens that were sent to the escrow by mistake.
     *
     * Two independent guards, because this is the one function that moves
     * tokens without a duel:
     *   1. it can only move `residualBalance()` — player stakes and deferred
     *      payouts are reported by `totalLocked` and are untouchable here;
     *   2. it only works while `frozen` — i.e. during a migration window, when
     *      no new money is entering. A transfer to the escrow at any other time
     *      is indistinguishable from a stake deposit arriving late, and acting
     *      on it then is how an operator ends up "recovering" a player's stake.
     *
     * The cost is honest: dust is recoverable only during a migration. That is
     * an acceptable trade for never touching player money.
     */
    function sweepResidual(address to) external onlyOwner nonReentrant {
        require(frozen, "Not frozen");
        require(to != address(0), "Zero address");
        uint256 amount = residualBalance();
        require(amount > 0, "No residual");
        SafeTransfer.safeTransfer(paymentToken, to, amount);
        emit ResidualSwept(to, amount);
    }

    /// @dev Audit M24: schedule a treasury change; it applies after ADMIN_TIMELOCK.
    function setTreasuryWallet(address _newTreasury) external onlyOwner {
        require(_newTreasury != address(0), "Zero address");
        pendingTreasuryWallet = _newTreasury;
        treasuryEffectiveAt = block.timestamp + ADMIN_TIMELOCK;
        emit TreasuryChangeScheduled(_newTreasury, treasuryEffectiveAt);
    }

    /// @dev Apply a scheduled treasury change once the timelock has elapsed.
    function applyTreasuryWallet() external {
        require(pendingTreasuryWallet != address(0), "No pending treasury");
        require(block.timestamp >= treasuryEffectiveAt, "Timelock not elapsed");
        address oldTreasury = treasuryWallet;
        treasuryWallet = pendingTreasuryWallet;
        pendingTreasuryWallet = address(0);
        treasuryEffectiveAt = 0;
        emit TreasuryUpdated(oldTreasury, treasuryWallet);
    }

    /// @dev Audit M24: schedule an oracle change; it applies after ADMIN_TIMELOCK.
    function setOracleSigner(address _newOracle) external onlyOwner {
        require(_newOracle != address(0), "Zero address");
        pendingOracleSigner = _newOracle;
        oracleEffectiveAt = block.timestamp + ADMIN_TIMELOCK;
        emit OracleChangeScheduled(_newOracle, oracleEffectiveAt);
    }

    /// @dev Apply a scheduled oracle change once the timelock has elapsed.
    function applyOracleSigner() external {
        require(pendingOracleSigner != address(0), "No pending oracle");
        require(block.timestamp >= oracleEffectiveAt, "Timelock not elapsed");
        address oldOracle = oracleSigner;
        oracleSigner = pendingOracleSigner;
        pendingOracleSigner = address(0);
        oracleEffectiveAt = 0;
        emit OracleSignerUpdated(oldOracle, oracleSigner);
    }

    /// @dev Cancel both pending admin changes.
    function cancelPendingAdminChanges() external onlyOwner {
        pendingTreasuryWallet = address(0);
        treasuryEffectiveAt = 0;
        pendingOracleSigner = address(0);
        oracleEffectiveAt = 0;
        emit PendingAdminChangesCancelled();
    }

    function recoverSigner(bytes32 ethSignedHash, bytes memory signature) internal pure returns (address) {
        require(signature.length == 65, "Invalid signature length");

        bytes32 r;
        bytes32 s;
        uint8 v;

        assembly {
            r := mload(add(signature, 32))
            s := mload(add(signature, 64))
            v := byte(0, mload(add(signature, 96)))
        }

        if (v < 27) {
            v += 27;
        }

        require(v == 27 || v == 28, "Invalid signature v value");

        // P1.17: enforce low-s (EIP-2 style) to kill signature malleability.
        // (s, r, v) and (s', r, v') with s' = n - s recover the SAME address;
        // without this check one oracle signature could be replayed twice
        // with different usedSignatures hashes.
        require(
            uint256(s) <= 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0,
            "Signature s-value too high"
        );

        return ecrecover(ethSignedHash, v, r, s);
    }
}
