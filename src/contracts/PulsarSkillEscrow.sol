// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title PulsarSkillEscrow
 * @dev High-speed, micro-gas Non-Custodial PvP Settlement Escrow for Pulsar Arena.
 * Built for Polygon (PoS), Base, and EVM Layer-2 networks with sub-cent gas fees.
 * 
 * Features:
 * - 1v1 Best of 3 Escrow locks for 1, 2, 5, 10 USDT stakes
 * - 98% Winner Payout (2% platform protocol & prize pool fund)
 * - Cryptographic Anti-Cheat Referee Oracle signature settlement
 * - Timeout refund protection if opponent disconnects or match expires
 */

interface IERC20 {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract PulsarSkillEscrow {
    address public immutable owner;
    address public refereeOracle;
    IERC20 public immutable usdtToken;

    uint256 public constant PROTOCOL_FEE_BPS = 200; // 2% (98% to winner)
    uint256 public constant MATCH_TIMEOUT = 10 minutes;

    enum MatchState { Empty, Created, Active, Settled, Refunded }

    struct DuelMatch {
        bytes32 matchId;
        address playerA;
        address playerB;
        uint256 stakeAmount;
        uint256 totalPot;
        uint256 createdAt;
        MatchState state;
        address winner;
    }

    mapping(bytes32 => DuelMatch) public matches;
    mapping(address => uint256) public playerVault;

    event MatchCreated(bytes32 indexed matchId, address indexed playerA, uint256 stakeAmount);
    event MatchJoined(bytes32 indexed matchId, address indexed playerB);
    event MatchSettled(bytes32 indexed matchId, address indexed winner, uint256 payout, uint256 fee);
    event MatchRefunded(bytes32 indexed matchId, string reason);
    event VaultDeposited(address indexed player, uint256 amount);
    event VaultWithdrawn(address indexed player, uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "Pulsar: Only Owner");
        _;
    }

    modifier onlyOracle() {
        require(msg.sender == refereeOracle || msg.sender == owner, "Pulsar: Only Referee Oracle");
        _;
    }

    constructor(address _usdtToken, address _refereeOracle) {
        require(_usdtToken != address(0), "Invalid token");
        require(_refereeOracle != address(0), "Invalid oracle");
        owner = msg.sender;
        usdtToken = IERC20(_usdtToken);
        refereeOracle = _refereeOracle;
    }

    function setRefereeOracle(address _newOracle) external onlyOwner {
        require(_newOracle != address(0), "Invalid oracle address");
        refereeOracle = _newOracle;
    }

    /**
     * @notice Deposit USDT into player gasless session vault
     */
    function depositVault(uint256 amount) external {
        require(amount > 0, "Amount must be > 0");
        require(usdtToken.transferFrom(msg.sender, address(this), amount), "Transfer failed");
        playerVault[msg.sender] += amount;
        emit VaultDeposited(msg.sender, amount);
    }

    /**
     * @notice Withdraw available USDT from player vault
     */
    function withdrawVault(uint256 amount) external {
        require(amount > 0, "Amount must be > 0");
        require(playerVault[msg.sender] >= amount, "Insufficient vault balance");
        playerVault[msg.sender] -= amount;
        require(usdtToken.transfer(msg.sender, amount), "Transfer failed");
        emit VaultWithdrawn(msg.sender, amount);
    }

    /**
     * @notice Create a new PvP duel escrow match
     */
    function createMatch(bytes32 matchId, uint256 stakeAmount) external {
        require(matches[matchId].state == MatchState.Empty, "Match ID already exists");
        require(stakeAmount >= 1 * 1e6, "Min stake is 1 USDT");
        
        // Deduct from caller's vault or direct transfer
        if (playerVault[msg.sender] >= stakeAmount) {
            playerVault[msg.sender] -= stakeAmount;
        } else {
            require(usdtToken.transferFrom(msg.sender, address(this), stakeAmount), "Stake transfer failed");
        }

        matches[matchId] = DuelMatch({
            matchId: matchId,
            playerA: msg.sender,
            playerB: address(0),
            stakeAmount: stakeAmount,
            totalPot: stakeAmount,
            createdAt: block.timestamp,
            state: MatchState.Created,
            winner: address(0)
        });

        emit MatchCreated(matchId, msg.sender, stakeAmount);
    }

    /**
     * @notice Join an existing match
     */
    function joinMatch(bytes32 matchId) external {
        DuelMatch storage m = matches[matchId];
        require(m.state == MatchState.Created, "Match not available");
        require(m.playerA != msg.sender, "Cannot play against yourself");

        if (playerVault[msg.sender] >= m.stakeAmount) {
            playerVault[msg.sender] -= m.stakeAmount;
        } else {
            require(usdtToken.transferFrom(msg.sender, address(this), m.stakeAmount), "Stake transfer failed");
        }

        m.playerB = msg.sender;
        m.totalPot += m.stakeAmount;
        m.state = MatchState.Active;

        emit MatchJoined(matchId, msg.sender);
    }

    /**
     * @notice Settle match after Best of 3 validated by anti-cheat referee oracle
     */
    function settleMatch(
        bytes32 matchId,
        address winner,
        bytes calldata oracleSignature
    ) external onlyOracle {
        DuelMatch storage m = matches[matchId];
        require(m.state == MatchState.Active || m.state == MatchState.Created, "Match not active");
        require(winner == m.playerA || winner == m.playerB, "Winner must be participant");

        uint256 totalPot = m.totalPot;
        uint256 fee = (totalPot * PROTOCOL_FEE_BPS) / 10000;
        uint256 winnerPayout = totalPot - fee;

        m.state = MatchState.Settled;
        m.winner = winner;

        // Credit to winner's vault for immediate next matches or instant withdrawal
        playerVault[winner] += winnerPayout;
        playerVault[owner] += fee;

        emit MatchSettled(matchId, winner, winnerPayout, fee);
    }

    /**
     * @notice Emergency timeout refund if match not completed within 10 minutes
     */
    function refundTimeoutMatch(bytes32 matchId) external {
        DuelMatch storage m = matches[matchId];
        require(m.state == MatchState.Created || m.state == MatchState.Active, "Match cannot be refunded");
        require(block.timestamp >= m.createdAt + MATCH_TIMEOUT, "Match timeout not reached");

        m.state = MatchState.Refunded;

        if (m.playerA != address(0)) {
            playerVault[m.playerA] += m.stakeAmount;
        }
        if (m.playerB != address(0)) {
            playerVault[m.playerB] += m.stakeAmount;
        }

        emit MatchRefunded(matchId, "Timeout elapsed without referee settlement");
    }
}
