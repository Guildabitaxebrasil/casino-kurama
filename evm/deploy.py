"""
Implantação (deploy) dos contratos DeFi da KuramaChain (Fases 3 e 4).

Os testes montam a codificação ABI dos construtores à mão; estes helpers são o
caminho suportado para subir os contratos fora dos testes, aplicando os
defaults de ``config`` (``EVM_ORACLE_*`` / ``EVM_LENDING_*``):

Oráculo (Fase 3)::

    from evm.deploy import deploy_price_feed, deploy_oracle

    _, feed = deploy_price_feed(engine)                  # quorum/reporter do config
    _, oracle = deploy_oracle(engine, pair='0x...', feed=feed)

Lending (Fase 4)::

    from evm.deploy import (deploy_lending_pool, deploy_price_oracle,
                            init_reserve)

    _, prices = deploy_price_oracle(engine)              # maxAge do config
    _, pool = deploy_lending_pool(engine, prices)        # taxas/closeFactor do config
    _, (aToken, debtToken) = init_reserve(engine, pool, asset)  # LTV/limiar/bônus do config

Staking (Fase 5)::

    from evm.deploy import deploy_staking, create_staking_pool, fund_staking_pool

    _, staking = deploy_staking(engine)
    _, pid = create_staking_pool(engine, staking, kur, kur, rate, end)
    fund_staking_pool(engine, staking, pid, 1_000 * 10**18)

Bridge (Fase 5)::

    from evm.deploy import deploy_bridge, deploy_wrapped_token, register_wrapped

    _, bridge = deploy_bridge(engine)                    # validadores/threshold do config
    _, wrapped = deploy_wrapped_token(engine, 'Wrapped ETH', 'wETH', bridge)
    register_wrapped(engine, bridge, 1, remote_token, wrapped)
"""
import functools
import logging
import os
from typing import Dict, List, Optional, Sequence, Tuple

from eth_keys import keys
from eth_utils import keccak

from config import (
    EVM_BRIDGE_PRIVATE_KEY,
    EVM_BRIDGE_THRESHOLD,
    EVM_BRIDGE_VALIDATOR_KEYS,
    EVM_CHAIN_ID,
    EVM_DEV_PRIVATE_KEY,
    EVM_LENDING_BASE_RATE_APR,
    EVM_LENDING_CLOSE_FACTOR_BPS,
    EVM_LENDING_LIQ_BONUS_BPS,
    EVM_LENDING_LIQ_THRESHOLD_BPS,
    EVM_LENDING_LTV_BPS,
    EVM_LENDING_OPTIMAL_UTILIZATION_PCT,
    EVM_LENDING_PRICE_MAX_AGE,
    EVM_LENDING_RESERVE_FACTOR_BPS,
    EVM_LENDING_SLOPE1_APR,
    EVM_LENDING_SLOPE2_APR,
    EVM_ORACLE_MAX_AGE,
    EVM_ORACLE_PERIOD,
    EVM_ORACLE_PRIVATE_KEY,
    EVM_ORACLE_QUORUM,
    EVM_STAKING_PRIVATE_KEY,
)
from evm.compiler import compile_all

logger = logging.getLogger(__name__)

CONTRACTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contracts')
DEFAULT_PRICE_FEED_DESCRIPTION = 'KUR/USD'
ZERO_ADDRESS = '0x' + '00' * 20


# ─── Helpers de chave / ABI ──────────────────────────────────────

def _strip_hex(value: str) -> str:
    return value[2:] if value.startswith('0x') else value


def address_of(private_key: str) -> str:
    """Endereço EVM (``0x...``) derivado de uma chave privada."""
    priv = keys.PrivateKey(bytes.fromhex(_strip_hex(private_key)))
    return '0x' + priv.public_key.to_address()[2:]


def _encode_address(address) -> bytes:
    if isinstance(address, (bytes, bytearray)):
        return bytes(address).rjust(32, b'\x00')
    return bytes.fromhex(_strip_hex(address)).rjust(32, b'\x00')


def _selector(signature: str) -> bytes:
    """Assinatura de função → seletor de 4 bytes."""
    return keccak(text=signature)[:4]


def _decode_address(data, slot: int = 0) -> str:
    """Lê o endereço (últimos 20 bytes) da palavra `slot` de um retorno ABI."""
    data = bytes(data)
    return '0x' + data[slot * 32 + 12: slot * 32 + 32].hex()


