// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./KurPair.sol";

interface IKurERC20Full {
    function transferFrom(address, address, uint256) external returns (bool);
    function transfer(address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
}

interface IKurFactory {
    function getPair(address, address) external view returns (address);
    function createPair(address, address) external returns (address);
}

/// @title KurRouter — roteador de liquidez e swaps do DEX da KuramaChain
contract KurRouter {
    address public factory;

    event LiquidityAdded(address indexed provider, address pair, uint256 amountA, uint256 amountB);
    event SwapExecuted(address indexed sender, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);

    constructor(address _factory) {
        factory = _factory;
    }

    function pairFor(address tokenA, address tokenB) public view returns (address) {
        return IKurFactory(factory).getPair(tokenA, tokenB);
    }

    /// @notice Adiciona liquidez a um par existente.
    function addLiquidity(address tokenA, address tokenB, uint256 amountA,
                          uint256 amountB, address to) external returns (uint256 liquidity) {
        address pair = pairFor(tokenA, tokenB);
        require(pair != address(0), 'KurRouter: NO_PAIR');
        require(amountA > 0 && amountB > 0, 'KurRouter: ZERO_AMOUNT');
        IKurERC20Full(tokenA).transferFrom(msg.sender, pair, amountA);
        IKurERC20Full(tokenB).transferFrom(msg.sender, pair, amountB);
        liquidity = KurPair(pair).mint(to);
        emit LiquidityAdded(msg.sender, pair, amountA, amountB);
    }

    /// @notice Swap exato de entrada por saída (path de 2 tokens).
    function swapExactTokensForTokens(uint256 amountIn, uint256 amountOutMin,
                                      address[] calldata path, address to)
        external returns (uint256 amountOut)
    {
        require(path.length == 2, 'KurRouter: INVALID_PATH');
        require(amountIn > 0, 'KurRouter: ZERO_IN');
        address pair = pairFor(path[0], path[1]);
        require(pair != address(0), 'KurRouter: NO_PAIR');

        KurPair p = KurPair(pair);
        (uint112 r0, uint112 r1, ) = p.getReserves();
        address t0 = p.token0();
        (uint256 reserveIn, uint256 reserveOut) = path[0] == t0
            ? (uint256(r0), uint256(r1)) : (uint256(r1), uint256(r0));

        uint256 amountInWithFee = amountIn * 997;
        amountOut = (amountInWithFee * reserveOut) / (reserveIn * 1000 + amountInWithFee);
        require(amountOut >= amountOutMin, 'KurRouter: SLIPPAGE');
        require(amountOut < reserveOut, 'KurRouter: INSUFFICIENT_LIQUIDITY');

        IKurERC20Full(path[0]).transferFrom(msg.sender, pair, amountIn);
        (uint256 amount0Out, uint256 amount1Out) = path[0] == t0
            ? (uint256(0), amountOut) : (amountOut, uint256(0));
        p.swap(amount0Out, amount1Out, to);
        emit SwapExecuted(msg.sender, path[0], path[1], amountIn, amountOut);
    }
}
