"""
Nó oráculo da KuramaChain (Fase 3 — Oráculo).

Um **nó oráculo** obtém um preço fora da cadeia (API de mercado, outra
exchange, etc.) e o publica on-chain no ``KurPriceFeed``, que agrega os
envios de todos os reporters (mediana + quórum). Contratos consumidores leem
o preço agregado — ou caem no fallback TWAP da DEX via ``KurOracle``.

Fluxo:

    1. ``source`` → preço off-chain (ex.: 2500.00 USD)
    2. validação de desvio (anti "fat finger") contra o último preço on-chain
    3. ``feed.submit(preço)`` assinado com a chave do reporter
    4. quando o quórum de reporters é atingido, o feed fecha a rodada

Uso típico::

    from evm.engine import EVMEngine
    from evm.oracle_node import KurOracleNode, HttpJsonPriceSource

    engine = EVMEngine()
    node = KurOracleNode(
        engine=engine,
        feed='0x<endereco do KurPriceFeed>',
        private_key='0x<chave do reporter>',
        source=HttpJsonPriceSource(
            'https://api.coingecko.com/api/v3/simple/price?ids=kusama&vs_currencies=usd',
            ['kusama', 'usd'],
        ),
    )
    node.publish_once()          # publica uma vez
    node.run(interval=60)        # loop contínuo

.. note::
   O nó publica **em processo**, usando o ``EVMEngine`` — a chave do reporter
   assina a transação pela própria engine (mesmo caminho de ``run.py``). Um nó
   oráculo externo que fale apenas JSON-RPC precisaria de um assinador próprio
   (``eth-account``) e de ``eth_sendRawTransaction``.
"""
import logging
import random
import time
from typing import Callable, Dict, List, Optional, Sequence

from eth_utils import keccak

from config import (
    EVM_ORACLE_INTERVAL,
    EVM_ORACLE_MAX_DEVIATION_PCT,
    EVM_ORACLE_PRIVATE_KEY,
)

logger = logging.getLogger(__name__)

#: Casas decimais do preço on-chain (padrão dos feeds USD da Chainlink).
DECIMALS = 8
ONE = 10 ** DECIMALS

_SEL_SUBMIT = keccak(text='submit(int256)')[:4]
_SEL_IS_REPORTER = keccak(text='isReporter(address)')[:4]
_SEL_LATEST_ROUND = keccak(text='latestRound()')[:4]
_SEL_LATEST_ROUND_DATA = keccak(text='latestRoundData()')[:4]


# ─── Helpers ABI ─────────────────────────────────────────────────

def to_units(price: float) -> int:
    """Converte um preço decimal (ex.: ``2500.42``) para 8 decimais."""
    return int(round(float(price) * ONE))


def from_units(value: int) -> float:
    """Converte um preço de 8 decimais para decimal (ex.: ``2500.42``)."""
    return value / ONE


def _enc_int256(value: int) -> bytes:
    return (value % (2 ** 256)).to_bytes(32, 'big')


def _enc_address(address: str) -> bytes:
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _word(data: bytes, index: int) -> bytes:
    return bytes(data)[index * 32:(index + 1) * 32]


def _uint(data: bytes, index: int) -> int:
    return int.from_bytes(_word(data, index), 'big')


def _int(data: bytes, index: int) -> int:
    return int.from_bytes(_word(data, index), 'big', signed=True)


def decode_round_data(out: bytes) -> Dict[str, int]:
    """
    Decodifica o retorno ABI de ``latestRoundData()``/``getRoundData(uint80)``.

    Returns:
        ``{'roundId', 'answer', 'startedAt', 'updatedAt', 'answeredInRound'}``
    """
    if len(out) < 5 * 32:
        raise ValueError(f'Retorno ABI curto para roundData: {len(out)} bytes')
    return {
        'roundId': _uint(out, 0),
        'answer': _int(out, 1),
        'startedAt': _uint(out, 2),
        'updatedAt': _uint(out, 3),
        'answeredInRound': _uint(out, 4),
    }