def _encode_string(value: str) -> bytes:
    data = value.encode()
    pad = (32 - len(data) % 32) % 32
    return len(data).to_bytes(32, 'big') + data + b'\x00' * pad


def _encode_price_feed_constructor(description: str, quorum: int,
                                   reporters: Sequence[str]) -> bytes:
    """ABI-encoda ``(string, uint256, address[])`` do KurPriceFeed."""
    desc = _encode_string(description)
    array = (len(reporters).to_bytes(32, 'big')
             + b''.join(_encode_address(r) for r in reporters))
    return ((3 * 32).to_bytes(32, 'big')                 # offset da string
            + int(quorum).to_bytes(32, 'big')            # quorum (estático)
            + (3 * 32 + len(desc)).to_bytes(32, 'big')   # offset do array
            + desc + array)


# ─── Compilação (uma vez por processo) ───────────────────────────

@functools.lru_cache(maxsize=1)
def load_oracle_contracts() -> Dict[str, Dict[str, Dict[str, object]]]:
    """Compila os contratos do oráculo e devolve ``{arquivo: {contrato: ...}}``."""
    return _load_contracts(('KurPriceFeed.sol', 'KurOracle.sol'))


@functools.lru_cache(maxsize=1)
def load_lending_contracts() -> Dict[str, Dict[str, Dict[str, object]]]:
    """
    Compila os contratos do mercado de empréstimos (Fase 4).

    Inclui ``KurPriceFeed.sol`` (interface AggregatorV3) e ``KurScaledToken.sol``
    porque ``KurPriceOracle``/``KurLendingPool`` os importam.
    """
    return _load_contracts(('KurPriceFeed.sol', 'KurPriceOracle.sol',
                            'KurScaledToken.sol', 'KurLendingPool.sol'))


def _load_contracts(names: Sequence[str]) -> Dict[str, Dict[str, Dict[str, object]]]:
    """Compila os arquivos ``.sol`` informados (resolvendo os imports entre eles)."""
    sources = {}
    for name in names:
        with open(os.path.join(CONTRACTS_DIR, name), encoding='utf-8') as fh:
            sources[name] = fh.read()
    artifacts = compile_all(sources)
    logger.debug('[deploy] %s compilados', ', '.join(names))
    return artifacts


# ─── Deploy ──────────────────────────────────────────────────────

def deploy_price_feed(engine, description: str = DEFAULT_PRICE_FEED_DESCRIPTION,
                      quorum: Optional[int] = None,
                      reporters: Optional[Sequence[str]] = None,
                      private_key: Optional[str] = None,
                      gas: int = 5_000_000) -> Tuple[str, str]:
    """
    Implanta um ``KurPriceFeed`` (feed AggregatorV3).

    Args:
        engine: instância de ``EVMEngine``.
        description: descrição do feed (ex.: ``'KUR/USD'``).
        quorum: reporters necessários para fechar uma rodada
            (default: ``config.EVM_ORACLE_QUORUM``).
        reporters: endereços autorizados (default: o reporter derivado de
            ``config.EVM_ORACLE_PRIVATE_KEY``).
        private_key: chave que assina o deploy (default: chave de dev).
        gas: limite de gas do deploy.

    Returns:
        ``(tx_hash, endereço do feed)``
    """
    artifact = load_oracle_contracts()['KurPriceFeed.sol']['KurPriceFeed']
    quorum = EVM_ORACLE_QUORUM if quorum is None else quorum
    if reporters is None:
        reporters = [address_of(EVM_ORACLE_PRIVATE_KEY)]
    args = _encode_price_feed_constructor(description, quorum, list(reporters))
    return engine.deploy(artifact['bytecode'] + args,
                         private_key or EVM_DEV_PRIVATE_KEY, gas=gas)


def deploy_oracle(engine, pair, feed: str = ZERO_ADDRESS,
                  period: Optional[int] = None, max_age: Optional[int] = None,
                  private_key: Optional[str] = None,
                  gas: int = 5_000_000) -> Tuple[str, str]:
    """
    Implanta um ``KurOracle`` (TWAP do par + fallback do feed).

    Args:
        engine: instância de ``EVMEngine``.
        pair: endereço do par de liquidez (``KurPair``) usado na TWAP.
        feed: endereço do ``KurPriceFeed`` (default: sem feed — só TWAP).
        period: janela mínima (s) da TWAP (default: ``config.EVM_ORACLE_PERIOD``).
        max_age: idade máxima (s) do preço do feed antes do fallback
            (default: ``config.EVM_ORACLE_MAX_AGE``).
        private_key: chave que assina o deploy (default: chave de dev).
        gas: limite de gas do deploy.

    Returns:
        ``(tx_hash, endereço do oráculo)``
    """
    artifact = load_oracle_contracts()['KurOracle.sol']['KurOracle']
    period = EVM_ORACLE_PERIOD if period is None else period
    max_age = EVM_ORACLE_MAX_AGE if max_age is None else max_age
    args = (_encode_address(pair) + _encode_address(feed)
            + int(period).to_bytes(32, 'big') + int(max_age).to_bytes(32, 'big'))
    return engine.deploy(artifact['bytecode'] + args,
                         private_key or EVM_DEV_PRIVATE_KEY, gas=gas)


