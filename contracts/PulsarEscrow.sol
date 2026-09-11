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

abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }
}

abstract contract Ownable is Context {
    address private _owner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

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
        _transferOwnership(newOwner);
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
        require(stakeAmount > 0, "Stake must be > 0");
        require(matches[matchId].status == MatchStatus.None, "Match already exists");

        require(paymentToken.transferFrom(msg.sender, address(this), stakeAmount), "Deposit failed");

        matches[matchId] = DuelMatch({
            matchId: matchId,
            player1: msg.sender,
            player2: address(0),
            stakeAmount: stakeAmount,
            totalPool: stakeAmount * 2,
            createdAt: block.timestamp,
            status: MatchStatus.Created,
            winner: address(0),
            winnerReactionMs: 0,
            loserReactionMs: 0
        });

        emit MatchCreated(matchId, msg.sender, stakeAmount, stakeAmount * 2);
    }

    function joinDuel(bytes32 matchId) external nonReentrant {
        DuelMatch storage duel = matches[matchId];
        require(duel.status == MatchStatus.Created, "Match not available");
        require(duel.player1 != msg.sender, "Cannot play against self");

        require(paymentToken.transferFrom(msg.sender, address(this), duel.stakeAmount), "Deposit failed");

        duel.player2 = msg.sender;
        duel.status = MatchStatus.Active;

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

        // Execute Non-Custodial Token Transfers
        require(paymentToken.transfer(proof.winner, winnerPrize), "Winner transfer failed");
        if (platformFee > 0) {
            require(paymentToken.transfer(treasuryWallet, platformFee), "Fee transfer failed");
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
            require(paymentToken.transfer(duel.player1, refundAmount), "Refund P1 failed");
            emit MatchCancelled(matchId, "Timeout cancelled");
        } else {
            duel.status = MatchStatus.Refunded;
            require(paymentToken.transfer(duel.player1, refundAmount), "Refund P1 failed");
            require(paymentToken.transfer(duel.player2, refundAmount), "Refund P2 failed");
            emit MatchRefunded(matchId, refundAmount);
        }
    }

    function setTreasuryWallet(address _newTreasury) external onlyOwner {
        require(_newTreasury != address(0), "Zero address");
        emit TreasuryUpdated(treasuryWallet, _newTreasury);
        treasuryWallet = _newTreasury;
    }

    function setOracleSigner(address _newOracle) external onlyOwner {
        require(_newOracle != address(0), "Zero address");
        emit OracleSignerUpdated(oracleSigner, _newOracle);
        oracleSigner = _newOracle;
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
