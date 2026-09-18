// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title PulsarEscrow - Non-Custodial Real Web3 Skill Battle Escrow & Oracle Settlement
 * @author Pulsar Protocol Team
 * @notice Optimized to prevent Stack Too Deep on all standard Solidity EVM compilers.
 */

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
    // P0-fix: anti-dust/anti-spam floor. Server ALLOWED_STAKES are 1/2/5/10 USDT
    // (6 decimals => 1 USDT = 1e6 units). Permissionless createDuel with
    // `stake > 0` let anyone squat matchIds and spam Created duels for ~1 wei.
    uint256 public constant MIN_STAKE_UNITS = 1_000_000;

    IERC20 public immutable paymentToken;
    address public treasuryWallet;
    address public oracleSigner;

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
    mapping(bytes32 => bool) public usedSignatures;

    uint256 public totalDuelsSettled;
    uint256 public totalVolumeDistributed;
    uint256 public totalFeesCollected;

    event MatchCreated(bytes32 indexed matchId, address indexed player1, uint256 stakeAmount, uint256 totalPool);
    event MatchJoined(bytes32 indexed matchId, address indexed player2);
    event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 prizePaid, uint256 platformFee);
    event MatchCancelled(bytes32 indexed matchId, string reason);
    event MatchRefunded(bytes32 indexed matchId, uint256 refundPerPlayer);
    event TreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event OracleSignerUpdated(address indexed oldOracle, address indexed newOracle);

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
    }

    function createDuel(bytes32 matchId, uint256 stakeAmount) external nonReentrant {
        require(stakeAmount >= MIN_STAKE_UNITS, "Stake below minimum");
        require(matches[matchId].status == MatchStatus.None, "Match already exists");

        uint256 beforeBalance = paymentToken.balanceOf(address(this));
        SafeTransfer.safeTransferFrom(paymentToken, msg.sender, address(this), stakeAmount);
        uint256 received = paymentToken.balanceOf(address(this)) - beforeBalance;
        require(received >= MIN_STAKE_UNITS, "Received below minimum");

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

        emit MatchCreated(matchId, msg.sender, received, received * 2);
    }

    function joinDuel(bytes32 matchId) external nonReentrant {
        DuelMatch storage duel = matches[matchId];
        require(duel.status == MatchStatus.Created, "Match not available");
        require(duel.player1 != msg.sender, "Cannot play against self");

        uint256 beforeBalance = paymentToken.balanceOf(address(this));
        SafeTransfer.safeTransferFrom(paymentToken, msg.sender, address(this), duel.stakeAmount);
        uint256 received = paymentToken.balanceOf(address(this)) - beforeBalance;
        require(received == duel.stakeAmount, "Fee-on-transfer deposit rejected");

        duel.player2 = msg.sender;
        duel.status = MatchStatus.Active;
        duel.totalPool = duel.stakeAmount * 2;

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

        // Execute Non-Custodial Token Transfers (F-19: SafeERC20 semantics)
        SafeTransfer.safeTransfer(paymentToken, proof.winner, winnerPrize);
        if (platformFee > 0) {
            SafeTransfer.safeTransfer(paymentToken, treasuryWallet, platformFee);
        }

        emit MatchSettled(proof.matchId, proof.winner, winnerPrize, platformFee);
    }

    function refundTimeoutMatch(bytes32 matchId) external nonReentrant {
        DuelMatch storage duel = matches[matchId];
        require(duel.status == MatchStatus.Created || duel.status == MatchStatus.Active, "Cannot refund");
        require(block.timestamp >= duel.createdAt + MATCH_TIMEOUT, "Match not timed out");

        uint256 refundAmount = duel.stakeAmount;

        if (duel.status == MatchStatus.Created) {
            duel.status = MatchStatus.Cancelled;
            SafeTransfer.safeTransfer(paymentToken, duel.player1, refundAmount);
            emit MatchCancelled(matchId, "Timeout cancelled");
        } else {
            duel.status = MatchStatus.Refunded;
            SafeTransfer.safeTransfer(paymentToken, duel.player1, refundAmount);
            SafeTransfer.safeTransfer(paymentToken, duel.player2, refundAmount);
            emit MatchRefunded(matchId, refundAmount);
        }
    }

    function setTreasuryWallet(address _newTreasury) external onlyOwner {
        require(_newTreasury != address(0), "Zero address");
        address oldTreasury = treasuryWallet;
        treasuryWallet = _newTreasury;
        emit TreasuryUpdated(oldTreasury, _newTreasury);
    }

    function setOracleSigner(address _newOracle) external onlyOwner {
        require(_newOracle != address(0), "Zero address");
        address oldOracle = oracleSigner;
        oracleSigner = _newOracle;
        emit OracleSignerUpdated(oldOracle, _newOracle);
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