# ─── Deploy: lending (Fase 4) ────────────────────────────────────

def _apr_pct_to_bps(apr_pct) -> int:
    """Converte uma APR em % (ex.: 4.0) para bps (400)."""
    return int(round(float(apr_pct) * 100))


def deploy_price_oracle(engine, max_age: Optional[int] = None,
                        private_key: Optional[str] = None,
                        gas: int = 3_000_000) -> Tuple[str, str]:
    """
    Implanta o ``KurPriceOracle`` (registro asset → feed AggregatorV3).

    Args:
        engine: instância de ``EVMEngine``.
        max_age: idade máxima (s) do preço aceita pelo pool
            (default: ``config.EVM_LENDING_PRICE_MAX_AGE``).
        private_key: chave que assina o deploy (default: chave de dev).
        gas: limite de gas do deploy.

    Returns:
        ``(tx_hash, endereço do price oracle)``
    """
    artifact = load_lending_contracts()['KurPriceOracle.sol']['KurPriceOracle']
    max_age = EVM_LENDING_PRICE_MAX_AGE if max_age is None else max_age
    args = int(max_age).to_bytes(32, 'big')
    return engine.deploy(artifact['bytecode'] + args,
                         private_key or EVM_DEV_PRIVATE_KEY, gas=gas)


def deploy_lending_pool(engine, price_oracle, private_key: Optional[str] = None,
                        base_apr_pct=None, slope1_apr_pct=None, slope2_apr_pct=None,
                        optimal_utilization_pct=None, close_factor_bps: Optional[int] = None,
                        gas: int = 25_000_000) -> Tuple[str, str]:
    """
    Implanta o ``KurLendingPool`` com o modelo de juros/closeFactor do ``config``.

    Args:
        engine: instância de ``EVMEngine``.
        price_oracle: endereço do ``KurPriceOracle`` já implantado.
        private_key: chave que assina o deploy (default: chave de dev).
        base_apr_pct: juros base em % a.a. (default: ``EVM_LENDING_BASE_RATE_APR``).
        slope1_apr_pct: inclinação 1 em % a.a. (default: ``EVM_LENDING_SLOPE1_APR``).
        slope2_apr_pct: inclinação 2 em % a.a. (default: ``EVM_LENDING_SLOPE2_APR``).
        optimal_utilization_pct: utilização ótima em %
            (default: ``EVM_LENDING_OPTIMAL_UTILIZATION_PCT``).
        close_factor_bps: fração máxima liquidável (default:
            ``EVM_LENDING_CLOSE_FACTOR_BPS``).
        gas: limite de gas do deploy (o pool embute o aToken/debtToken).

    Returns:
        ``(tx_hash, endereço do pool)``
    """
    artifact = load_lending_contracts()['KurLendingPool.sol']['KurLendingPool']
    base = EVM_LENDING_BASE_RATE_APR if base_apr_pct is None else base_apr_pct
    slope1 = EVM_LENDING_SLOPE1_APR if slope1_apr_pct is None else slope1_apr_pct
    slope2 = EVM_LENDING_SLOPE2_APR if slope2_apr_pct is None else slope2_apr_pct
    optimal = (EVM_LENDING_OPTIMAL_UTILIZATION_PCT
               if optimal_utilization_pct is None else optimal_utilization_pct)
    close = (EVM_LENDING_CLOSE_FACTOR_BPS
             if close_factor_bps is None else close_factor_bps)
    args = (_encode_address(price_oracle)
            + _apr_pct_to_bps(base).to_bytes(32, 'big')
            + _apr_pct_to_bps(slope1).to_bytes(32, 'big')
            + _apr_pct_to_bps(slope2).to_bytes(32, 'big')
            + int(round(float(optimal) * 100)).to_bytes(32, 'big')
            + int(close).to_bytes(32, 'big'))
    return engine.deploy(artifact['bytecode'] + args,
                         private_key or EVM_DEV_PRIVATE_KEY, gas=gas)


