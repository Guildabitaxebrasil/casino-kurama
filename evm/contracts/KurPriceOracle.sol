// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./KurPriceFeed.sol";

/// @title KurPriceOracle — registro de feeds de preço por ativo (Fase 4)
/// @notice Mapeia `asset => feed AggregatorV3` (os `KurPriceFeed` da Fase 3)
///         e normaliza o preço em **18 decimais** — a moeda-base usada pelo
///         mercado de empréstimos (`KurLendingPool`).
///
///         Preço **obsoleto reverte**: o pool nunca calcula colateral com um
///         preço velho. Com `maxAge == 0` a checagem de idade é desativada.
contract KurPriceOracle {
    uint8 public constant BASE_DECIMALS = 18;

    address public owner;
    /// @notice Endereço do feed AggregatorV3 de cada ativo (0 = não registrado).
    mapping(address => address) public feeds;
    /// @notice Ativos que já entraram na lista (mesmo sem feed no momento).
    mapping(address => bool) public isRegistered;
    address[] public assets;
    /// @notice Idade máxima (segundos) aceita para o preço (0 = sem checagem).
    uint256 public maxAge;

    event AssetFeedUpdated(address indexed asset, address feed);
    event MaxAgeUpdated(uint256 maxAge);
    event OwnershipTransferred(address indexed from, address indexed to);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurPriceOracle: NOT_OWNER');
        _;
    }

    constructor(uint256 _maxAge) {
        owner = msg.sender;
        maxAge = _maxAge;
    }

    // ─── Registro de feeds ───────────────────────────────────────

    /// @notice Registra (ou remove, com `feed == address(0)`) o feed de um ativo.
    /// @dev O ativo entra na lista (`assets`) uma única vez — remover e
    ///      registrar de novo não o duplica.
    function setAssetFeed(address asset, address feed) external onlyOwner {
        require(asset != address(0), 'KurPriceOracle: ZERO_ASSET');
        if (!isRegistered[asset]) {
            isRegistered[asset] = true;
            assets.push(asset);
        }
        feeds[asset] = feed;
        emit AssetFeedUpdated(asset, feed);
    }

    function assetsLength() external view returns (uint256) {
        return assets.length;
    }

    // ─── Preço ───────────────────────────────────────────────────

    /// @notice Preço do ativo em 18 decimais (ex.: 1 USD = 1e18).
    /// @dev Reverte se o ativo não tem feed, se o preço for inválido ou
    ///      obsoleto — nunca devolve um preço velho.
    function getAssetPrice(address asset) public view returns (uint256) {
        address feed = feeds[asset];
        require(feed != address(0), 'KurPriceOracle: NO_FEED');
        (, int256 answer, , uint256 updatedAt, ) =
            AggregatorV3Interface(feed).latestRoundData();
        require(answer > 0, 'KurPriceOracle: BAD_PRICE');
        require(updatedAt != 0 && updatedAt <= block.timestamp,
                'KurPriceOracle: BAD_TIMESTAMP');
        if (maxAge != 0) {
            require(block.timestamp - updatedAt <= maxAge,
                    'KurPriceOracle: STALE_PRICE');
        }
        return _scale18(uint256(answer), AggregatorV3Interface(feed).decimals());
    }

    /// @notice Preço e se ele está dentro de `maxAge` (diagnóstico, não reverte).
    function assetPriceInfo(address asset) external view returns (
        uint256 price, uint256 updatedAt, bool fresh
    ) {
        address feed = feeds[asset];
        if (feed == address(0)) {
            return (0, 0, false);
        }
        try AggregatorV3Interface(feed).latestRoundData() returns (
            uint80, int256 answer, uint256, uint256 ts, uint80
        ) {
            if (answer <= 0) {
                return (0, ts, false);
            }
            bool fresh_ = ts != 0 && ts <= block.timestamp
                && (maxAge == 0 || block.timestamp - ts <= maxAge);
            return (_scale18(uint256(answer),
                             AggregatorV3Interface(feed).decimals()), ts, fresh_);
        } catch {
            return (0, 0, false);
        }
    }

    // ─── Administração ───────────────────────────────────────────

    function setMaxAge(uint256 newMaxAge) external onlyOwner {
        maxAge = newMaxAge;
        emit MaxAgeUpdated(newMaxAge);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), 'KurPriceOracle: ZERO_ADDRESS');
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ─── Internos ────────────────────────────────────────────────

    /// @dev Normaliza um preço de `decimals` para 18 decimais.
    function _scale18(uint256 value, uint8 decimals_) private pure returns (uint256) {
        if (decimals_ == BASE_DECIMALS) {
            return value;
        }
        if (decimals_ < BASE_DECIMALS) {
            return value * (10**(BASE_DECIMALS - decimals_));
        }
        return value / (10**(decimals_ - BASE_DECIMALS));
    }
}
