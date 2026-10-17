// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title UQ112x112 — aritmética de ponto fixo 112.112
/// @notice Usada pelos acumuladores de preço do KurPair (TWAP estilo Uniswap V2).
///         Um preço é representado como `valor * 2**112`.
library UQ112x112 {
    uint224 internal constant Q112 = 2**112;

    /// @notice Codifica um uint112 como UQ112x112 (multiplica por 2**112).
    function encode(uint112 y) internal pure returns (uint224 z) {
        z = uint224(y) * Q112;
    }

    /// @notice Divide um UQ112x112 por um uint112 (mantém a escala 2**112).
    function uqdiv(uint224 x, uint112 y) internal pure returns (uint224 z) {
        z = x / uint224(y);
    }
}