def init_reserve(engine, pool, asset, ltv: Optional[int] = None,
                 liquidation_threshold: Optional[int] = None,
                 liquidation_bonus: Optional[int] = None,
                 reserve_factor: Optional[int] = None,
                 private_key: Optional[str] = None,
                 gas: int = 10_000_000) -> Tuple[str, Tuple[str, str]]:
    """
    Abre o mercado de um ativo no pool (aplica os defaults ``EVM_LENDING_*``).

    Args:
        engine: instância de ``EVMEngine``.
        pool: endereço do ``KurLendingPool``.
        asset: endereço do ERC-20 (precisa ter ``symbol()``/``decimals()``).
        ltv: LTV inicial em bps (default: ``EVM_LENDING_LTV_BPS``).
        liquidation_threshold: limiar de liquidação em bps
            (default: ``EVM_LENDING_LIQ_THRESHOLD_BPS``).
        liquidation_bonus: bônus do liquidante em bps
            (default: ``EVM_LENDING_LIQ_BONUS_BPS``).
        reserve_factor: parte dos juros do protocolo em bps
            (default: ``EVM_LENDING_RESERVE_FACTOR_BPS``).
        private_key: chave que assina a transação (default: chave de dev).
        gas: limite de gas (cria os dois tokens da reserva).

    Returns:
        ``(tx_hash, (aToken, debtToken))``
    """
    ltv = EVM_LENDING_LTV_BPS if ltv is None else ltv
    threshold = (EVM_LENDING_LIQ_THRESHOLD_BPS
                 if liquidation_threshold is None else liquidation_threshold)
    bonus = EVM_LENDING_LIQ_BONUS_BPS if liquidation_bonus is None else liquidation_bonus
    factor = (EVM_LENDING_RESERVE_FACTOR_BPS
              if reserve_factor is None else reserve_factor)
    data = (_selector('initReserve(address,uint16,uint16,uint16,uint16)')
            + _encode_address(asset)
            + int(ltv).to_bytes(32, 'big')
            + int(threshold).to_bytes(32, 'big')
            + int(bonus).to_bytes(32, 'big')
            + int(factor).to_bytes(32, 'big'))
    tx = engine.send(private_key or EVM_DEV_PRIVATE_KEY, pool, data, gas=gas)

    # Os endereços do aToken/debtToken ficam nas duas primeiras palavras do
    # retorno de getReserveConfigurationData(asset).
    out = engine.call(pool, _selector('getReserveConfigurationData(address)')
                      + _encode_address(asset))
    return tx, (_decode_address(out, 0), _decode_address(out, 1))


# ─── Deploy: staking (Fase 5) ────────────────────────────────────

@functools.lru_cache(maxsize=1)
def load_staking_contracts() -> Dict[str, Dict[str, Dict[str, object]]]:
    """Compila os contratos de staking (Fase 5)."""
    return _load_contracts(('KurStaking.sol',))


def deploy_staking(engine, private_key: Optional[str] = None,
                   gas: int = 5_000_000) -> Tuple[str, str]:
    """
    Implanta o ``KurStaking`` (pools de staking/farming).

    Returns:
        ``(tx_hash, endereço do contrato)``
    """
    artifact = load_staking_contracts()['KurStaking.sol']['KurStaking']
    tx, address = engine.deploy(artifact['bytecode'],
                                private_key or EVM_STAKING_PRIVATE_KEY, gas=gas)
    _require_code(engine, address, 'KurStaking')
    return tx, address


def create_staking_pool(engine, staking: str, staking_token: str,
                        reward_token: str, reward_rate: int, reward_end: int,
                        private_key: Optional[str] = None,
                        gas: int = 1_000_000) -> Tuple[str, int]:
    """
    Cria um pool de staking e devolve o ``pid`` (índice do pool).

    Args:
        engine: instância de ``EVMEngine``.
        staking: endereço do ``KurStaking``.
        staking_token: token depositado (KUR, LP token...).
        reward_token: token pago como recompensa.
        reward_rate: recompensa por segundo (unidades do reward_token).
        reward_end: timestamp em que a emissão termina.
        private_key: chave do owner do contrato (default: chave de staking).

    Returns:
        ``(tx_hash, pid)``
    """
    before = _uint_word(engine.call(staking, _selector('poolCount()')))
    data = (_selector('createPool(address,address,uint256,uint256)')
            + _encode_address(staking_token)
            + _encode_address(reward_token)
            + int(reward_rate).to_bytes(32, 'big')
            + int(reward_end).to_bytes(32, 'big'))
    tx = _send_checked(engine, private_key or EVM_STAKING_PRIVATE_KEY, staking, data, gas)
    return tx, before


