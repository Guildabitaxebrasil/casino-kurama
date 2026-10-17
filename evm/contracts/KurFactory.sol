// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./KurPair.sol";

/// @title KurFactory — fábrica de pares de liquidez (DEX)
/// @notice Cria e registra pools KurPair para qualquer par de tokens ERC-20.
contract KurFactory {
    mapping(address => mapping(address => address)) public getPair;
    address[] public allPairs;

    event PairCreated(address indexed token0, address indexed token1,
                      address pair, uint256 totalPairs);

    function allPairsLength() external view returns (uint256) {
        return allPairs.length;
    }

    function createPair(address tokenA, address tokenB) external returns (address pair) {
        require(tokenA != tokenB, 'KurFactory: IDENTICAL');
        require(tokenA != address(0) && tokenB != address(0), 'KurFactory: ZERO_ADDRESS');
        require(getPair[tokenA][tokenB] == address(0), 'KurFactory: PAIR_EXISTS');

        (address token0, address token1) = tokenA < tokenB
            ? (tokenA, tokenB) : (tokenB, tokenA);

        KurPair newPair = new KurPair();
        newPair.initialize(token0, token1);
        pair = address(newPair);

        getPair[token0][token1] = pair;
        getPair[token1][token0] = pair;
        allPairs.push(pair);

        emit PairCreated(token0, token1, pair, allPairs.length);
    }
}
