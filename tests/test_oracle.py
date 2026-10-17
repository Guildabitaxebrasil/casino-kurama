"""
Testes do oráculo da KuramaChain (Fase 3).

Cobre:
- ``KurPriceFeed``: feed AggregatorV3 (Chainlink) com quórum e mediana.
- ``KurOracle``: TWAP do par AMM e fallback quando o feed está obsoleto.
- ``evm.oracle_node``: nó oráculo Python (fonte de preço → publicação on-chain).

Executar com: python -m pytest tests/test_oracle.py -v
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.compiler import compile_all
from evm.engine import EVMEngine
from evm.oracle_node import (
    FixedPriceSource,
    KurOracleNode,
    NotAuthorizedError,
    PriceDeviationError,
    RandomWalkSource,
    decode_round_data,
    from_units,
    to_units,
)
from config import EVM_DEV_PRIVATE_KEY

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'evm', 'contracts')

SOURCES = (
    'UQ112x112.sol', 'KurToken.sol', 'KurPair.sol', 'KurFactory.sol',
    'KurPriceFeed.sol', 'KurOracle.sol',
)

REPORTER_KEYS = ['0x' + 'aa' * 32, '0x' + 'bb' * 32, '0x' + 'cc' * 32]
OTHER_KEY = '0x' + 'dd' * 32

USD = 10 ** 8  # 1 unidade de preço com 8 decimais


# ─── Helpers ─────────────────────────────────────────────────────

def _read(name: str) -> str:
    with open(os.path.join(CONTRACTS_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def _sel(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def _addr_of(private_key: str) -> str:
    return '0x' + keys.PrivateKey(
        bytes.fromhex(private_key[2:])).public_key.to_address()[2:]


def _addr_arg(address: str) -> bytes:
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _uint(data: bytes) -> int:
    return int.from_bytes(bytes(data)[:32], 'big')


def _address(data: bytes) -> str:
    return '0x' + bytes(data)[-20:].hex()


def _enc_string(s: str) -> bytes:
    b = s.encode()
    pad = (32 - len(b) % 32) % 32
    return len(b).to_bytes(32, 'big') + b + b'\x00' * pad


def _enc_constructor(name: str, symbol: str, supply: int) -> bytes:
    """ABI-encoda os argumentos ``(string, string, uint256)``."""
    head = ((3 * 32).to_bytes(32, 'big')
            + (3 * 32 + 64).to_bytes(32, 'big')
            + supply.to_bytes(32, 'big'))
    return head + _enc_string(name) + _enc_string(symbol)


def _enc_price_feed_constructor(description: str, quorum: int,
                                reporters: list) -> bytes:
    """ABI-encoda ``(string, uint256, address[])`` do KurPriceFeed."""
    desc = _enc_string(description)
    array = (len(reporters).to_bytes(32, 'big')
             + b''.join(_addr_arg(r) for r in reporters))
    return ((3 * 32).to_bytes(32, 'big')      # offset da string
            + quorum.to_bytes(32, 'big')      # quorum (estático)
            + (3 * 32 + len(desc)).to_bytes(32, 'big')  # offset do array
            + desc + array)


def _make_engine(funded_keys=()) -> EVMEngine:
    """Engine com gênese financiando os endereços das chaves informadas."""
    accounts = {_addr_of(key): 1_000.0 for key in funded_keys}
    return EVMEngine(auto_mine=True, genesis_accounts=accounts)


class _OracleTestBase(unittest.TestCase):
    """Compila os contratos uma única vez para toda a suíte."""

    @classmethod
    def setUpClass(cls):
        cls.artifacts = compile_all({name: _read(name) for name in SOURCES})
        cls.feed_art = cls.artifacts['KurPriceFeed.sol']['KurPriceFeed']
        cls.oracle_art = cls.artifacts['KurOracle.sol']['KurOracle']
        cls.token_art = cls.artifacts['KurToken.sol']['KurToken']
        cls.pair_art = cls.artifacts['KurPair.sol']['KurPair']
        cls.factory_art = cls.artifacts['KurFactory.sol']['KurFactory']

    def _deploy_feed(self, engine, deployer_key, quorum=1, reporters=None,
                     description='KUR/USD'):
        reporters = reporters if reporters is not None else [_addr_of(deployer_key)]
        args = _enc_price_feed_constructor(description, quorum, reporters)
        _, feed = engine.deploy(self.feed_art['bytecode'] + args, deployer_key,
                                gas=5_000_000)
        return feed

    def _latest(self, engine, feed):
        return decode_round_data(engine.call(feed, _sel('latestRoundData()')))

    def _send_revert(self, engine, key, to, data, gas=None):
        """
        Envia uma tx que DEVE reverter e exige recibo com status 0.

        No fork London a tx que reverte é **incluída no bloco** com status 0
        (não é descartada nem levanta exceção) — a falha aparece no recibo.
        """
        tx = engine.send(key, to, data, gas=gas)
        receipt = engine.get_transaction_receipt(tx)
        self.assertIsNotNone(receipt, 'recibo não encontrado para a tx enviada')
        self.assertEqual(int(receipt['status'], 16), 0,
                         'esperava revert (status 0) no recibo')
        return receipt


# ─── Feed de preço (AggregatorV3) ────────────────────────────────

class TestKurPriceFeed(_OracleTestBase):
    """Fase 3 — feed on-chain com reporters, quórum e mediana."""

    def setUp(self):
        self.engine = _make_engine(REPORTER_KEYS + [OTHER_KEY])
        self.key = EVM_DEV_PRIVATE_KEY
        self.deployer = _addr_of(self.key)
        self.reporters = [_addr_of(k) for k in REPORTER_KEYS]

    def _submit(self, engine, key, feed, price):
        return engine.send(key, feed, _sel('submit(int256)')
                           + (price % 2 ** 256).to_bytes(32, 'big'))

    def test_metadata(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self.assertEqual(_uint(self.engine.call(feed, _sel('decimals()'))), 8)
        self.assertEqual(_uint(self.engine.call(feed, _sel('version()'))), 3)
        self.assertEqual(_uint(self.engine.call(feed, _sel('reportersLength()'))), 1)
        # description() é dinâmico: offset + length + bytes
        out = bytes(self.engine.call(feed, _sel('description()')))
        length = int.from_bytes(out[32:64], 'big')
        self.assertEqual(out[64:64 + length].decode(), 'KUR/USD')

    def test_no_round_before_first_price(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self.assertRaises(Exception, self.engine.call, feed,
                          _sel('latestRoundData()'))

    def test_single_reporter_closes_round(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        tx = self._submit(self.engine, self.key, feed, 2500 * USD)
        receipt = self.engine.get_transaction_receipt(tx)
        self.assertEqual(int(receipt['status'], 16), 1)

        data = self._latest(self.engine, feed)
        self.assertEqual(data['roundId'], 1)
        self.assertEqual(data['answer'], 2500 * USD)
        self.assertEqual(data['answeredInRound'], 1)
        self.assertGreater(data['updatedAt'], 0)
        self.assertEqual(_uint(self.engine.call(feed, _sel('latestAnswer()'))),
                         2500 * USD)
        # getRoundData(1) devolve a mesma rodada
        self.assertEqual(
            decode_round_data(self.engine.call(
                feed, _sel('getRoundData(uint80)') + (1).to_bytes(32, 'big'))),
            data)

    def test_price_only_published_when_quorum_reached(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=3,
                                 reporters=self.reporters)
        self._submit(self.engine, REPORTER_KEYS[0], feed, 100 * USD)
        self._submit(self.engine, REPORTER_KEYS[1], feed, 300 * USD)
        # 2 de 3: rodada ainda aberta
        self.assertRaises(Exception, self.engine.call, feed,
                          _sel('latestRoundData()'))

        self._submit(self.engine, REPORTER_KEYS[2], feed, 200 * USD)
        data = self._latest(self.engine, feed)
        self.assertEqual(data['roundId'], 1)
        self.assertEqual(data['answer'], 200 * USD)  # mediana de 100/300/200

    def test_median_of_two_reporters(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=2,
                                 reporters=self.reporters[:2])
        self._submit(self.engine, REPORTER_KEYS[0], feed, 100 * USD)
        self._submit(self.engine, REPORTER_KEYS[1], feed, 101 * USD)
        # média dos dois centrais
        self.assertEqual(self._latest(self.engine, feed)['answer'],
                         (100 * USD + 101 * USD) // 2)

    def test_new_round_after_quorum(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self._submit(self.engine, self.key, feed, 2500 * USD)
        self._submit(self.engine, self.key, feed, 2600 * USD)
        data = self._latest(self.engine, feed)
        self.assertEqual(data['roundId'], 2)
        self.assertEqual(data['answer'], 2600 * USD)
        self.assertEqual(_uint(self.engine.call(feed, _sel('latestRound()'))), 2)

    def test_rejects_non_reporter(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self._send_revert(self.engine, OTHER_KEY, feed,
                          _sel('submit(int256)') + (2500 * USD).to_bytes(32, 'big'))

    def test_rejects_duplicate_submission_in_same_round(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=3,
                                 reporters=self.reporters)
        self._submit(self.engine, REPORTER_KEYS[0], feed, 100 * USD)
        self._send_revert(self.engine, REPORTER_KEYS[0], feed,
                          _sel('submit(int256)') + (101 * USD).to_bytes(32, 'big'))

    def test_rejects_zero_price(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self._send_revert(self.engine, self.key, feed,
                          _sel('submit(int256)') + (0).to_bytes(32, 'big'))

    def test_reverted_tx_does_not_block_next_submission(self):
        """Uma tx que reverte não impede a próxima transação de entrar."""
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self._send_revert(self.engine, OTHER_KEY, feed,
                          _sel('submit(int256)') + (2500 * USD).to_bytes(32, 'big'))
        self._submit(self.engine, self.key, feed, 2500 * USD)
        self.assertEqual(self._latest(self.engine, feed)['answer'], 2500 * USD)
        self.assertEqual(_uint(self.engine.call(feed, _sel('latestRound()'))), 1)

    def test_reporter_and_quorum_admin(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1,
                                 reporters=[self.deployer, self.reporters[0]])
        # remove o reporter externo
        self.engine.send(self.key, feed, _sel('setReporter(address,bool)')
                         + _addr_arg(self.reporters[0]) + (0).to_bytes(32, 'big'))
        self.assertEqual(_uint(self.engine.call(feed, _sel('reportersLength()'))), 1)
        self._send_revert(self.engine, REPORTER_KEYS[0], feed,
                          _sel('submit(int256)') + (2500 * USD).to_bytes(32, 'big'))
        # quorum maior que o nº de reporters é rejeitado
        self._send_revert(self.engine, self.key, feed,
                          _sel('setQuorum(uint256)') + (2).to_bytes(32, 'big'))

    def test_admin_is_owner_only(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        self._send_revert(self.engine, OTHER_KEY, feed,
                          _sel('setQuorum(uint256)') + (1).to_bytes(32, 'big'))


# ─── TWAP da DEX + fallback ──────────────────────────────────────

class TestKurOracle(_OracleTestBase):
    """Fase 3 — TWAP do par AMM e fallback quando o feed está obsoleto."""

    def setUp(self):
        self.engine = _make_engine()
        self.key = EVM_DEV_PRIVATE_KEY
        self.deployer = _addr_of(self.key)

        supply = 1_000_000 * 10 ** 18
        _, self.tokenA = self.engine.deploy(
            self.token_art['bytecode'] + _enc_constructor('Token A', 'TKA', supply),
            self.key, gas=4_000_000)
        _, self.tokenB = self.engine.deploy(
            self.token_art['bytecode'] + _enc_constructor('Token B', 'TKB', supply),
            self.key, gas=4_000_000)
        _, self.factory = self.engine.deploy(self.factory_art['bytecode'],
                                             self.key, gas=5_000_000)
        self.engine.send(self.key, self.factory,
                         _sel('createPair(address,address)')
                         + _addr_arg(self.tokenA) + _addr_arg(self.tokenB))
        out = self.engine.call(self.factory, _sel('getPair(address,address)')
                               + _addr_arg(self.tokenA) + _addr_arg(self.tokenB))
        self.pair = _address(out)
        self.token0 = _address(self.engine.call(self.pair, _sel('token0()')))
        self.token1 = _address(self.engine.call(self.pair, _sel('token1()')))

        # 100k de um token / 200k do outro → preço (token0 em token1) = 2 ou 0.5
        for token, amount in ((self.tokenA, 100_000 * 10 ** 18),
                              (self.tokenB, 200_000 * 10 ** 18)):
            self.engine.send(self.key, token,
                             _sel('transfer(address,uint256)')
                             + _addr_arg(self.pair) + amount.to_bytes(32, 'big'))
        self.engine.send(self.key, self.pair,
                         _sel('mint(address)') + _addr_arg(self.deployer))

    # ─── helpers ─────────────────────────────────────────────────

    def _reserves(self):
        out = bytes(self.engine.call(self.pair, _sel('getReserves()')))
        return int.from_bytes(out[0:32], 'big'), int.from_bytes(out[32:64], 'big')

    def _expected_price8(self):
        """Preço esperado do token0 em token1, em 8 decimais."""
        r0, r1 = self._reserves()
        return r1 * 10 ** 8 // r0

    def _deploy_oracle(self, feed='0x' + '00' * 20, period=1, max_age=3600):
        args = (_addr_arg(self.pair) + _addr_arg(feed)
                + period.to_bytes(32, 'big') + max_age.to_bytes(32, 'big'))
        _, oracle = self.engine.deploy(self.oracle_art['bytecode'] + args,
                                       self.key, gas=5_000_000)
        return oracle

    def _update(self, oracle):
        return self.engine.send(self.key, oracle, _sel('update()'))

    def _get_price(self, oracle):
        out = bytes(self.engine.call(oracle, _sel('getPrice()')))
        return int.from_bytes(out[0:32], 'big'), int.from_bytes(out[32:64], 'big') != 0

    def _feed_submit(self, feed, price, key=None):
        key = key or self.key
        return self.engine.send(key, feed, _sel('submit(int256)')
                                + (price % 2 ** 256).to_bytes(32, 'big'))

    # ─── testes ──────────────────────────────────────────────────

    def test_pair_accumulates_cumulative_prices(self):
        """A liquidez acumula preço ponderado no tempo (base da TWAP)."""
        # O 1º mint não acumula (as reservas ainda eram zero); um novo
        # evento (2º mint proporcional) já acumula preço × tempo.
        for token, amount in ((self.tokenA, 10_000 * 10 ** 18),
                              (self.tokenB, 20_000 * 10 ** 18)):
            self.engine.send(self.key, token,
                             _sel('transfer(address,uint256)')
                             + _addr_arg(self.pair) + amount.to_bytes(32, 'big'))
        self.engine.send(self.key, self.pair,
                         _sel('mint(address)') + _addr_arg(self.deployer))

        c0, c1 = self._cumulatives()
        self.assertGreater(c0, 0)
        self.assertGreater(c1, 0)
        # a liquidez é proporcional (2:1) — a orientação depende da ordem
        # dos endereços no par, logo o preço é 2 USD ou 0.5 USD
        self.assertIn(self._expected_price8(), (2 * 10 ** 8, 5 * 10 ** 7))

    def _cumulatives(self):
        out = bytes(self.engine.call(self.pair, _sel('getCumulativePrices()')))
        return (int.from_bytes(out[0:32], 'big'),
                int.from_bytes(out[32:64], 'big'))

    def test_get_price_without_feed_uses_twap(self):
        oracle = self._deploy_oracle(period=1)
        # antes do primeiro update() a TWAP ainda não existe
        self.assertRaises(Exception, self.engine.call, oracle, _sel('getPrice()'))

        self._update(oracle)
        price, from_feed = self._get_price(oracle)
        self.assertFalse(from_feed)
        self.assertEqual(price, self._expected_price8())
        self.assertTrue(_uint(self.engine.call(oracle, _sel('twapReady()'))) != 0)

    def test_consult_converts_amounts_with_twap(self):
        oracle = self._deploy_oracle(period=1)
        self._update(oracle)
        r0, r1 = self._reserves()
        one = 10 ** 18
        out = self.engine.call(oracle, _sel('consult(address,uint256)')
                               + _addr_arg(self.token0) + one.to_bytes(32, 'big'))
        self.assertEqual(_uint(out), r1 * one // r0)
        # token1 → token0 (preço inverso)
        out = self.engine.call(oracle, _sel('consult(address,uint256)')
                               + _addr_arg(self.token1) + one.to_bytes(32, 'big'))
        self.assertEqual(_uint(out), r0 * one // r1)

    def test_get_price_prefers_fresh_feed(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        oracle = self._deploy_oracle(feed=feed, period=1, max_age=3600)
        self._update(oracle)
        self._feed_submit(feed, 123 * USD)

        price, from_feed = self._get_price(oracle)
        self.assertTrue(from_feed)
        self.assertEqual(price, 123 * USD)
        # o fallback TWAP estaria em 2 USD — logo o preço veio mesmo do feed
        self.assertNotEqual(price, self._expected_price8())
        # feedPrice(): fresco + preço
        out = bytes(self.engine.call(oracle, _sel('feedPrice()')))
        self.assertEqual(int.from_bytes(out[0:32], 'big'), 123 * USD)
        self.assertNotEqual(int.from_bytes(out[64:96], 'big'), 0)

    def test_get_price_falls_back_when_feed_is_stale(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        # maxAge = 0 → o preço do feed só é válido no próprio bloco
        oracle = self._deploy_oracle(feed=feed, period=1, max_age=0)
        self._feed_submit(feed, 123 * USD)
        self._update(oracle)   # novo bloco → feed fica obsoleto
        self._feed_submit(feed, 123 * USD)  # nova rodada, ainda assim obsoleta no próximo bloco
        self._update(oracle)

        # avança um bloco sem publicar nada: o feed envelhece
        self.engine.send(self.key, self.pair, _sel('getReserves()'))

        price, from_feed = self._get_price(oracle)
        self.assertFalse(from_feed)
        self.assertEqual(price, self._expected_price8())

        out = bytes(self.engine.call(oracle, _sel('feedPrice()')))
        self.assertNotEqual(int.from_bytes(out[0:32], 'big'), 0)  # há preço no feed
        self.assertEqual(int.from_bytes(out[64:96], 'big'), 0)    # mas não está fresco

    def test_second_update_matches_constant_reserves(self):
        """Sem swaps, a TWAP acompanha a razão das reservas."""
        oracle = self._deploy_oracle(period=1)
        self._update(oracle)
        first, _ = self._get_price(oracle)
        self._update(oracle)
        second, _ = self._get_price(oracle)
        self.assertEqual(first, self._expected_price8())
        self.assertEqual(second, self._expected_price8())

    def test_update_respects_period(self):
        oracle = self._deploy_oracle(period=1000)
        self._send_revert(self.engine, self.key, oracle, _sel('update()'))

    def test_get_price_reverts_without_any_source(self):
        oracle = self._deploy_oracle()  # sem feed e sem update()
        self.assertRaises(Exception, self.engine.call, oracle, _sel('getPrice()'))

    def test_deploy_helpers_apply_config_defaults(self):
        """Os helpers de deploy (evm/deploy.py) usam os defaults EVM_ORACLE_*."""
        from evm.deploy import address_of, deploy_oracle, deploy_price_feed
        from config import (EVM_ORACLE_MAX_AGE, EVM_ORACLE_PERIOD,
                            EVM_ORACLE_PRIVATE_KEY, EVM_ORACLE_QUORUM)

        tx, feed = deploy_price_feed(self.engine)
        self.assertEqual(
            int(self.engine.get_transaction_receipt(tx)['status'], 16), 1)
        self.assertEqual(_uint(self.engine.call(feed, _sel('quorum()'))),
                         EVM_ORACLE_QUORUM)
        self.assertEqual(_uint(self.engine.call(feed, _sel('reportersLength()'))), 1)
        reporter = address_of(EVM_ORACLE_PRIVATE_KEY)
        self.assertNotEqual(
            _uint(self.engine.call(feed, _sel('isReporter(address)') + _addr_arg(reporter))), 0)

        tx, oracle = deploy_oracle(self.engine, pair=self.pair, feed=feed)
        self.assertEqual(
            int(self.engine.get_transaction_receipt(tx)['status'], 16), 1)
        self.assertEqual(_uint(self.engine.call(oracle, _sel('period()'))),
                         EVM_ORACLE_PERIOD)
        self.assertEqual(_uint(self.engine.call(oracle, _sel('maxAge()'))),
                         EVM_ORACLE_MAX_AGE)
        self.assertEqual(_address(self.engine.call(oracle, _sel('feed()'))),
                         feed.lower())
        self.assertEqual(_address(self.engine.call(oracle, _sel('token0()'))),
                         self.token0.lower())

    def test_set_feed_and_max_age(self):
        feed = self._deploy_feed(self.engine, self.key, quorum=1)
        oracle = self._deploy_oracle(period=1, max_age=3600)
        self._update(oracle)
        self._feed_submit(feed, 250 * USD)
        # sem feed configurado no oráculo, usa a TWAP
        _, from_feed = self._get_price(oracle)
        self.assertFalse(from_feed)
        # aponta o oráculo para o feed → passa a usar o feed
        self.engine.send(self.key, oracle, _sel('setFeed(address)') + _addr_arg(feed))
        price, from_feed = self._get_price(oracle)
        self.assertTrue(from_feed)
        self.assertEqual(price, 250 * USD)
        # maxAge = 0 desativa o feed (fica obsoleto no bloco seguinte)
        self.engine.send(self.key, oracle, _sel('setMaxAge(uint256)') + (0).to_bytes(32, 'big'))
        self.engine.send(self.key, self.pair, _sel('getReserves()'))
        _, from_feed = self._get_price(oracle)
        self.assertFalse(from_feed)


# ─── Nó oráculo Python ───────────────────────────────────────────

class TestOracleNode(_OracleTestBase):
    """Fase 3 — nó Python publicando o preço off-chain no feed."""

    def setUp(self):
        self.engine = _make_engine([OTHER_KEY])
        self.key = EVM_DEV_PRIVATE_KEY
        self.deployer = _addr_of(self.key)
        self.feed = self._deploy_feed(self.engine, self.key, quorum=1)

    def _node(self, source, key=None, max_deviation_pct=0):
        return KurOracleNode(
            engine=self.engine, feed=self.feed, private_key=key or self.key,
            source=source, max_deviation_pct=max_deviation_pct,
        )

    def test_reporter_address_derived_from_key(self):
        node = self._node(FixedPriceSource(2500.0))
        self.assertEqual(node.reporter, self.deployer)
        self.assertTrue(node.is_authorized())

    def test_no_price_on_chain_before_publish(self):
        node = self._node(FixedPriceSource(2500.0))
        self.assertIsNone(node.on_chain_round())
        self.assertIsNone(node.on_chain_price())

    def test_publish_once_updates_feed(self):
        node = self._node(FixedPriceSource(2500.42))
        result = node.publish_once()
        self.assertEqual(int(self.engine.get_transaction_receipt(
            result['tx'])['status'], 16), 1)
        self.assertEqual(result['price'], to_units(2500.42))
        self.assertEqual(result['round']['roundId'], 1)
        self.assertEqual(result['round']['answer'], to_units(2500.42))
        self.assertEqual(node.on_chain_price(), to_units(2500.42))
        self.assertAlmostEqual(from_units(node.on_chain_price()), 2500.42, places=2)

    def test_rejects_unauthorized_reporter(self):
        node = self._node(FixedPriceSource(2500.0), key=OTHER_KEY)
        self.assertFalse(node.is_authorized())
        self.assertRaises(NotAuthorizedError, node.publish_once)

    def test_deviation_guard_blocks_outlier(self):
        node = self._node(FixedPriceSource(2500.0), max_deviation_pct=20)
        node.publish_once()
        node.source = FixedPriceSource(5000.0)  # +100%
        self.assertRaises(PriceDeviationError, node.publish_once)
        # o preço on-chain não mudou
        self.assertEqual(node.on_chain_price(), to_units(2500.0))

    def test_deviation_guard_can_be_disabled(self):
        node = self._node(FixedPriceSource(2500.0), max_deviation_pct=0)
        node.publish_once()
        node.source = FixedPriceSource(5000.0)
        node.publish_once()
        self.assertEqual(node.on_chain_price(), to_units(5000.0))

    def test_run_loop_publishes_each_iteration(self):
        node = self._node(RandomWalkSource(2500.0, 0.005, seed=7))
        ticks = []
        count = node.run(interval=0, iterations=2, on_tick=ticks.append)
        self.assertEqual(count, 2)
        self.assertEqual(len(ticks), 2)
        self.assertEqual(node.on_chain_round()['roundId'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
