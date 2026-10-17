// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

interface IBridgeERC20 {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

interface IKurWrappedToken {
    function mint(address to, uint256 value) external;
    function burn(address from, uint256 value) external;
}

/// @title KurBridge — bridge lock/mint com atestação de validadores
/// @notice Conecta a KuramaChain a outras redes sem depender de mensageria
///         externa: os validadores observam `Deposit` na chain de origem e
///         assinam o comprovante (EIP-191). Com `threshold` assinaturas de
///         validadores distintos, qualquer conta executa `withdraw` na chain
///         de destino.
///
///         Modelo:
///         - token "nativo" desta chain: fica **travado** no bridge no depósito
///           e é liberado no saque (lock/release);
///         - token externo: é registrado com `registerWrapped` e a versão
///           `KurWrappedToken` é **cunhada** no saque (mint) e **queimada** no
///           depósito de volta (burn).
///
///         Segurança: `depositId` só pode ser processado uma vez; a mensagem
///         assinada amarra as duas chains, o bridge, o destinatário e o valor;
///         as assinaturas precisam vir em ordem crescente de endereço (sem
///         duplicatas). O owner pode pausar o bridge em emergência.
contract KurBridge {
    uint256 public immutable localChainId;
    address public owner;
    uint256 public threshold;
    bool public paused;

    mapping(address => bool) public isValidator;
    address[] public validators;

    /// @notice Depósitos já processados (por `depositId`).
    mapping(bytes32 => bool) public processed;

    /// @notice chain remota => token remoto => wrapped local (saque cunha).
    mapping(uint256 => mapping(address => address)) public wrappedFor;
    /// @notice chain remota => token remoto => ativo local liberado (saque libera).
    mapping(uint256 => mapping(address => address)) public releaseFor;
    /// @notice Tokens locais que são wrapped (depósito queima em vez de travar).
    mapping(address => bool) public isWrapped;

    uint256 public nonce;

    event Deposit(
        bytes32 indexed depositId,
        address indexed token,
        address indexed sender,
        uint256 amount,
        uint256 destChain,
        address recipient,
        uint256 nonce
    );
    event Withdrawal(
        bytes32 indexed depositId,
        uint256 indexed srcChain,
        address indexed token,
        address recipient,
        uint256 amount,
        bool minted
    );
    event ValidatorUpdated(address indexed validator, bool allowed);
    event ThresholdUpdated(uint256 threshold);
    event WrappedRegistered(uint256 indexed remoteChain, address indexed remoteToken,
                            address indexed wrappedToken);
    event ReleaseRegistered(uint256 indexed remoteChain, address indexed remoteToken,
                            address indexed localToken);
    event Paused(bool paused);
    event OwnershipTransferred(address indexed from, address indexed to);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurBridge: NOT_OWNER');
        _;
    }

    modifier whenNotPaused() {
        require(!paused, 'KurBridge: PAUSED');
        _;
    }