# ─── Fontes de preço off-chain ───────────────────────────────────

class PriceSource:
    """Interface de uma fonte de preço off-chain (retorna preço em 8 decimais)."""

    def get_price(self) -> int:
        raise NotImplementedError


class FixedPriceSource(PriceSource):
    """Fonte fixa — útil em testes e demos."""

    def __init__(self, price: float):
        self.price = price

    def get_price(self) -> int:
        return to_units(self.price)


class RandomWalkSource(PriceSource):
    """Passeio aleatório em torno de um preço — simulação de mercado (demo)."""

    def __init__(self, start: float, volatility: float = 0.01,
                 seed: Optional[int] = None):
        self.value = float(start)
        self.volatility = float(volatility)
        self._rng = random.Random(seed)

    def get_price(self) -> int:
        self.value = max(0.01, self.value * (1 + self._rng.uniform(-self.volatility,
                                                                  self.volatility)))
        return to_units(self.value)


class HttpJsonPriceSource(PriceSource):
    """
    Fonte HTTP/JSON: busca o preço em uma API pública.

    Args:
        url: endpoint que devolve JSON.
        path: caminho das chaves até o número, ex.: ``['kusama', 'usd']``.
        timeout: timeout da requisição (s).

    Exemplo (CoinGecko)::

        HttpJsonPriceSource(
            'https://api.coingecko.com/api/v3/simple/price?ids=kusama&vs_currencies=usd',
            ['kusama', 'usd'],
        )
    """

    def __init__(self, url: str, path: Sequence[str], timeout: float = 5.0):
        self.url = url
        self.path: List[str] = list(path)
        self.timeout = timeout

    def get_price(self) -> int:
        import requests  # import tardio: a lib só é necessária nesta fonte

        resp = requests.get(self.url, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        for key in self.path:
            data = data[key]
        return to_units(float(data))


# ─── Erros ───────────────────────────────────────────────────────

class PriceDeviationError(ValueError):
    """Preço fora da banda de desvio aceitável em relação ao último on-chain."""


class NotAuthorizedError(RuntimeError):
    """A chave configurada não é reporter autorizado no feed."""


# ─── Nó oráculo ──────────────────────────────────────────────────

class KurOracleNode:
    """
    Nó oráculo: obtém o preço off-chain e publica no feed on-chain.

    Args:
        engine: instância de ``EVMEngine`` (assina e envia a transação).
        feed: endereço ``0x...`` do ``KurPriceFeed``.
        private_key: chave do reporter (default: ``config``). Deve estar
            autorizada no feed (``isReporter``).
        source: fonte de preço; default: passeio aleatório a partir de 1.0.
        max_deviation_pct: desvio máximo (%) aceito vs. último preço on-chain.
            ``None`` ou ``0`` desativa a checagem.
    """

    def __init__(self, engine, feed: str, private_key: Optional[str] = None,
                 source: Optional[PriceSource] = None,
                 max_deviation_pct: Optional[int] = None):
        from eth_keys import keys  # import local: evita custo no import do módulo

        self.engine = engine
        self.feed = feed
        self.private_key = private_key or EVM_ORACLE_PRIVATE_KEY
        self.source = source or RandomWalkSource(1.0)
        self.max_deviation_pct = (
            EVM_ORACLE_MAX_DEVIATION_PCT if max_deviation_pct is None
            else max_deviation_pct
        )
        priv = keys.PrivateKey(bytes.fromhex(
            self.private_key[2:] if self.private_key.startswith('0x')
            else self.private_key
        ))
        self.reporter = '0x' + priv.public_key.to_address()[2:]

    # ─── Leitura on-chain ────────────────────────────────────────

    def is_authorized(self) -> bool:
        """True se ``reporter`` está autorizado a publicar neste feed."""
        out = self.engine.call(self.feed, _SEL_IS_REPORTER + _enc_address(self.reporter))
        return _uint(out, 0) != 0

    def on_chain_round(self) -> Optional[Dict[str, int]]:
        """
        Última rodada fechada no feed.

        Returns:
            Dict decodificado, ou ``None`` se nenhuma rodada foi fechada ainda.
        """
        try:
            out = self.engine.call(self.feed, _SEL_LATEST_ROUND_DATA)
        except Exception:
            return None  # feed reverteu: 'NO_DATA'
        try:
            return decode_round_data(out)
        except ValueError:
            return None

    def on_chain_price(self) -> Optional[int]:
        """Último preço publicado (8 decimais) ou ``None``."""
        info = self.on_chain_round()
        return None if info is None else info['answer']

    # ─── Publicação ──────────────────────────────────────────────

    def fetch_price(self) -> int:
        """Obtém o preço da fonte off-chain, validando que é positivo."""
        price = int(self.source.get_price())
        if price <= 0:
            raise ValueError(f'Preço inválido da fonte: {price}')
        return price

    def check_deviation(self, price: int) -> None:
        """Levanta ``PriceDeviationError`` se o preço sair da banda aceitável."""
        pct = self.max_deviation_pct
        if not pct:
            return
        last = self.on_chain_price()
        if not last or last <= 0:
            return
        deviation_pct = abs(price - last) * 100.0 / last
        if deviation_pct > pct:
            raise PriceDeviationError(
                f'Desvio de {deviation_pct:.2f}% excede o limite de {pct}% '
                f'(on-chain={from_units(last)}, novo={from_units(price)})'
            )

    def publish_once(self, price: Optional[int] = None) -> Dict[str, object]:
        """
        Publica um preço no feed (uma rodada pode fechar se o quórum for 1).

        Args:
            price: preço já em 8 decimais (default: lê da fonte off-chain).

        Returns:
            ``{'tx', 'price', 'round', 'reporter'}`` — ``round`` é a rodada
            fechada (dict) ou ``None`` se o quórum ainda não foi atingido.
        """
        if price is None:
            price = self.fetch_price()
        else:
            price = int(price)
        if price <= 0:
            raise ValueError(f'Preço inválido: {price}')

        if not self.is_authorized():
            raise NotAuthorizedError(
                f'Reporter {self.reporter} não está autorizado no feed {self.feed}'
            )
        self.check_deviation(price)

        tx = self.engine.send(
            self.private_key, self.feed, _SEL_SUBMIT + _enc_int256(price)
        )
        receipt = self.engine.get_transaction_receipt(tx) or {}
        status = int(receipt.get('status', '0x0'), 16)
        if status != 1:
            raise RuntimeError(f'Transação do oráculo falhou (status {status}): {tx}')

        round_info = self.on_chain_round()
        logger.info('[oráculo] preço %s publicado por %s (tx %s)',
                    from_units(price), self.reporter, tx)
        return {
            'tx': tx,
            'price': price,
            'reporter': self.reporter,
            'round': round_info,
        }

    def run(self, interval: Optional[float] = None,
            iterations: Optional[int] = None,
            stop_event=None,
            on_tick: Optional[Callable[[Dict[str, object]], None]] = None) -> int:
        """
        Loop de publicação.

        Args:
            interval: segundos entre publicações (default: ``config``).
            iterations: nº de publicações (``None`` = infinito).
            stop_event: ``threading.Event`` para parar o loop.
            on_tick: callback opcional chamado com o resultado de cada tick.

        Returns:
            Número de publicações feitas.
        """
        interval = EVM_ORACLE_INTERVAL if interval is None else interval
        count = 0
        while iterations is None or count < iterations:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                result = self.publish_once()
                count += 1
                if on_tick is not None:
                    on_tick(result)
            except (PriceDeviationError, NotAuthorizedError) as exc:
                logger.warning('[oráculo] publicação recusada: %s', exc)
            except Exception as exc:  # rede/RPC indisponível: tenta no próximo tick
                logger.error('[oráculo] falha ao publicar: %s', exc)

            if iterations is not None and count >= iterations:
                break
            if stop_event is not None:
                if stop_event.wait(interval):
                    break
            else:
                time.sleep(interval)
        return count