def fund_staking_pool(engine, staking: str, pid: int, amount: int,
                      private_key: Optional[str] = None,
                      gas: int = 1_000_000) -> Tuple[str, str]:
    """
    Abastece um pool com o token de recompensa.

    Requer ``approve(staking, amount)`` antes, feito pela conta que assina.

    Returns:
        ``(tx_hash, endereço do contrato)``
    """
    data = (_selector('fundPool(uint256,uint256)')
            + int(pid).to_bytes(32, 'big')
            + int(amount).to_bytes(32, 'big'))
    tx = _send_checked(engine, private_key or EVM_STAKING_PRIVATE_KEY, staking, data, gas)
    return tx, staking


# ─── Deploy: bridge (Fase 5) ─────────────────────────────────────

@functools.lru_cache(maxsize=1)
def load_bridge_contracts() -> Dict[str, Dict[str, Dict[str, object]]]:
    """Compila os contratos do bridge e do token wrapped (Fase 5)."""
    return _load_contracts(('KurBridge.sol', 'KurWrappedToken.sol'))


def deploy_bridge(engine, chain_id: Optional[int] = None,
                  validators: Optional[Sequence[str]] = None,
                  threshold: Optional[int] = None,
                  private_key: Optional[str] = None,
                  gas: int = 5_000_000) -> Tuple[str, str]:
    """
    Implanta um ``KurBridge`` (lock/mint com validadores m-de-n).

    Args:
        engine: instância de ``EVMEngine``.
        chain_id: chain ID **desta** rede (default: ``config.EVM_CHAIN_ID``).
        validators: endereços autorizados (default: derivados de
            ``config.EVM_BRIDGE_VALIDATOR_KEYS``).
        threshold: assinaturas necessárias (default: ``EVM_BRIDGE_THRESHOLD``).
        private_key: chave que assina o deploy (default: chave do bridge).

    Returns:
        ``(tx_hash, endereço do bridge)``
    """
    artifact = load_bridge_contracts()['KurBridge.sol']['KurBridge']
    chain_id = EVM_CHAIN_ID if chain_id is None else chain_id
    if validators is None:
        validators = [address_of(key) for key in EVM_BRIDGE_VALIDATOR_KEYS]
    threshold = EVM_BRIDGE_THRESHOLD if threshold is None else threshold
    validators = list(validators)
    array = (len(validators).to_bytes(32, 'big')
             + b''.join(_encode_address(v) for v in validators))
    args = (int(chain_id).to_bytes(32, 'big')      # param 0 (estático)
            + (96).to_bytes(32, 'big')             # offset do array
            + int(threshold).to_bytes(32, 'big')   # param 2 (estático)
            + array)
    tx, address = engine.deploy(artifact['bytecode'] + args,
                                private_key or EVM_BRIDGE_PRIVATE_KEY, gas=gas)
    _require_code(engine, address, 'KurBridge')
    return tx, address


def deploy_wrapped_token(engine, name: str, symbol: str, bridge: str,
                         private_key: Optional[str] = None,
                         gas: int = 3_000_000) -> Tuple[str, str]:
    """
    Implanta um ``KurWrappedToken`` cujo único ``minter``/``burner`` é o bridge.

    Returns:
        ``(tx_hash, endereço do token wrapped)``
    """
    artifact = load_bridge_contracts()['KurWrappedToken.sol']['KurWrappedToken']
    name_enc = _encode_string(name)
    symbol_enc = _encode_string(symbol)
    args = ((3 * 32).to_bytes(32, 'big')                  # offset do name
            + (3 * 32 + len(name_enc)).to_bytes(32, 'big')  # offset do symbol
            + _encode_address(bridge)
            + name_enc + symbol_enc)
    tx, address = engine.deploy(artifact['bytecode'] + args,
                                private_key or EVM_BRIDGE_PRIVATE_KEY, gas=gas)
    _require_code(engine, address, 'KurWrappedToken')
    return tx, address