    constructor(uint256 _localChainId, address[] memory _validators, uint256 _threshold) {
        require(_localChainId != 0, 'KurBridge: BAD_CHAIN');
        require(_threshold > 0 && _threshold <= _validators.length, 'KurBridge: BAD_THRESHOLD');
        owner = msg.sender;
        localChainId = _localChainId;
        threshold = _threshold;
        for (uint256 i = 0; i < _validators.length; i++) {
            _addValidator(_validators[i]);
        }
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ─── Depósito (chain de origem) ──────────────────────────────

    /// @notice Trava (ou queima, se for wrapped) `amount` e emite o comprovante.
    /// @param token Token local a transferir.
    /// @param amount Quantidade (em unidades do token).
    /// @param destChain Chain ID EVM de destino.
    /// @param recipient Endereço de destino na outra chain.
    function deposit(address token, uint256 amount, uint256 destChain, address recipient)
        external whenNotPaused returns (bytes32 depositId)
    {
        require(token != address(0), 'KurBridge: ZERO_ADDRESS');
        require(recipient != address(0), 'KurBridge: ZERO_ADDRESS');
        require(amount > 0, 'KurBridge: ZERO_AMOUNT');
        require(destChain != localChainId, 'KurBridge: SAME_CHAIN');

        if (isWrapped[token]) {
            // Volta para a chain de origem: queima o wrapped.
            IKurWrappedToken(token).burn(msg.sender, amount);
        } else {
            require(IBridgeERC20(token).transferFrom(msg.sender, address(this), amount),
                    'KurBridge: TRANSFER_FAILED');
        }

        nonce += 1;
        depositId = keccak256(abi.encode(
            address(this), localChainId, token, msg.sender, amount,
            destChain, recipient, nonce
        ));
        emit Deposit(depositId, token, msg.sender, amount, destChain, recipient, nonce);
    }

    // ─── Saque (chain de destino) ────────────────────────────────

    /// @notice Comprova um depósito feito na chain de origem e libera/cunha.
    /// @param signatures Assinaturas EIP-191 dos validadores, ordenadas por
    ///        endereço crescente.
    function withdraw(
        uint256 srcChain,
        address token,
        address recipient,
        uint256 amount,
        uint256 _nonce,
        bytes32 depositId,
        bytes[] calldata signatures
    ) external whenNotPaused returns (bool minted) {
        require(srcChain != localChainId, 'KurBridge: SAME_CHAIN');
        require(recipient != address(0), 'KurBridge: ZERO_ADDRESS');
        require(amount > 0, 'KurBridge: ZERO_AMOUNT');
        require(!processed[depositId], 'KurBridge: ALREADY_PROCESSED');
        require(signatures.length >= threshold, 'KurBridge: NOT_ENOUGH_SIGNATURES');

        bytes32 digest = withdrawalDigest(srcChain, token, recipient, amount, _nonce, depositId);
        address last = address(0);
        for (uint256 i = 0; i < signatures.length; i++) {
            address signer = _recover(digest, signatures[i]);
            require(signer != address(0), 'KurBridge: BAD_SIGNATURE');
            require(isValidator[signer], 'KurBridge: NOT_VALIDATOR');
            require(signer > last, 'KurBridge: BAD_ORDER');
            last = signer;
        }

        processed[depositId] = true;

        address wrapped = wrappedFor[srcChain][token];
        if (wrapped != address(0)) {
            IKurWrappedToken(wrapped).mint(recipient, amount);
            minted = true;
        } else {
            // Sem wrapped: libera o ativo travado (mapeado por releaseFor na
            // volta de um ativo que nasceu aqui, ou o próprio token depositado).
            address asset = releaseFor[srcChain][token];
            if (asset == address(0)) {
                asset = token;
            }
            require(IBridgeERC20(asset).transfer(recipient, amount),
                    'KurBridge: TRANSFER_FAILED');
        }
        emit Withdrawal(depositId, srcChain, token, recipient, amount, minted);
    }

    /// @notice Hash da mensagem assinada pelos validadores (sem o prefixo EIP-191).
    function withdrawalHash(
        uint256 srcChain, address token, address recipient,
        uint256 amount, uint256 _nonce, bytes32 depositId
    ) public view returns (bytes32) {
        return keccak256(abi.encode(
            srcChain, localChainId, token, recipient, amount, _nonce,
            depositId, address(this)
        ));
    }

    /// @notice Digest EIP-191 que os validadores assinam (`eth_sign`/`personal_sign`).
    function withdrawalDigest(
        uint256 srcChain, address token, address recipient,
        uint256 amount, uint256 _nonce, bytes32 depositId
    ) public view returns (bytes32) {
        return keccak256(abi.encodePacked(
            '\x19Ethereum Signed Message:\n32',
            withdrawalHash(srcChain, token, recipient, amount, _nonce, depositId)
        ));
    }

    // ─── Administração ───────────────────────────────────────────

    function registerWrapped(uint256 remoteChain, address remoteToken, address wrappedToken)
        external onlyOwner
    {
        require(remoteChain != 0 && remoteChain != localChainId, 'KurBridge: BAD_CHAIN');
        require(remoteToken != address(0) && wrappedToken != address(0), 'KurBridge: ZERO_ADDRESS');
        require(wrappedFor[remoteChain][remoteToken] == address(0), 'KurBridge: ALREADY_REGISTERED');
        wrappedFor[remoteChain][remoteToken] = wrappedToken;
        isWrapped[wrappedToken] = true;
        emit WrappedRegistered(remoteChain, remoteToken, wrappedToken);
    }

    /// @notice Mapeia um ativo externo para o ativo **local** a ser liberado no
    ///         saque (usado para devolver ao ativo original na volta do bridge).
    function registerRelease(uint256 remoteChain, address remoteToken, address localToken)
        external onlyOwner
    {
        require(remoteChain != 0 && remoteChain != localChainId, 'KurBridge: BAD_CHAIN');
        require(remoteToken != address(0) && localToken != address(0), 'KurBridge: ZERO_ADDRESS');
        require(releaseFor[remoteChain][remoteToken] == address(0), 'KurBridge: ALREADY_REGISTERED');
        releaseFor[remoteChain][remoteToken] = localToken;
        emit ReleaseRegistered(remoteChain, remoteToken, localToken);
    }

    function setValidator(address validator, bool allowed) external onlyOwner {
        if (allowed) {
            _addValidator(validator);
        } else {
            require(isValidator[validator], 'KurBridge: NOT_VALIDATOR');
            isValidator[validator] = false;
            uint256 n = validators.length;
            for (uint256 i = 0; i < n; i++) {
                if (validators[i] == validator) {
                    validators[i] = validators[n - 1];
                    validators.pop();
                    break;
                }
            }
            require(threshold <= validators.length, 'KurBridge: THRESHOLD_TOO_HIGH');
            emit ValidatorUpdated(validator, false);
        }
    }

    function setThreshold(uint256 newThreshold) external onlyOwner {
        require(newThreshold > 0 && newThreshold <= validators.length,
                'KurBridge: BAD_THRESHOLD');
        threshold = newThreshold;
        emit ThresholdUpdated(newThreshold);
    }

    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        emit Paused(_paused);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), 'KurBridge: ZERO_ADDRESS');
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function validatorsLength() external view returns (uint256) {
        return validators.length;
    }

    // ─── Internos ────────────────────────────────────────────────

    function _addValidator(address validator) internal {
        require(validator != address(0), 'KurBridge: ZERO_ADDRESS');
        require(!isValidator[validator], 'KurBridge: VALIDATOR_EXISTS');
        isValidator[validator] = true;
        validators.push(validator);
        emit ValidatorUpdated(validator, true);
    }

    function _recover(bytes32 digest, bytes calldata signature) internal pure returns (address) {
        if (signature.length != 65) {
            return address(0);
        }
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (v < 27) {
            v += 27;
        }
        if (v != 27 && v != 28) {
            return address(0);
        }
        // Rejeita assinaturas maleáveis (high-s).
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        return ecrecover(digest, v, r, s);
    }
}
