// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @title KurWrappedToken — ativo externo representado na KuramaChain
/// @notice ERC-20 cunhado/queimado **apenas** pelo bridge. Serve para o modelo
///         lock/mint: o ativo original fica travado na chain de origem e a
///         versão wrapped circula aqui.
contract KurWrappedToken {
    string public name;
    string public symbol;
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    address public immutable bridge;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    modifier onlyBridge() {
        require(msg.sender == bridge, 'KurWrappedToken: NOT_BRIDGE');
        _;
    }

    constructor(string memory _name, string memory _symbol, address _bridge) {
        require(_bridge != address(0), 'KurWrappedToken: ZERO_BRIDGE');
        name = _name;
        symbol = _symbol;
        bridge = _bridge;
    }

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
        require(allowed >= value, 'KurWrappedToken: ALLOWANCE');
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function mint(address to, uint256 value) external onlyBridge {
        require(to != address(0), 'KurWrappedToken: ZERO_ADDRESS');
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }

    function burn(address from, uint256 value) external onlyBridge {
        require(balanceOf[from] >= value, 'KurWrappedToken: BALANCE');
        balanceOf[from] -= value;
        totalSupply -= value;
        emit Transfer(from, address(0), value);
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), 'KurWrappedToken: ZERO_ADDRESS');
        require(balanceOf[from] >= value, 'KurWrappedToken: BALANCE');
        balanceOf[from] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }
}