def register_wrapped(engine, bridge: str, remote_chain: int, remote_token: str,
                     wrapped_token: str, private_key: Optional[str] = None,
                     gas: int = 500_000) -> str:
    """
    Registra o mapeamento ``(chain remota, token remoto) → wrapped local``.

    Returns:
        Hash da transação.
    """
    data = (_selector('registerWrapped(uint256,address,address)')
            + int(remote_chain).to_bytes(32, 'big')
            + _encode_address(remote_token)
            + _encode_address(wrapped_token))
    return _send_checked(engine, private_key or EVM_BRIDGE_PRIVATE_KEY, bridge, data, gas)


def register_release(engine, bridge: str, remote_chain: int, remote_token: str,
                     local_token: str, private_key: Optional[str] = None,
                     gas: int = 500_000) -> str:
    """
    Mapeia ``(chain remota, token remoto) → ativo local liberado no saque``.

    Use no caminho de volta: o token nasceu nesta chain (ex.: KUR) e foi
    representado como wrapped na chain remota; ao queimar o wrapped lá, o
    saque aqui libera o KUR travado.

    Returns:
        Hash da transação.
    """
    data = (_selector('registerRelease(uint256,address,address)')
            + int(remote_chain).to_bytes(32, 'big')
            + _encode_address(remote_token)
            + _encode_address(local_token))
    return _send_checked(engine, private_key or EVM_BRIDGE_PRIVATE_KEY, bridge, data, gas)


def _require_code(engine, address: str, name: str) -> None:
    """Garante que o deploy realmente publicou código (construtor não reverteu)."""
    if not engine.get_code(address):
        raise RuntimeError(f'deploy de {name} falhou (sem código em {address})')


def _uint_word(data) -> int:
    """Lê um uint256 (primeira palavra) de um retorno ABI."""
    data = bytes(data)
    return int.from_bytes(data[:32], 'big') if data else 0


def _send_checked(engine, private_key: str, to: str, data: bytes, gas: int) -> str:
    """Envia uma transação e levanta se ela reverter (status != 1)."""
    tx = engine.send(private_key, to, data, gas=gas)
    receipt = engine.get_transaction_receipt(tx) or {}
    if int(receipt.get('status', '0x0'), 16) != 1:
        raise RuntimeError(f'transação revertida ({tx})')
    return tx


# ─── Ações de staking (Fase 5) ───────────────────────────────────

def stake_tokens(engine, staking: str, pid: int, amount: int,
                 private_key: Optional[str] = None,
                 gas: int = 800_000) -> str:
    """Faz ``stake(pid, amount)`` (requer ``approve(staking, amount)`` antes)."""
    data = (_selector('stake(uint256,uint256)')
            + int(pid).to_bytes(32, 'big')
            + int(amount).to_bytes(32, 'big'))
    return _send_checked(engine, private_key or EVM_DEV_PRIVATE_KEY, staking, data, gas)


def unstake_tokens(engine, staking: str, pid: int, amount: int,
                   private_key: Optional[str] = None,
                   gas: int = 800_000) -> str:
    """Faz ``withdraw(pid, amount)`` (devolve o principal; use ``claim`` p/ prêmio)."""
    data = (_selector('withdraw(uint256,uint256)')
            + int(pid).to_bytes(32, 'big')
            + int(amount).to_bytes(32, 'big'))
    return _send_checked(engine, private_key or EVM_DEV_PRIVATE_KEY, staking, data, gas)


def claim_rewards(engine, staking: str, pid: int,
                  private_key: Optional[str] = None,
                  gas: int = 800_000) -> str:
    """Faz ``claim(pid)`` e paga as recompensas acumuladas."""
    data = _selector('claim(uint256)') + int(pid).to_bytes(32, 'big')
    return _send_checked(engine, private_key or EVM_DEV_PRIVATE_KEY, staking, data, gas)


# ─── Ações do bridge (Fase 5) ────────────────────────────────────

def bridge_deposit(engine, bridge: str, token: str, amount: int, dest_chain: int,
                   recipient: str, private_key: Optional[str] = None,
                   gas: int = 500_000) -> str:
    """
    Trava (ou queima) `amount` no bridge rumo à `dest_chain`.

    Requer ``approve(bridge, amount)`` quando o token não for wrapped.
    """
    data = (_selector('deposit(address,uint256,uint256,address)')
            + _encode_address(token)
            + int(amount).to_bytes(32, 'big')
            + int(dest_chain).to_bytes(32, 'big')
            + _encode_address(recipient))
    return _send_checked(engine, private_key or EVM_DEV_PRIVATE_KEY, bridge, data, gas)
