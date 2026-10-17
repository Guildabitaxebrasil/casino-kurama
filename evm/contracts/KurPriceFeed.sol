// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/// @notice Subconjunto da `AggregatorV3Interface` (Chainlink) usado pelos
///         consumidores de preço. Contratos externos que já falam Chainlink
///         funcionam sem alteração.
interface AggregatorV3Interface {
    function decimals() external view returns (uint8);
    function description() external view returns (string memory);
    function version() external view returns (uint256);

    function latestRoundData() external view returns (
        uint80 roundId, int256 answer, uint256 startedAt,
        uint256 updatedAt, uint80 answeredInRound
    );

    function getRoundData(uint80 _roundId) external view returns (
        uint80 roundId, int256 answer, uint256 startedAt,
        uint256 updatedAt, uint80 answeredInRound
    );
}

/// @title KurPriceFeed — feed de preço on-chain (padrão Chainlink aggregator)
/// @notice Nós oráculo autorizados (`reporters`) enviam o preço off-chain
///         assinado (`submit`). Quando o número de envios de uma rodada atinge
///         o `quorum`, a rodada é fechada com a **mediana** dos valores —
///         um único reporter desonesto não move o preço.
///
///         Formato de retorno: sempre 8 decimais (ex.: 2500.00 USD = 250000000000),
///         igual aos feeds USD da Chainlink.
contract KurPriceFeed is AggregatorV3Interface {
    struct Round {
        int256 answer;
        uint256 startedAt;
        uint256 updatedAt;
        uint80 answeredInRound;
    }

    uint8 private constant _DECIMALS = 8;

    address public owner;
    string public override description;
    uint256 public quorum;

    mapping(address => bool) public isReporter;
    address[] public reporters;

    mapping(uint80 => Round) private _rounds;
    /// @notice Última rodada fechada (0 = nenhuma ainda).
    uint80 public latestRound;

    // ─── Estado da rodada aberta ─────────────────────────────────
    uint80 private _openRound;
    uint256 private _openCount;
    mapping(uint80 => address[]) private _submitters;
    mapping(uint80 => mapping(address => int256)) private _submission;
    mapping(uint80 => mapping(address => bool)) private _hasSubmitted;

    event NewReporter(address indexed reporter, bool allowed);
    event QuorumUpdated(uint256 quorum);
    event Submission(address indexed reporter, uint80 indexed roundId, int256 price);
    event AnswerUpdated(int256 indexed current, uint80 indexed roundId, uint256 updatedAt);
    event OwnershipTransferred(address indexed from, address indexed to);

    modifier onlyOwner() {
        require(msg.sender == owner, 'KurPriceFeed: NOT_OWNER');
        _;
    }

    modifier onlyReporter() {
        require(isReporter[msg.sender], 'KurPriceFeed: NOT_REPORTER');
        _;
    }

    constructor(string memory _description, uint256 _quorum, address[] memory _reporters) {
        require(_quorum > 0, 'KurPriceFeed: BAD_QUORUM');
        require(_reporters.length >= _quorum, 'KurPriceFeed: BAD_QUORUM');
        owner = msg.sender;
        description = _description;
        quorum = _quorum;
        for (uint256 i = 0; i < _reporters.length; i++) {
            _addReporter(_reporters[i]);
        }
        _openRound = 1;
        _rounds[_openRound].startedAt = block.timestamp;
    }

    // ─── Metadados (AggregatorV3) ────────────────────────────────

    function decimals() external pure override returns (uint8) {
        return _DECIMALS;
    }

    function version() external pure override returns (uint256) {
        return 3;
    }

    function reportersLength() external view returns (uint256) {
        return reporters.length;
    }

    // ─── Escrita (nós oráculo) ───────────────────────────────────

    /// @notice Reporta o preço da rodada aberta.
    /// @param price Preço em 8 decimais (deve ser positivo).
    /// @return roundId Rodada **fechada** se esta submissão atingiu o quórum,
    ///         ou 0 se a rodada continua aberta.
    function submit(int256 price) external onlyReporter returns (uint80 roundId) {
        require(price > 0, 'KurPriceFeed: BAD_PRICE');
        uint80 open = _openRound;
        require(!_hasSubmitted[open][msg.sender], 'KurPriceFeed: ALREADY_SUBMITTED');

        _hasSubmitted[open][msg.sender] = true;
        _submission[open][msg.sender] = price;
        _submitters[open].push(msg.sender);
        _openCount += 1;
        emit Submission(msg.sender, open, price);

        if (_openCount >= quorum) {
            roundId = open;
            int256 answer = _median(open, _openCount);
            _rounds[roundId].answer = answer;
            _rounds[roundId].updatedAt = block.timestamp;
            _rounds[roundId].answeredInRound = roundId;
            latestRound = roundId;

            // Abre a próxima rodada.
            _openRound = roundId + 1;
            _openCount = 0;
            _rounds[_openRound].startedAt = block.timestamp;
            emit AnswerUpdated(answer, roundId, block.timestamp);
        }
    }

    // ─── Leitura (AggregatorV3) ──────────────────────────────────

    function latestRoundData() external view override returns (
        uint80 roundId, int256 answer, uint256 startedAt,
        uint256 updatedAt, uint80 answeredInRound
    ) {
        roundId = latestRound;
        require(roundId != 0, 'KurPriceFeed: NO_DATA');
        Round memory r = _rounds[roundId];
        return (roundId, r.answer, r.startedAt, r.updatedAt, r.answeredInRound);
    }

    function getRoundData(uint80 _roundId) external view override returns (
        uint80 roundId, int256 answer, uint256 startedAt,
        uint256 updatedAt, uint80 answeredInRound
    ) {
        Round memory r = _rounds[_roundId];
        require(r.updatedAt != 0, 'KurPriceFeed: NO_DATA');
        return (_roundId, r.answer, r.startedAt, r.updatedAt, r.answeredInRound);
    }

    /// @notice Atalho: último preço (0 se nenhuma rodada foi fechada).
    function latestAnswer() external view returns (int256) {
        return _rounds[latestRound].answer;
    }

    /// @notice Atalho: timestamp do último preço (0 se nenhuma rodada fechada).
    function latestTimestamp() external view returns (uint256) {
        return _rounds[latestRound].updatedAt;
    }

    // ─── Administração ───────────────────────────────────────────

    function setReporter(address reporter, bool allowed) external onlyOwner {
        if (allowed) {
            _addReporter(reporter);
        } else {
            require(isReporter[reporter], 'KurPriceFeed: NOT_REPORTER');
            isReporter[reporter] = false;
            uint256 n = reporters.length;
            for (uint256 i = 0; i < n; i++) {
                if (reporters[i] == reporter) {
                    reporters[i] = reporters[n - 1];
                    reporters.pop();
                    break;
                }
            }
            require(quorum <= reporters.length, 'KurPriceFeed: QUORUM_TOO_HIGH');
            emit NewReporter(reporter, false);
        }
    }

    function setQuorum(uint256 newQuorum) external onlyOwner {
        require(newQuorum > 0 && newQuorum <= reporters.length, 'KurPriceFeed: BAD_QUORUM');
        quorum = newQuorum;
        emit QuorumUpdated(newQuorum);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), 'KurPriceFeed: ZERO_ADDRESS');
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ─── Internos ───────────────────────────────────────────────

    function _addReporter(address reporter) private {
        require(reporter != address(0), 'KurPriceFeed: ZERO_ADDRESS');
        require(!isReporter[reporter], 'KurPriceFeed: REPORTER_EXISTS');
        isReporter[reporter] = true;
        reporters.push(reporter);
        emit NewReporter(reporter, true);
    }

    /// @dev Mediana dos envios da rodada. Com N par, a média dos dois centrais.
    function _median(uint80 roundId, uint256 n) private view returns (int256) {
        int256[] memory values = new int256[](n);
        address[] storage subs = _submitters[roundId];
        for (uint256 i = 0; i < n; i++) {
            values[i] = _submission[roundId][subs[i]];
        }
        // insertion sort (N é pequeno: número de reporters)
        for (uint256 i = 1; i < n; i++) {
            int256 key = values[i];
            uint256 j = i;
            while (j > 0 && values[j - 1] > key) {
                values[j] = values[j - 1];
                j -= 1;
            }
            values[j] = key;
        }
        if (n % 2 == 1) {
            return values[n / 2];
        }
        return (values[n / 2 - 1] + values[n / 2]) / 2;
    }
}
