// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * Token variants the escrow must survive (audit CT1).
 *
 * The contract inlines a SafeERC20-equivalent because real USDT does not return
 * a bool from `transfer`. That code path had never been exercised: MockUSDT is
 * an OpenZeppelin ERC20 that always returns true, so the branch that exists
 * *because* of USDT was the one branch with no coverage.
 *
 * Each variant below is a specific real-world failure mode:
 *   NoReturnUSDT      - Tether: no return value at all
 *   FalseReturnUSDT   - returns false WITHOUT reverting (a silent failure)
 *   FeeOnTransferUSDT - takes a cut in flight (the pool is not the nominal sum)
 *   ReentrantUSDT     - calls back into the escrow during a transfer
 *
 * They share storage and `_move` but each declares its own `transfer` /
 * `transferFrom` signature: a variant cannot inherit the no-return signature and
 * then add a return type.
 */

abstract contract TokenBase {
    string public name;
    string public symbol;
    uint8 public decimals;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(string memory _name, string memory _symbol, uint8 _decimals) {
        name = _name;
        symbol = _symbol;
        decimals = _decimals;
    }

    function faucet(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function _move(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "token: balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _burn(address from, uint256 amount) internal {
        balanceOf[from] -= amount;
        totalSupply -= amount;
        emit Transfer(from, address(0), amount);
    }

    function _spendAllowance(address from, address spender, uint256 amount) internal {
        require(allowance[from][spender] >= amount, "token: allowance");
        allowance[from][spender] -= amount;
    }
}

/// Minimal ERC-20 whose transfer functions return NOTHING, like mainnet USDT.
contract NoReturnUSDT is TokenBase {
    constructor() TokenBase("No-Return USD", "nrUSDT", 6) {}

    // NOTE: no return value. This is the entire point of the variant.
    function transfer(address to, uint256 amount) external {
        _move(msg.sender, to, amount);
    }

    function transferFrom(address from, address to, uint256 amount) external {
        _spendAllowance(from, msg.sender, amount);
        _move(from, to, amount);
    }
}

/// Returns `false` from transfer/transferFrom WITHOUT reverting.
contract FalseReturnUSDT is TokenBase {
    bool public failTransfers = true;

    constructor() TokenBase("False-Return USD", "frUSDT", 6) {}

    function setFailTransfers(bool value) external {
        failTransfers = value;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        if (failTransfers) {
            return false; // silent failure: no revert, no movement
        }
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (failTransfers) {
            return false;
        }
        _spendAllowance(from, msg.sender, amount);
        _move(from, to, amount);
        return true;
    }
}

/// Takes a cut in flight, so the received amount is less than the nominal one.
contract FeeOnTransferUSDT is TokenBase {
    uint256 public constant FEE_BPS = 100; // 1%

    constructor() TokenBase("Fee-On-Transfer USD", "fotUSDT", 6) {}

    function transfer(address to, uint256 amount) external returns (bool) {
        uint256 fee = (amount * FEE_BPS) / 10_000;
        _move(msg.sender, to, amount - fee);
        _burn(msg.sender, fee);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        _spendAllowance(from, msg.sender, amount);
        uint256 fee = (amount * FEE_BPS) / 10_000;
        _move(from, to, amount - fee);
        _burn(from, fee);
        return true;
    }
}

/// Calls back into a target during a transfer, to prove `nonReentrant` holds.
///
/// It RECORDS whether the re-entry succeeded rather than requiring it: the
/// escrow's guard makes the inner call revert, and a token that insisted on
/// success would only prove that a revert propagates.
contract ReentrantUSDT is TokenBase {
    address public target;
    bytes public payload;
    bool public armed;
    bool public reentrySucceeded;
    bytes public reentryReturn;

    constructor() TokenBase("Reentrant USD", "reUSDT", 6) {}

    function arm(address _target, bytes calldata _payload) external {
        target = _target;
        payload = _payload;
        armed = true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        if (armed) {
            armed = false; // one shot, so the outer call can still complete
            (bool ok, bytes memory ret) = target.call(payload);
            reentrySucceeded = ok;
            reentryReturn = ret;
        }
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        _spendAllowance(from, msg.sender, amount);
        _move(from, to, amount);
        return true;
    }
}
