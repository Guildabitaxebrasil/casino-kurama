// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./KurScaledToken.sol";

// ─── Interfaces mínimas (nomes próprios, como nos contratos da Fase 3) ───

interface IKurERC20Lending {
    function decimals() external view returns (uint8);
    function symbol() external view returns (string memory);
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
}

interface IKurScaledTokenLite {
    function index() external view returns (uint256);
    function balanceOf(address) external view returns (uint256);
    function scaledBalanceOf(address) external view returns (uint256);
    function scaledTotalSupply() external view returns (uint256);
    function totalSupply() external view returns (uint256);
    function setIndex(uint256) external;
    function mint(address, uint256) external returns (uint256);
    function burn(address, uint256) external returns (uint256);
}

interface IKurPriceOracleLite {
    function getAssetPrice(address asset) external view returns (uint256);
}

/// @title KurLendingPool — mercado de empréstimos (fork do Aave V2)
/// @notice Depósito (colateral que rende juros via **aToken**), empréstimo a
///         taxa variável (**debtToken**) e **liquidação** de posições
///         subcolateralizadas, com o preço vindo do `KurPriceOracle`
///         (Fase 3/4).
///
///         Modelo de juros (taxa **por segundo**, em ray):
///
///             u          = dívida / (dívida + liquidez disponível)
///             borrowRate = base + slope1*u/optimal            (u <= optimal)
///                        = base + slope1 + slope2*(u-optimal)/(1-optimal)
///             liquidityRate = borrowRate * u * (1 - reserveFactor)
///
///         Os juros são capitalizados de forma **linear** no intervalo entre
///         dois accruals (`índice *= 1 + taxa*Δt`), não compostos como no Aave.
///
///         Desvios conscientes do Aave V2 (mercado único, sem `referralCode`):
///         - `borrow` só tem taxa **variável** (sem `interestRateMode`);
///         - `liquidationCall` não recebe `receiveAToken` (paga em ativo);
///         - `aToken`/`debtToken` são instâncias do mesmo `KurScaledToken`.
///
///         Preços em 18 decimais (`KurPriceOracle`): todo valor é
///         `amount * price / 10**decimals do ativo`.
contract KurLendingPool {
    uint256 public constant RAY = 1e27;
    uint256 public constant WAD = 1e18;
    uint256 public constant BPS = 10000;
    uint256 public constant SECONDS_PER_YEAR = 365 days;

    struct ReserveData {
        address aToken;
        address debtToken;
        uint8 decimals;
        uint16 ltv;                  // bps — quanto do colateral pode ser emprestado
        uint16 liquidationThreshold; // bps — acima disso a posição fica liquidável
        uint16 liquidationBonus;     // multiplicador em bps (10500 = 1,05 = +5%)
        uint16 reserveFactor;        // bps — parte dos juros que vai ao protocolo
        uint256 liquidityIndex;      // ray — rendimento dos depositantes
        uint256 borrowIndex;         // ray — juros da dívida
        uint40 lastUpdateTimestamp;
        bool active;
        bool borrowingEnabled;
    }

    struct AccountData {
        uint256 collateral;         // valor do colateral (18 decimais)
        uint256 debt;               // valor da dívida (18 decimais)
        uint256 weightedLtv;        // Σ valor * ltv
        uint256 weightedThreshold;  // Σ valor * liquidationThreshold
    }

    address public owner;
    address public priceOracle;
    /// @notice Taxas em ray por segundo (derivadas das APR do config).
    uint256 public baseRate;
    uint256 public slope1;
    uint256 public slope2;
    /// @notice Utilização ótima (ray, ex.: 0.8e27).
    uint256 public optimalUtilization;
    /// @notice Fração máxima da dívida liquidável de uma vez (bps).
    uint16 public closeFactor;

    mapping(address => ReserveData) private _reserves;
    address[] private _assets;
    /// @notice Parte dos juros reservada ao protocolo, por ativo.
    mapping(address => uint256) public accruedTreasury;

    event ReserveInitialized(address indexed asset, address aToken, address debtToken,
                             uint16 ltv, uint16 liquidationThreshold, uint16 liquidationBonus);
    event Deposit(address indexed asset, address indexed user, address indexed onBehalfOf,
                  uint256 amount);
    event Withdraw(address indexed asset, address indexed user, address indexed to,
                   uint256 amount);
    event Borrow(address indexed asset, address indexed user, uint256 amount, uint256 borrowRate);
    event Repay(address indexed asset, address indexed user, address indexed onBehalfOf,
                uint256 amount);
    event LiquidationCall(address indexed collateralAsset, address indexed debtAsset,
                          address indexed user, address liquidator, uint256 debtRepaid,
                          uint256 collateralSeized);
    event TreasuryClaimed(address indexed asset, address indexed to, uint256 amount);
    event ReserveConfigUpdated(address indexed asset, uint16 ltv, uint16 liquidationThreshold,
                               uint16 liquidationBonus, uint16 reserveFactor,
                               bool active, bool borrowingEnabled);
    event RateParamsUpdated(uint256 baseRate, uint256 slope1, uint256 slope2,
                            uint256 optimalUtilization);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurLendingPool: NOT_OWNER');
        _;
    }

    constructor(address _priceOracle, uint256 baseAprBps, uint256 slope1AprBps,
                uint256 slope2AprBps, uint256 optimalUtilizationBps,
                uint16 _closeFactor) {
        require(_priceOracle != address(0), 'KurLendingPool: ZERO_ORACLE');
        require(optimalUtilizationBps > 0 && optimalUtilizationBps < BPS,
                'KurLendingPool: BAD_UTILIZATION');
        require(_closeFactor > 0 && _closeFactor <= BPS,
                'KurLendingPool: BAD_CLOSE_FACTOR');
        owner = msg.sender;
        priceOracle = _priceOracle;
        baseRate = _aprToPerSecond(baseAprBps);
        slope1 = _aprToPerSecond(slope1AprBps);
        slope2 = _aprToPerSecond(slope2AprBps);
        optimalUtilization = optimalUtilizationBps * RAY / BPS;
        closeFactor = _closeFactor;
    }

    // ─── Reservas ────────────────────────────────────────────────

    /// @notice Cria o mercado de um ativo (aToken + debtToken + parâmetros).
    /// @dev O ativo precisa ser um ERC-20 com `symbol()`/`decimals()`.
    function initReserve(address asset, uint16 ltv, uint16 liquidationThreshold,
                         uint16 liquidationBonus, uint16 reserveFactor)
        external onlyOwner returns (address aToken, address debtToken)
    {
        require(asset != address(0), 'KurLendingPool: ZERO_ASSET');
        require(_reserves[asset].aToken == address(0),
                'KurLendingPool: RESERVE_ALREADY_INITIALIZED');
        require(ltv > 0 && ltv <= liquidationThreshold && liquidationThreshold <= BPS,
                'KurLendingPool: BAD_CONFIG');
        require(liquidationBonus >= BPS, 'KurLendingPool: BAD_BONUS');
        require(reserveFactor <= BPS, 'KurLendingPool: BAD_RESERVE_FACTOR');

        string memory sym = IKurERC20Lending(asset).symbol();
        aToken = address(new KurScaledToken(
            string.concat('Kurama ', sym), string.concat('a', sym), asset));
        debtToken = address(new KurScaledToken(
            string.concat('Kurama Debt ', sym), string.concat('d', sym), asset));

        ReserveData storage r = _reserves[asset];
        r.aToken = aToken;
        r.debtToken = debtToken;
        r.decimals = IKurERC20Lending(asset).decimals();
        r.ltv = ltv;
        r.liquidationThreshold = liquidationThreshold;
        r.liquidationBonus = liquidationBonus;
        r.reserveFactor = reserveFactor;
        r.liquidityIndex = RAY;
        r.borrowIndex = RAY;
        r.lastUpdateTimestamp = uint40(block.timestamp);
        r.active = true;
        r.borrowingEnabled = true;

        _assets.push(asset);
        emit ReserveInitialized(asset, aToken, debtToken, ltv, liquidationThreshold,
                                liquidationBonus);
    }

    function getReservesCount() external view returns (uint256) {
        return _assets.length;
    }

    function getReservesList() external view returns (address[] memory) {
        return _assets;
    }

    function getReserveConfigurationData(address asset) external view returns (
        address aToken, address debtToken, uint8 decimals, uint16 ltv,
        uint16 liquidationThreshold, uint16 liquidationBonus, uint16 reserveFactor,
        bool active, bool borrowingEnabled
    ) {
        ReserveData storage r = _reserves[asset];
        return (r.aToken, r.debtToken, r.decimals, r.ltv, r.liquidationThreshold,
                r.liquidationBonus, r.reserveFactor, r.active, r.borrowingEnabled);
    }

    /// @notice Números do mercado (índices já projetados para `block.timestamp`).
    function getReserveData(address asset) external view returns (
        uint256 liquidityIndex, uint256 borrowIndex, uint256 totalBorrows,
        uint256 availableLiquidity, uint256 utilizationRate, uint256 borrowRatePerSecond
    ) {
        require(_reserves[asset].aToken != address(0),
                'KurLendingPool: RESERVE_NOT_INITIALIZED');
        (liquidityIndex, borrowIndex, ) = _projectedIndexes(asset);
        totalBorrows = _totalBorrowsAt(asset, borrowIndex);
        availableLiquidity = _availableLiquidity(asset);
        utilizationRate = _utilization(asset);
        borrowRatePerSecond = _borrowRate(asset);
    }

    /// @notice Taxa de juros corrente da dívida (ray por segundo) e utilização.
    function borrowRate(address asset) external view returns (uint256) {
        return _borrowRate(asset);
    }

    function utilization(address asset) external view returns (uint256) {
        return _utilization(asset);
    }

    // ─── Depósito / saque ────────────────────────────────────────

    /// @notice Deposita `amount` do ativo e recebe aToken (colateral que rende).
    function deposit(address asset, uint256 amount, address onBehalfOf) external {
        require(amount > 0, 'KurLendingPool: ZERO_AMOUNT');
        ReserveData storage r = _accrue(asset);
        require(r.active, 'KurLendingPool: RESERVE_INACTIVE');
        require(onBehalfOf != address(0), 'KurLendingPool: ZERO_ADDRESS');

        IKurERC20Lending(asset).transferFrom(msg.sender, address(this), amount);
        IKurScaledTokenLite(r.aToken).mint(onBehalfOf, amount);
        emit Deposit(asset, msg.sender, onBehalfOf, amount);
    }

    /// @notice Saca `amount` do ativo (use `type(uint256).max` para tudo).
    /// @return amount Sacado efetivamente.
    function withdraw(address asset, uint256 amount, address to)
        external returns (uint256)
    {
        ReserveData storage r = _accrue(asset);
        require(to != address(0), 'KurLendingPool: ZERO_ADDRESS');

        uint256 balance = _aBalanceOf(asset, msg.sender);
        if (amount == type(uint256).max) {
            amount = balance;
        }
        require(amount > 0 && amount <= balance, 'KurLendingPool: INVALID_AMOUNT');
        require(_availableLiquidity(asset) >= amount,
                'KurLendingPool: INSUFFICIENT_LIQUIDITY');

        // Queima o colateral ANTES de checar a saúde: se o saque deixar a
        // posição subcolateralizada, o revert desfaz a queima inteira.
        IKurScaledTokenLite(r.aToken).burn(msg.sender, amount);
        require(_healthFactor(msg.sender) >= WAD,
                'KurLendingPool: COLLATERAL_CANNOT_BE_WITHDRAWN');

        IKurERC20Lending(asset).transfer(to, amount);
        emit Withdraw(asset, msg.sender, to, amount);
        return amount;
    }

    // ─── Empréstimo / pagamento ──────────────────────────────────

    /// @notice Toma emprestado `amount` do ativo (taxa variável).
    function borrow(address asset, uint256 amount, address onBehalfOf) external {
        require(amount > 0, 'KurLendingPool: ZERO_AMOUNT');
        ReserveData storage r = _accrue(asset);
        require(r.active, 'KurLendingPool: RESERVE_INACTIVE');
        require(r.borrowingEnabled, 'KurLendingPool: BORROWING_DISABLED');
        require(onBehalfOf != address(0), 'KurLendingPool: ZERO_ADDRESS');
        require(_availableLiquidity(asset) >= amount,
                'KurLendingPool: INSUFFICIENT_LIQUIDITY');

        uint256 borrowValue = _assetValue(asset, amount);
        AccountData memory ad = _accountData(onBehalfOf);
        require(ad.collateral > 0, 'KurLendingPool: NO_COLLATERAL');
        require(ad.debt + borrowValue <= ad.weightedLtv / BPS,
                'KurLendingPool: COLLATERAL_LTV_EXCEEDED');
        require((ad.debt + borrowValue) * WAD
                    <= (ad.weightedThreshold / BPS) * WAD,
                'KurLendingPool: HEALTH_FACTOR_TOO_LOW');

        IKurScaledTokenLite(r.debtToken).mint(onBehalfOf, amount);
        IKurERC20Lending(asset).transfer(msg.sender, amount);
        emit Borrow(asset, onBehalfOf, amount, _borrowRate(asset));
    }

    /// @notice Paga `amount` da dívida de `onBehalfOf` (max = dívida inteira).
    /// @return repaid Valor efetivamente pago (limitado à dívida).
    function repay(address asset, uint256 amount, address onBehalfOf)
        external returns (uint256 repaid)
    {
        ReserveData storage r = _accrue(asset);
        uint256 debt = _debtBalanceOf(asset, onBehalfOf);
        repaid = amount > debt ? debt : amount;
        require(repaid > 0, 'KurLendingPool: NO_DEBT');

        IKurERC20Lending(asset).transferFrom(msg.sender, address(this), repaid);
        IKurScaledTokenLite(r.debtToken).burn(onBehalfOf, repaid);
        emit Repay(asset, msg.sender, onBehalfOf, repaid);
    }

    // ─── Liquidação ──────────────────────────────────────────────

    /// @notice Liquida uma posição com fator de saúde < 1.
    /// @dev O liquidante paga `debtToCover` do `debtAsset` (limitado pelo
    ///      `closeFactor`) e recebe o equivalente em `collateralAsset` mais o
    ///      `liquidationBonus`.
    /// @return collateralSeized Colateral recebido pelo liquidante.
    function liquidationCall(address collateralAsset, address debtAsset, address user,
                             uint256 debtToCover)
        external returns (uint256 collateralSeized)
    {
        _accrue(collateralAsset);
        _accrue(debtAsset);
        require(collateralAsset != debtAsset, 'KurLendingPool: SAME_ASSET');
        require(_healthFactor(user) < WAD,
                'KurLendingPool: HEALTH_FACTOR_NOT_BELOW_THRESHOLD');

        uint256 debt = _debtBalanceOf(debtAsset, user);
        require(debt > 0, 'KurLendingPool: NO_DEBT_OF_SELECTED_ASSET');
        uint256 maxCover = debt * closeFactor / BPS;
        if (debtToCover > maxCover) {
            debtToCover = maxCover;
        }
        require(debtToCover > 0, 'KurLendingPool: NOTHING_TO_LIQUIDATE');

        ReserveData storage collateralReserve = _reserves[collateralAsset];
        uint256 collateralBalance = _aBalanceOf(collateralAsset, user);
        require(collateralBalance > 0, 'KurLendingPool: NO_COLLATERAL');

        // valor da dívida → colateral + bônus do liquidante.
        // `liquidationBonus` já é o multiplicador em bps (10500 = 1,05 = +5%).
        uint256 debtValue = _assetValue(debtAsset, debtToCover);
        uint256 priceCollateral = IKurPriceOracleLite(priceOracle)
            .getAssetPrice(collateralAsset);
        collateralSeized = debtValue * collateralReserve.liquidationBonus / BPS
            * (10**collateralReserve.decimals) / priceCollateral;
        if (collateralSeized > collateralBalance) {
            collateralSeized = collateralBalance;
        }
        require(_availableLiquidity(collateralAsset) >= collateralSeized,
                'KurLendingPool: INSUFFICIENT_LIQUIDITY');

        // liquidante paga a dívida; pool queima a dívida e entrega o colateral
        IKurERC20Lending(debtAsset).transferFrom(msg.sender, address(this), debtToCover);
        IKurScaledTokenLite(_reserves[debtAsset].debtToken).burn(user, debtToCover);
        IKurScaledTokenLite(collateralReserve.aToken).burn(user, collateralSeized);
        IKurERC20Lending(collateralAsset).transfer(msg.sender, collateralSeized);

        emit LiquidationCall(collateralAsset, debtAsset, user, msg.sender, debtToCover,
                             collateralSeized);
    }

    // ─── Juros ───────────────────────────────────────────────────

    /// @notice Aplica os juros pendentes do mercado (pode ser chamado por qualquer um).
    function accrue(address asset) external {
        _accrue(asset);
    }

    /// @notice Índices correntes do mercado, já projetados para agora.
    function getIndexes(address asset) external view returns (
        uint256 liquidityIndex, uint256 borrowIndex
    ) {
        (liquidityIndex, borrowIndex, ) = _projectedIndexes(asset);
    }

    /// @notice Juros acumulados do protocolo no ativo.
    function claimTreasury(address asset, address to)
        external onlyOwner returns (uint256 amount)
    {
        amount = accruedTreasury[asset];
        require(amount > 0, 'KurLendingPool: NOTHING_TO_CLAIM');
        require(_availableLiquidity(asset) >= amount,
                'KurLendingPool: INSUFFICIENT_LIQUIDITY');
        accruedTreasury[asset] = 0;
        IKurERC20Lending(asset).transfer(to, amount);
        emit TreasuryClaimed(asset, to, amount);
    }

    // ─── Visão de conta ──────────────────────────────────────────

    /// @notice Dados agregados da conta (valores em 18 decimais).
    /// @return totalCollateralBase Valor do colateral.
    /// @return totalDebtBase Valor da dívida.
    /// @return availableBorrowsBase Quanto ainda pode ser emprestado (pelo LTV).
    /// @return currentLiquidationThreshold Limiar médio de liquidação (bps).
    /// @return ltv LTV médio do colateral (bps).
    /// @return healthFactor Fator de saúde (1e18 = limite; `type(uint256).max` sem dívida).
    function getUserAccountData(address user) public view returns (
        uint256 totalCollateralBase, uint256 totalDebtBase, uint256 availableBorrowsBase,
        uint256 currentLiquidationThreshold, uint256 ltv, uint256 healthFactor
    ) {
        AccountData memory ad = _accountData(user);
        totalCollateralBase = ad.collateral;
        totalDebtBase = ad.debt;
        ltv = ad.collateral == 0 ? 0 : ad.weightedLtv / ad.collateral;
        currentLiquidationThreshold = ad.collateral == 0
            ? 0 : ad.weightedThreshold / ad.collateral;
        uint256 maxBorrow = ad.collateral * ltv / BPS;
        availableBorrowsBase = maxBorrow > ad.debt ? maxBorrow - ad.debt : 0;
        healthFactor = ad.debt == 0
            ? type(uint256).max
            : (ad.weightedThreshold / BPS) * WAD / ad.debt;
    }

    /// @notice Saldo de aToken (colateral) e debtToken (dívida) de um usuário.
    function getUserReserveData(address user, address asset) external view returns (
        uint256 aTokenBalance, uint256 debtTokenBalance
    ) {
        return (_aBalanceOf(asset, user), _debtBalanceOf(asset, user));
    }

    // ─── Administração ───────────────────────────────────────────

    function setReserveConfig(address asset, uint16 ltv, uint16 liquidationThreshold,
                              uint16 liquidationBonus, uint16 reserveFactor,
                              bool active, bool borrowingEnabled) external onlyOwner
    {
        ReserveData storage r = _reserves[asset];
        require(r.aToken != address(0), 'KurLendingPool: RESERVE_NOT_INITIALIZED');
        require(ltv > 0 && ltv <= liquidationThreshold && liquidationThreshold <= BPS,
                'KurLendingPool: BAD_CONFIG');
        require(liquidationBonus >= BPS, 'KurLendingPool: BAD_BONUS');
        require(reserveFactor <= BPS, 'KurLendingPool: BAD_RESERVE_FACTOR');
        r.ltv = ltv;
        r.liquidationThreshold = liquidationThreshold;
        r.liquidationBonus = liquidationBonus;
        r.reserveFactor = reserveFactor;
        r.active = active;
        r.borrowingEnabled = borrowingEnabled;
        emit ReserveConfigUpdated(asset, ltv, liquidationThreshold, liquidationBonus,
                                  reserveFactor, active, borrowingEnabled);
    }

    /// @notice Ajusta o modelo de juros (APR em bps → taxa por segundo em ray).
    function setRateParams(uint256 baseAprBps, uint256 slope1AprBps, uint256 slope2AprBps,
                           uint256 optimalUtilizationBps) external onlyOwner
    {
        require(optimalUtilizationBps > 0 && optimalUtilizationBps < BPS,
                'KurLendingPool: BAD_UTILIZATION');
        baseRate = _aprToPerSecond(baseAprBps);
        slope1 = _aprToPerSecond(slope1AprBps);
        slope2 = _aprToPerSecond(slope2AprBps);
        optimalUtilization = optimalUtilizationBps * RAY / BPS;
        emit RateParamsUpdated(baseRate, slope1, slope2, optimalUtilization);
    }

    function setPriceOracle(address newOracle) external onlyOwner {
        require(newOracle != address(0), 'KurLendingPool: ZERO_ORACLE');
        priceOracle = newOracle;
    }

    function setCloseFactor(uint16 newCloseFactor) external onlyOwner {
        require(newCloseFactor > 0 && newCloseFactor <= BPS,
                'KurLendingPool: BAD_CLOSE_FACTOR');
        closeFactor = newCloseFactor;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), 'KurLendingPool: ZERO_ADDRESS');
        owner = newOwner;
    }

    // ─── Internos: juros ─────────────────────────────────────────

    /// @dev Aplica os juros pendentes e devolve a reserva.
    function _accrue(address asset) internal returns (ReserveData storage r) {
        r = _reserves[asset];
        require(r.aToken != address(0), 'KurLendingPool: RESERVE_NOT_INITIALIZED');
        (uint256 liquidityIndex, uint256 borrowIndex, uint256 interest) =
            _projectedIndexes(asset);
        if (liquidityIndex != r.liquidityIndex) {
            r.liquidityIndex = liquidityIndex;
            IKurScaledTokenLite(r.aToken).setIndex(liquidityIndex);
        }
        if (borrowIndex != r.borrowIndex) {
            r.borrowIndex = borrowIndex;
            IKurScaledTokenLite(r.debtToken).setIndex(borrowIndex);
        }
        if (interest != 0 && r.reserveFactor != 0) {
            accruedTreasury[asset] += interest * r.reserveFactor / BPS;
        }
        r.lastUpdateTimestamp = uint40(block.timestamp);
    }

    /// @dev Projeta os índices para `block.timestamp` sem tocar no estado.
    ///      Retorna também os juros (unidades do ativo) gerados no intervalo.
    function _projectedIndexes(address asset) internal view returns (
        uint256 liquidityIndex, uint256 borrowIndex, uint256 interest
    ) {
        ReserveData storage r = _reserves[asset];
        liquidityIndex = r.liquidityIndex;
        borrowIndex = r.borrowIndex;
        uint256 elapsed = block.timestamp - r.lastUpdateTimestamp;
        if (elapsed == 0) {
            return (liquidityIndex, borrowIndex, 0);
        }
        uint256 debt = _totalBorrowsAt(asset, r.borrowIndex);
        if (debt == 0) {
            return (liquidityIndex, borrowIndex, 0);
        }
        uint256 borrowRateRay = _borrowRate(asset);
        uint256 liquidityRateRay = borrowRateRay * _utilization(asset) / RAY
            * (BPS - r.reserveFactor) / BPS;
        interest = debt * borrowRateRay * elapsed / RAY;
        borrowIndex = borrowIndex + borrowIndex * borrowRateRay * elapsed / RAY;
        liquidityIndex = liquidityIndex + liquidityIndex * liquidityRateRay * elapsed / RAY;
    }

    /// @dev Taxa da dívida (ray por segundo) para a utilização corrente.
    function _borrowRate(address asset) internal view returns (uint256) {
        uint256 u = _utilization(asset);
        if (u <= optimalUtilization) {
            return baseRate + slope1 * u / optimalUtilization;
        }
        return baseRate + slope1 + slope2 * (u - optimalUtilization)
            / (RAY - optimalUtilization);
    }

    /// @dev dívida / (dívida + liquidez disponível).
    function _utilization(address asset) internal view returns (uint256) {
        uint256 debt = _totalBorrowsAt(asset, _reserves[asset].borrowIndex);
        uint256 total = debt + _availableLiquidity(asset);
        return total == 0 ? 0 : debt * RAY / total;
    }

    function _totalBorrowsAt(address asset, uint256 borrowIndex) internal view returns (uint256) {
        return IKurScaledTokenLite(_reserves[asset].debtToken).scaledTotalSupply()
            * borrowIndex / RAY;
    }

    function _availableLiquidity(address asset) internal view returns (uint256) {
        return IKurERC20Lending(asset).balanceOf(address(this));
    }

    // ─── Internos: saldos e valores ──────────────────────────────

    /// @dev Saldo de aToken do usuário com o índice corrente (projetado).
    function _aBalanceOf(address asset, address user) internal view returns (uint256) {
        (uint256 liquidityIndex, , ) = _projectedIndexes(asset);
        return IKurScaledTokenLite(_reserves[asset].aToken).scaledBalanceOf(user)
            * liquidityIndex / RAY;
    }

    /// @dev Dívida do usuário com o índice corrente (projetado).
    function _debtBalanceOf(address asset, address user) internal view returns (uint256) {
        (, uint256 borrowIndex, ) = _projectedIndexes(asset);
        return IKurScaledTokenLite(_reserves[asset].debtToken).scaledBalanceOf(user)
            * borrowIndex / RAY;
    }

    /// @dev Valor de `amount` do ativo em moeda-base (18 decimais).
    function _assetValue(address asset, uint256 amount) internal view returns (uint256) {
        uint256 price = IKurPriceOracleLite(priceOracle).getAssetPrice(asset);
        return amount * price / (10**_reserves[asset].decimals);
    }

    function _accountData(address user) internal view returns (AccountData memory ad) {
        uint256 n = _assets.length;
        for (uint256 i = 0; i < n; i++) {
            address asset = _assets[i];
            ReserveData storage r = _reserves[asset];
            uint256 collateral = _aBalanceOf(asset, user);
            if (collateral > 0) {
                uint256 value = _assetValue(asset, collateral);
                ad.collateral += value;
                ad.weightedLtv += value * r.ltv;
                ad.weightedThreshold += value * r.liquidationThreshold;
            }
            uint256 debt = _debtBalanceOf(asset, user);
            if (debt > 0) {
                ad.debt += _assetValue(asset, debt);
            }
        }
    }

    /// @dev Fator de saúde (1e18 = limite de liquidação; max uint sem dívida).
    function _healthFactor(address user) internal view returns (uint256) {
        uint256 hf;
        (, , , , , hf) = getUserAccountData(user);
        return hf;
    }

    // ─── Internos: utilidades ────────────────────────────────────

    /// @dev Converte uma APR (bps) na taxa por segundo em ray.
    function _aprToPerSecond(uint256 aprBps) internal pure returns (uint256) {
        return aprBps * RAY / BPS / SECONDS_PER_YEAR;
    }
}
