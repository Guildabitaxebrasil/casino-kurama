// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

// ─── Interfaces (com nomes próprios para não colidir com os imports) ───

interface IKurPairCumulative {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112, uint112, uint32);
    function price0CumulativeLast() external view returns (uint256);
    function price1CumulativeLast() external view returns (uint256);
}

interface IKurAggregatorV3 {
    function decimals() external view returns (uint8);
    function latestRoundData() external view returns (
        uint80 roundId, int256 answer, uint256 startedAt,
        uint256 updatedAt, uint80 answeredInRound
    );
}

/// @title KurOracle — oráculo de preço com TWAP da DEX + fallback
/// @notice Combina duas fontes de preço:
///
///         1. **Primária:** um feed `AggregatorV3` (KurPriceFeed) publicado
///            pelos nós oráculo. É usado enquanto o dado for **fresco**
///            (`block.timestamp - updatedAt <= maxAge`).
///         2. **Fallback (TWAP):** média ponderada no tempo do preço do par
///            AMM do DEX (`KurPair`), que continua funcionando se os nós
///            oráculo caírem ou o feed ficar obsoleto.
///
///         O preço é sempre normalizado em **8 decimais** e o par é sempre
///         lido como "preço do `token0` em unidades do `token1`".
contract KurOracle {
    uint256 private constant Q112 = 2**112;
    uint256 private constant ONE_8 = 1e8;

    address public owner;
    /// @notice Par do DEX usado como fonte TWAP.
    address public immutable pair;
    address public immutable token0;
    address public immutable token1;
    /// @notice Feed primário (pode ser address(0) para usar só a TWAP).
    address public feed;
    /// @notice Janela mínima (segundos) entre duas chamadas de `update()`.
    uint32 public period;
    /// @notice Idade máxima (segundos) aceita para o preço do feed.
    uint256 public maxAge;

    uint256 public price0CumulativeLast;
    uint256 public price1CumulativeLast;
    uint32 public blockTimestampLast;
    /// @notice TWAP do preço do token0 em token1 (UQ112x112).
    uint256 public price0Average;
    /// @notice TWAP do preço do token1 em token0 (UQ112x112).
    uint256 public price1Average;
    /// @notice True após o primeiro `update()` (TWAP consultável).
    bool public twapReady;

    event TwapUpdated(uint256 price0Average, uint256 price1Average, uint32 timestamp);
    event FeedUpdated(address feed);
    event MaxAgeUpdated(uint256 maxAge);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurOracle: NOT_OWNER');
        _;
    }

    constructor(address _pair, address _feed, uint32 _period, uint256 _maxAge) {
        require(_pair != address(0), 'KurOracle: ZERO_PAIR');
        owner = msg.sender;
        pair = _pair;
        token0 = IKurPairCumulative(_pair).token0();
        token1 = IKurPairCumulative(_pair).token1();
        feed = _feed;
        period = _period;
        maxAge = _maxAge;

        (uint256 c0, uint256 c1, uint32 ts) = _currentCumulativePrices();
        price0CumulativeLast = c0;
        price1CumulativeLast = c1;
        blockTimestampLast = ts;
    }

    // ─── TWAP ────────────────────────────────────────────────────

    /// @notice Atualiza a TWAP a partir dos acumuladores do par.
    /// @dev Deve ser chamada periodicamente (por um keeper/nó) para manter a
    ///      janela de observação curta.
    function update() external {
        (uint256 c0, uint256 c1, uint32 ts) = _currentCumulativePrices();
        uint32 elapsed = ts - blockTimestampLast;
        require(elapsed >= period, 'KurOracle: PERIOD_NOT_ELAPSED');

        price0Average = (c0 - price0CumulativeLast) / elapsed;
        price1Average = (c1 - price1CumulativeLast) / elapsed;
        price0CumulativeLast = c0;
        price1CumulativeLast = c1;
        blockTimestampLast = ts;
        twapReady = true;
        emit TwapUpdated(price0Average, price1Average, ts);
    }

    /// @notice Converte `amountIn` de `tokenIn` para o outro token usando a TWAP.
    function consult(address tokenIn, uint256 amountIn) external view returns (uint256 amountOut) {
        require(twapReady, 'KurOracle: TWAP_NOT_READY');
        if (tokenIn == token0) {
            amountOut = (price0Average * amountIn) >> 112;
        } else {
            require(tokenIn == token1, 'KurOracle: UNKNOWN_TOKEN');
            amountOut = (price1Average * amountIn) >> 112;
        }
    }

    // ─── Preço agregado (feed com fallback TWAP) ─────────────────

    /// @notice Preço do `token0` em unidades do `token1`, com 8 decimais.
    /// @return price Preço normalizado em 8 decimais.
    /// @return fromFeed True se veio do feed (fresco), False se veio da TWAP.
    function getPrice() external view returns (uint256 price, bool fromFeed) {
        if (feed != address(0)) {
            try IKurAggregatorV3(feed).latestRoundData() returns (
                uint80, int256 answer, uint256, uint256 updatedAt, uint80
            ) {
                if (answer > 0 && updatedAt > 0 && updatedAt <= block.timestamp
                        && block.timestamp - updatedAt <= maxAge) {
                    return (_scale8(uint256(answer), IKurAggregatorV3(feed).decimals()), true);
                }
            } catch {
                // Feed sem dados (ou revertendo): cai no fallback TWAP.
            }
        }
        require(twapReady, 'KurOracle: NO_PRICE');
        price = (price0Average * ONE_8) >> 112;
    }

    /// @notice Preço do feed (se houver), sem fallback — para diagnóstico.
    function feedPrice() external view returns (uint256 price, uint256 updatedAt, bool fresh) {
        if (feed == address(0)) {
            return (0, 0, false);
        }
        try IKurAggregatorV3(feed).latestRoundData() returns (
            uint80, int256 answer, uint256, uint256 ts, uint80
        ) {
            if (answer <= 0) {
                return (0, ts, false);
            }
            return (_scale8(uint256(answer), IKurAggregatorV3(feed).decimals()), ts,
                    ts <= block.timestamp && block.timestamp - ts <= maxAge);
        } catch {
            return (0, 0, false);
        }
    }

    // ─── Administração ───────────────────────────────────────────

    function setFeed(address newFeed) external onlyOwner {
        feed = newFeed;
        emit FeedUpdated(newFeed);
    }

    function setMaxAge(uint256 newMaxAge) external onlyOwner {
        maxAge = newMaxAge;
        emit MaxAgeUpdated(newMaxAge);
    }

    // ─── Internos ───────────────────────────────────────────────

    /// @dev Cumulativos do par extrapolados até `block.timestamp` (estilo
    ///      UniswapV2OracleLibrary.currentCumulativePrices).
    function _currentCumulativePrices() private view returns (
        uint256 c0, uint256 c1, uint32 blockTimestamp
    ) {
        blockTimestamp = uint32(block.timestamp);
        c0 = IKurPairCumulative(pair).price0CumulativeLast();
        c1 = IKurPairCumulative(pair).price1CumulativeLast();
        (uint112 r0, uint112 r1, uint32 pairTs) = IKurPairCumulative(pair).getReserves();
        if (pairTs != blockTimestamp && r0 != 0 && r1 != 0) {
            uint32 timeElapsed = blockTimestamp - pairTs;
            c0 += (uint256(r1) * Q112 / uint256(r0)) * timeElapsed;
            c1 += (uint256(r0) * Q112 / uint256(r1)) * timeElapsed;
        }
    }

    /// @dev Normaliza um preço de `decimals` para 8 decimais.
    function _scale8(uint256 value, uint8 decimals_) private pure returns (uint256) {
        if (decimals_ == 8) {
            return value;
        }
        if (decimals_ < 8) {
            return value * (10**(8 - decimals_));
        }
        return value / (10**(decimals_ - 8));
    }
}
