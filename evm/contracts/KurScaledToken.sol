// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title KurScaledToken — token com saldo indexado (aToken / debtToken)
/// @notice Implementa o modelo de saldo "escalado" do Aave: o saldo contábil
///         (`scaledBalanceOf`) é fixo e o saldo real (`balanceOf`) cresce com
///         o índice (`index`, em ray = 1e27):
///
///             balanceOf(u)  = scaledBalanceOf(u) * index / 1e27
///             totalSupply() = scaledTotalSupply()  * index / 1e27
///
///         O pool (`KurLendingPool`) é o único que pode cunhar/queimar e
///         atualizar o índice — com `liquidityIndex` o token é um **aToken**
///         (depósito que rende juros) e com `borrowIndex` é um **debtToken**
///         (dívida que cresce com os juros).
///
///         Transferências são um ERC-20 normal, mas os valores são convertidos
///         para escalado na entrada (a `allowance` é expressa no saldo real).
contract KurScaledToken {
    uint256 internal constant RAY = 1e27;

    string public name;
    string public symbol;
    uint8 public constant decimals = 18;
    /// @notice Ativo subjacente (o token depositado/emprestado).
    address public immutable underlying;
    /// @notice Contrato autorizado a cunhar/queimar/atualizar o índice.
    address public pool;

    /// @notice Índice atual (ray). Nunca diminui.
    uint256 public index;

    mapping(address => uint256) internal _scaled;
    uint256 internal _scaledTotal;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event IndexUpdated(uint256 index);

    modifier onlyPool() {
        require(msg.sender == pool, 'KurScaledToken: NOT_POOL');
        _;
    }

    constructor(string memory _name, string memory _symbol, address _underlying) {
        name = _name;
        symbol = _symbol;
        underlying = _underlying;
        pool = msg.sender;
        index = RAY;
    }

    // ─── Saldos indexados ────────────────────────────────────────

    function scaledBalanceOf(address account) external view returns (uint256) {
        return _scaled[account];
    }

    function scaledTotalSupply() external view returns (uint256) {
        return _scaledTotal;
    }

    function balanceOf(address account) public view returns (uint256) {
        return _scaled[account] * index / RAY;
    }

    function totalSupply() external view returns (uint256) {
        return _scaledTotal * index / RAY;
    }

    /// @notice Converte um valor do ativo subjacente no saldo escalado.
    function scaledFrom(uint256 amount) external view returns (uint256) {
        return amount * RAY / index;
    }

    // ─── Escrita (pool) ──────────────────────────────────────────

    /// @notice Cunha `amount` (em unidades do subjacente) para `to`.
    /// @dev Arredonda para baixo: o dust fica com o pool.
    function mint(address to, uint256 amount) external onlyPool returns (uint256 scaled) {
        require(to != address(0), 'KurScaledToken: MINT_TO_ZERO');
        scaled = amount * RAY / index;
        _scaled[to] += scaled;
        _scaledTotal += scaled;
        emit Transfer(address(0), to, amount);
    }

    /// @notice Queima `amount` (em unidades do subjacente) de `from`.
    /// @dev Arredonda para cima (protege o pool); se `amount` cobre todo o
    ///      saldo, queima o saldo escalado inteiro (evita dust de arredondamento).
    function burn(address from, uint256 amount) external onlyPool returns (uint256 scaled) {
        uint256 balance = _scaled[from] * index / RAY;
        if (amount >= balance) {
            scaled = _scaled[from];
        } else {
            scaled = _rayDivUp(amount, index);
            require(scaled <= _scaled[from], 'KurScaledToken: INSUFFICIENT_BALANCE');
        }
        _scaled[from] -= scaled;
        _scaledTotal -= scaled;
        emit Transfer(from, address(0), amount);
    }

    /// @notice Atualiza o índice (juros). Nunca pode diminuir.
    function setIndex(uint256 newIndex) external onlyPool {
        require(newIndex >= index, 'KurScaledToken: INDEX_DECREASED');
        index = newIndex;
        emit IndexUpdated(newIndex);
    }

    // ─── ERC-20 ──────────────────────────────────────────────────

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, 'KurScaledToken: ALLOWANCE_EXCEEDED');
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    // ─── Internos ────────────────────────────────────────────────

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), 'KurScaledToken: TRANSFER_TO_ZERO');
        uint256 scaled = value * RAY / index;
        require(_scaled[from] >= scaled, 'KurScaledToken: INSUFFICIENT_BALANCE');
        _scaled[from] -= scaled;
        _scaled[to] += scaled;
        emit Transfer(from, to, value);
    }

    function _rayDivUp(uint256 amount, uint256 divisor) private pure returns (uint256) {
        return (amount * RAY + divisor - 1) / divisor;
    }
}
