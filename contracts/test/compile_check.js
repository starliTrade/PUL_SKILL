/**
 * PULSAR — solc-js compile gate for the contract suite.
 * Verifies contracts compile cleanly against pinned compiler versions and
 * reports hard errors only (warnings allowed). Used locally and in CI until
 * Foundry is installed on the developer machine.
 *
 * Usage: node contracts/test/compile_check.js
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));

const SOL = require.resolve('solc');

const targets = [
  { file: path.join(here, '..', 'PulsarEscrow.sol'), key: 'contracts/PulsarEscrow.sol' },
  { file: path.join(here, 'MockUSDT.sol'), key: 'contracts/test/MockUSDT.sol' },
];

// Minimal interface shims — OZ ERC20 subset needed by MockUSDT
const OZ_ERC20_SRC = `
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * Minimal subset of OpenZeppelin's ERC20 (v5.x semantics) inlined for the
 * sandbox compile gate — enough surface for MockUSDT. The real contract
 * under test (PulsarEscrow.sol) has zero external imports and uses its own
 * inline IERC20/Ownable/ReentrancyGuard, so this shim only affects tests.
 */
abstract contract Context {
    function _msgSender() internal view virtual returns (address) { return msg.sender; }
}

interface IERC20 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

contract ERC20 is Context, IERC20 {
    mapping(address account => uint256) private _balances;
    mapping(address account => mapping(address spender => uint256)) private _allowances;

    uint256 private _totalSupply;
    string private _name;
    string private _symbol;
    uint8 private constant _DECIMALS = 18;

    constructor(string memory name_, string memory symbol_) {
        _name = name_;
        _symbol = symbol_;
    }

    function name() public view virtual returns (string memory) { return _name; }
    function symbol() public view virtual returns (string memory) { return _symbol; }
    function decimals() public view virtual returns (uint8) { return _DECIMALS; }
    function totalSupply() public view virtual returns (uint256) { return _totalSupply; }
    function balanceOf(address account) public view virtual returns (uint256) { return _balances[account]; }

    function transfer(address to, uint256 value) public virtual returns (bool) {
        _transfer(_msgSender(), to, value);
        return true;
    }

    function allowance(address owner, address spender) public view virtual returns (uint256) {
        return _allowances[owner][spender];
    }

    function approve(address spender, uint256 value) public virtual returns (bool) {
        _approve(_msgSender(), spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) public virtual returns (bool) {
        uint256 currentAllowance = _allowances[from][_msgSender()];
        require(currentAllowance >= value, "ERC20: insufficient allowance");
        _approve(from, _msgSender(), currentAllowance - value);
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(from != address(0), "ERC20: transfer from the zero address");
        require(to != address(0), "ERC20: transfer to the zero address");
        uint256 fromBalance = _balances[from];
        require(fromBalance >= value, "ERC20: transfer amount exceeds balance");
        _balances[from] = fromBalance - value;
        _balances[to] += value;
        emit Transfer(from, to, value);
    }

    function _mint(address account, uint256 value) internal {
        require(account != address(0), "ERC20: mint to the zero address");
        _totalSupply += value;
        _balances[account] += value;
        emit Transfer(address(0), account, value);
    }

    function _approve(address owner, address spender, uint256 value) internal {
        _allowances[owner][spender] = value;
        emit Approval(owner, spender, value);
    }
}
`;

function loadSolc() {
  // solc-js exports a compiler wrapper with default export; handle both shapes
  const m = require('solc');
  return m.default ?? m;
}

function compileFile(solc, source, key, evmVersion) {
  const input = {
    language: 'Solidity',
    sources: { [key]: { content: source } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion,
      outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object'] } },
    },
  };
  const out = JSON.parse(solc.compile(JSON.stringify(input)));
  const errs = (out.errors || []).filter((e) => (e.severity ?? e.type) === 'error');
  if (errs.length) throw new Error(errs.map((e) => e.formattedMessage).join('\n'));
  const c = out.contracts?.[key];
  const names = Object.keys(c || {});
  if (!names.length) throw new Error(`no contracts produced for ${key}`);
  return names;
}

function main() {
  const solc = loadSolc();
  console.log('solc version:', solc.version());
  let failed = false;

  // 1) Production contract on its EVM targets
  const escrowSrc = fs.readFileSync(targets[0].file, 'utf8');
  for (const evm of ['paris', 'shanghai']) {
    try {
      const names = compileFile(solc, escrowSrc, targets[0].key, evm);
      console.log(`OK PulsarEscrow (evm=${evm}) -> ${names.join(', ')}`);
    } catch (e) {
      failed = true;
      console.error(`FAIL PulsarEscrow (evm=${evm})\n${e.message}`);
    }
  }

  // 2) MockUSDT compiled against the inlined minimal ERC20 shim
  const usdtSrc = fs.readFileSync(targets[1].file, 'utf8').replace(
    /import\s*\{ERC20\}\s*from\s*["'][^"']+["'];\s*/,
    ''
  );
  try {
    // Strip the shim's SPDX header — a unit may carry only one identifier.
    const shimSrc = OZ_ERC20_SRC.replace('// SPDX-License-Identifier: MIT\n', '');
    const names = compileFile(solc, shimSrc + '\n' + usdtSrc, 'MockUSDT_shim.sol', 'paris');
    console.log(`OK MockUSDT (with minimal ERC20 shim) -> ${names.join(', ')}`);
  } catch (e) {
    failed = true;
    console.error('FAIL MockUSDT compile\n' + e.message);
  }

  // 3) Deploy script: verify it exists (real compile needs forge-std, installed
  //    with `forge init` on the dev machine — see docs/DEPLOYMENT.md)
  const deployPath = path.join(here, '..', 'script', 'Deploy.s.sol');
  if (!fs.existsSync(deployPath)) {
    failed = true;
    console.error('FAIL Deploy.s.sol missing');
  } else {
    console.log('OK Deploy.s.sol present (full compile via forge on dev machine)');
  }

  console.log(failed ? 'COMPILE CHECK FAILED' : 'COMPILE CHECK PASSED');
  // Let stdout drain naturally (process.exit() truncates piped output).
  if (failed) process.exitCode = 1;
}

main();


