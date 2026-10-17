// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import './UQ112x112.sol';

interface IKurERC20 {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
}

/// @title KurPair — par de liquidez AMM (x*y=k)
/// @notice Pool de dois tokens com LP token ERC-20 embutido. Taxa de swap 0,3%.
///         Modelo Uniswap V2 (simplificado).
contract KurPair {
    using UQ112x112 for uint224;

    string public constant name = 'Kurama LP';
    string public constant symbol = 'KUR-LP';
    uint8 public constant decimals = 18;

    address public factory;
    address public token0;
    address public token1;

    uint112 private reserve0;
    uint112 private reserve1;
    uint32 private blockTimestampLast;

    // Acumuladores de preço (UQ112x112) consumidos pelo oráculo (TWAP).
    uint256 public price0CumulativeLast;
    uint256 public price1CumulativeLast;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    uint256 public constant MINIMUM_LIQUIDITY = 1000;

    event Mint(address indexed sender, uint256 amount0, uint256 amount1);
    event Burn(address indexed sender, uint256 amount0, uint256 amount1, address indexed to);
    event Swap(address indexed sender, uint256 amount0In, uint256 amount1In,
               uint256 amount0Out, uint256 amount1Out, address indexed to);
    event Sync(uint112 reserve0, uint112 reserve1);
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor() {
        factory = msg.sender;
    }

    function initialize(address _token0, address _token1) external {
        require(msg.sender == factory, 'KurPair: FORBIDDEN');
        token0 = _token0;
        token1 = _token1;
    }

    function getReserves() public view returns (uint112, uint112, uint32) {
        return (reserve0, reserve1, blockTimestampLast);
    }

    /// @notice Acumuladores de preço ponderados no tempo (TWAP).
    function getCumulativePrices() external view returns (uint256, uint256) {
        return (price0CumulativeLast, price1CumulativeLast);
    }

    /// @notice Adiciona liquidez. O par usa o saldo de tokens que RECEBEU
    ///         (o provedor deve transferir os tokens antes de chamar mint).
    function mint(address to) external returns (uint256 liquidity) {
        (uint112 _r0, uint112 _r1, ) = getReserves();
        uint256 bal0 = IKurERC20(token0).balanceOf(address(this));
        uint256 bal1 = IKurERC20(token1).balanceOf(address(this));
        uint256 amount0 = bal0 - _r0;
        uint256 amount1 = bal1 - _r1;

        uint256 _totalSupply = totalSupply;
        if (_totalSupply == 0) {
            liquidity = _sqrt(amount0 * amount1) - MINIMUM_LIQUIDITY;
            _mint(address(0), MINIMUM_LIQUIDITY);
        } else {
            liquidity = _min(
                amount0 * _totalSupply / _r0,
                amount1 * _totalSupply / _r1
            );
        }
        require(liquidity > 0, 'KurPair: INSUFFICIENT_LIQUIDITY_MINTED');
        _mint(to, liquidity);
        _update(bal0, bal1);
        emit Mint(msg.sender, amount0, amount1);
    }

    /// @notice Remove liquidez queimando LP tokens previamente enviados ao par.
    function burn(address to) external returns (uint256 amount0, uint256 amount1) {
        uint256 bal0 = IKurERC20(token0).balanceOf(address(this));
        uint256 bal1 = IKurERC20(token1).balanceOf(address(this));
        uint256 liquidity = balanceOf[address(this)];
        uint256 _totalSupply = totalSupply;

        amount0 = liquidity * bal0 / _totalSupply;
        amount1 = liquidity * bal1 / _totalSupply;
        require(amount0 > 0 && amount1 > 0, 'KurPair: INSUFFICIENT_LIQUIDITY_BURNED');

        _burn(address(this), liquidity);
        IKurERC20(token0).transfer(to, amount0);
        IKurERC20(token1).transfer(to, amount1);

        _update(
            IKurERC20(token0).balanceOf(address(this)),
            IKurERC20(token1).balanceOf(address(this))
        );
        emit Burn(msg.sender, amount0, amount1, to);
    }

    /// @notice Executa um swap. O chamador deve transferir o token de entrada
    ///         para o par ANTES de chamar swap.
    function swap(uint256 amount0Out, uint256 amount1Out, address to) external {
        require(amount0Out > 0 || amount1Out > 0, 'KurPair: INSUFFICIENT_OUTPUT');
        (uint112 _r0, uint112 _r1, ) = getReserves();
        require(amount0Out < _r0 && amount1Out < _r1, 'KurPair: INSUFFICIENT_LIQUIDITY');

        if (amount0Out > 0) IKurERC20(token0).transfer(to, amount0Out);
        if (amount1Out > 0) IKurERC20(token1).transfer(to, amount1Out);

        uint256 bal0 = IKurERC20(token0).balanceOf(address(this));
        uint256 bal1 = IKurERC20(token1).balanceOf(address(this));

        uint256 amount0In = bal0 > _r0 - amount0Out ? bal0 - (_r0 - amount0Out) : 0;
        uint256 amount1In = bal1 > _r1 - amount1Out ? bal1 - (_r1 - amount1Out) : 0;
        require(amount0In > 0 || amount1In > 0, 'KurPair: INSUFFICIENT_INPUT');

        // Invariante x*y=k com taxa de 0,3%
        uint256 bal0Adjusted = bal0 * 1000 - amount0In * 3;
        uint256 bal1Adjusted = bal1 * 1000 - amount1In * 3;
        require(
            bal0Adjusted * bal1Adjusted >= uint256(_r0) * uint256(_r1) * 1000 * 1000,
            'KurPair: K'
        );

        _update(bal0, bal1);
        emit Swap(msg.sender, amount0In, amount1In, amount0Out, amount1Out, to);
    }

    // ─── LP token (ERC-20) ───────────────────────────────────────

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, 'KurPair: ALLOWANCE');
        if (allowed != type(uint256).max) allowance[from][msg.sender] = allowed - value;
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(balanceOf[from] >= value, 'KurPair: BALANCE');
        balanceOf[from] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }

    function _mint(address to, uint256 value) internal {
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }

    function _burn(address from, uint256 value) internal {
        balanceOf[from] -= value;
        totalSupply -= value;
        emit Transfer(from, address(0), value);
    }

    // ─── Internos ────────────────────────────────────────────────

    function _update(uint256 bal0, uint256 bal1) private {
        require(bal0 <= type(uint112).max && bal1 <= type(uint112).max, 'KurPair: OVERFLOW');
        uint32 blockTimestamp = uint32(block.timestamp);
        uint32 timeElapsed = blockTimestamp - blockTimestampLast;

        // Acumula o preço pelo tempo decorrido (base da TWAP do oráculo).
        if (timeElapsed > 0 && reserve0 != 0 && reserve1 != 0) {
            price0CumulativeLast += uint256(
                UQ112x112.encode(uint112(bal1)).uqdiv(uint112(bal0))
            ) * timeElapsed;
            price1CumulativeLast += uint256(
                UQ112x112.encode(uint112(bal0)).uqdiv(uint112(bal1))
            ) * timeElapsed;
        }

        reserve0 = uint112(bal0);
        reserve1 = uint112(bal1);
        blockTimestampLast = blockTimestamp;
        emit Sync(reserve0, reserve1);
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }

    function _sqrt(uint256 y) private pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }
}
