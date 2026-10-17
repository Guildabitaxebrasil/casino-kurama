"""
Testes do mercado de empréstimos da KuramaChain (Fase 4 — Lending).

Cobre:
- ``KurPriceOracle``: registro asset → feed AggregatorV3, preço em 18 decimais
  e recusa de preço obsoleto.
- ``KurScaledToken``: aToken/debtToken com índice ray (saldo que rende/juros).
- ``KurLendingPool``: depósito, saque, empréstimo (LTV), pagamento, juros
  (utilização → taxa), reserva do protocolo e **liquidação por oráculo**.

O relógio da EVM é fixado com ``engine.advance_time(0)``: cada bloco avança
exatamente 1s, o que torna juros e liquidações determinísticos.

Executar com: python -m pytest tests/test_lending.py -v
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.compiler import compile_all
from evm.deploy import deploy_lending_pool, deploy_price_oracle, init_reserve
from evm.engine import EVMEngine
from evm.oracle_node import FixedPriceSource, KurOracleNode
from config import (
    EVM_DEV_PRIVATE_KEY,
    EVM_LENDING_CLOSE_FACTOR_BPS,
    EVM_LENDING_PRICE_MAX_AGE,
    EVM_LENDING_LIQ_BONUS_BPS,
    EVM_LENDING_LIQ_THRESHOLD_BPS,
    EVM_LENDING_LTV_BPS,
    EVM_LENDING_RESERVE_FACTOR_BPS,
)

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'evm', 'contracts')

SOURCES = (
    'KurToken.sol', 'KurPriceFeed.sol', 'KurPriceOracle.sol',
    'KurScaledToken.sol', 'KurLendingPool.sol',
)

DEPLOYER_KEY = EVM_DEV_PRIVATE_KEY
LIQUIDATOR_KEY = '0x' + 'bb' * 32
OTHER_KEY = '0x' + 'ee' * 32

USD = 10 ** 8          # 1 unidade do feed (8 decimais) = 1 USD
WAD = 10 ** 18
RAY = 10 ** 27
BPS = 10_000
YEAR = 365 * 24 * 3600
MAX_UINT = 2 ** 256 - 1
DUST = 10 ** 15        # 0,001 token — tolerância para juros de alguns segundos

COLL_PRICE = 2 * USD           # colateral: 2 USD por token
DEBT_PRICE = 1 * USD           # "stablecoin": 1 USD por token
COLL_DROP_PRICE = 160 * USD // 100   # 1,60 USD: derruba o colateral abaixo do limiar
ORACLE_PRICE = 1000 * USD      # preço usado nos testes só do registro de feeds

OP_GAS = 4_000_000
RESERVE_GAS = 12_000_000
BALANCE = 200_000          # tokens distribuídos a cada conta de teste


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


def _word(value: int) -> bytes:
    return int(value).to_bytes(32, 'big')


def _words(data, n: int) -> list:
    data = bytes(data)
    return [int.from_bytes(data[i * 32:(i + 1) * 32], 'big') for i in range(n)]


def _uint(data) -> int:
    return _words(data, 1)[0]


def _address(data) -> str:
    return '0x' + bytes(data)[-20:].hex()


def _enc_string(s: str) -> bytes:
    b = s.encode()
    pad = (32 - len(b) % 32) % 32
    return len(b).to_bytes(32, 'big') + b + b'\x00' * pad


def _enc_token_constructor(name: str, symbol: str, supply: int) -> bytes:
    """ABI-encoda ``(string, string, uint256)`` do KurToken."""
    return (((3 * 32).to_bytes(32, 'big')
             + (3 * 32 + 64).to_bytes(32, 'big')
             + supply.to_bytes(32, 'big'))
            + _enc_string(name) + _enc_string(symbol))


def _enc_feed_constructor(description: str, quorum: int, reporters: list) -> bytes:
    """ABI-encoda ``(string, uint256, address[])`` do KurPriceFeed."""
    desc = _enc_string(description)
    array = (len(reporters).to_bytes(32, 'big')
             + b''.join(_addr_arg(r) for r in reporters))
    return ((3 * 32).to_bytes(32, 'big')
            + quorum.to_bytes(32, 'big')
            + (3 * 32 + len(desc)).to_bytes(32, 'big')
            + desc + array)


def _tokens(amount: float) -> int:
    """Converte um valor "humano" em wei (18 decimais)."""
    return int(amount * 10 ** 18)


def _apr_bps(rate_per_second: int) -> int:
    """Taxa em ray por segundo → APR em bps (400 = 4% a.a.)."""
    return rate_per_second * YEAR * BPS // RAY


def _make_engine(funded_keys=()) -> EVMEngine:
    """Engine com o relógio fixado (blocos de 1s) e contas financiadas."""
    accounts = {_addr_of(key): 1_000.0 for key in funded_keys}
    engine = EVMEngine(auto_mine=True, genesis_accounts=accounts)
    engine.advance_time(0)
    return engine


# ─── Base ────────────────────────────────────────────────────────

class _LendingTestBase(unittest.TestCase):
    """Compila os contratos uma única vez para toda a suíte."""

    @classmethod
    def setUpClass(cls):
        artifacts = compile_all({name: _read(name) for name in SOURCES})
        cls.token_art = artifacts['KurToken.sol']['KurToken']
        cls.feed_art = artifacts['KurPriceFeed.sol']['KurPriceFeed']

    def _deploy_token(self, engine, key, name='Collateral', symbol='COLL',
                      supply=1_000_000):
        _, address = engine.deploy(
            self.token_art['bytecode']
            + _enc_token_constructor(name, symbol, _tokens(supply)),
            key, gas=4_000_000)
        return address

    def _deploy_feed(self, engine, key, quorum=1, reporters=None):
        reporters = reporters if reporters is not None else [_addr_of(key)]
        args = _enc_feed_constructor('KUR/USD', quorum, reporters)
        _, feed = engine.deploy(self.feed_art['bytecode'] + args, key, gas=5_000_000)
        return feed

    def _submit(self, key, feed, price):
        """Publica um preço no feed (tx com sucesso garantido)."""
        return self._send(self.engine, key, feed, _sel('submit(int256)') + _word(price))

    def _send(self, engine, key, to, data, gas=None):
        """Envia uma tx que deve ter sucesso e devolve o recibo."""
        tx = engine.send(key, to, data, gas=gas or OP_GAS)
        receipt = engine.get_transaction_receipt(tx)
        self.assertIsNotNone(receipt, 'recibo não encontrado para a tx enviada')
        self.assertEqual(int(receipt['status'], 16), 1,
                         f'tx revertida (esperava sucesso): {to}')
        return receipt

    def _send_revert(self, engine, key, to, data, gas=None):
        """
        Envia uma tx que DEVE reverter e exige recibo com status 0.

        No fork London a tx que reverte é **incluída no bloco** com status 0
        (não é descartada nem levanta exceção) — a falha aparece no recibo.
        """
        tx = engine.send(key, to, data, gas=gas or OP_GAS)
        receipt = engine.get_transaction_receipt(tx)
        self.assertIsNotNone(receipt, 'recibo não encontrado para a tx enviada')
        self.assertEqual(int(receipt['status'], 16), 0,
                         'esperava revert (status 0) no recibo')
        return receipt

    def _assert_close(self, actual, expected, tolerance=DUST):
        """Compara valores tolerando o juro (dust) de um ou dois segundos."""
        self.assertLessEqual(
            abs(actual - expected), tolerance,
            f'{actual} != {expected} (tolerância {tolerance})')


class _PriceOracleTestBase(_LendingTestBase):
    """Base para os testes só do registro de preços."""

    def setUp(self):
        self.engine = _make_engine([OTHER_KEY])
        self.key = DEPLOYER_KEY
        self.deployer = _addr_of(self.key)
        self.coll = self._deploy_token(self.engine, self.key).lower()
        self.feed = self._deploy_feed(self.engine, self.key).lower()
        self._submit(self.key, self.feed, ORACLE_PRICE)
        _, self.prices = deploy_price_oracle(self.engine)

    def _price(self, asset):
        return _uint(self.engine.call(
            self.prices, _sel('getAssetPrice(address)') + _addr_arg(asset)))

    def _set_feed(self, asset, feed, key=None, expect_ok=True):
        data = (_sel('setAssetFeed(address,address)')
                + _addr_arg(asset) + _addr_arg(feed))
        sender = key or self.key
        if expect_ok:
            return self._send(self.engine, sender, self.prices, data)
        return self._send_revert(self.engine, sender, self.prices, data)


class _MarketTestBase(_LendingTestBase):
    """Monta um mercado completo: 2 ativos, 2 feeds, price oracle e pool."""

    def setUp(self):
        self.engine = _make_engine([LIQUIDATOR_KEY, OTHER_KEY])
        self.key = DEPLOYER_KEY
        self.deployer = _addr_of(self.key)
        self.liquidator_key = LIQUIDATOR_KEY
        self.other_key = OTHER_KEY
        self.liquidator = _addr_of(LIQUIDATOR_KEY)
        self.other = _addr_of(OTHER_KEY)

        self.coll = self._deploy_token(self.engine, self.key, 'Collateral', 'COLL').lower()
        self.debt = self._deploy_token(self.engine, self.key, 'Stable', 'DEBT').lower()

        # o deployer cunhou todo o supply no construtor: distribui tokens
        for address in (self.liquidator, self.other):
            for asset in (self.coll, self.debt):
                self._send(self.engine, self.key, asset,
                           _sel('transfer(address,uint256)')
                           + _addr_arg(address) + _word(_tokens(BALANCE)))

        self.coll_feed = self._deploy_feed(self.engine, self.key).lower()
        self.debt_feed = self._deploy_feed(self.engine, self.key).lower()
        self._set_prices()

        _, self.prices = deploy_price_oracle(self.engine)
        for asset, feed in ((self.coll, self.coll_feed), (self.debt, self.debt_feed)):
            self._send(self.engine, self.key, self.prices,
                       _sel('setAssetFeed(address,address)')
                       + _addr_arg(asset) + _addr_arg(feed))

        self.prices = self.prices.lower()
        _, self.pool = deploy_lending_pool(self.engine, self.prices)
        self.pool = self.pool.lower()
        _, (self.aColl, self.dColl) = init_reserve(self.engine, self.pool, self.coll)
        _, (self.aDebt, self.dDebt) = init_reserve(self.engine, self.pool, self.debt)

    # ─── helpers do mercado ──────────────────────────────────────

    def _set_prices(self, coll_price=COLL_PRICE, debt_price=DEBT_PRICE):
        self._submit(self.key, self.coll_feed, coll_price)
        self._submit(self.key, self.debt_feed, debt_price)

    def _approve(self, key, asset, spender, amount):
        return self._send(self.engine, key, asset,
                          _sel('approve(address,uint256)')
                          + _addr_arg(spender) + _word(amount))

    def _supply(self, key, asset, amount, on_behalf_of=None):
        """Aprova e deposita no pool (colateral)."""
        self._approve(key, asset, self.pool, amount)
        return self._deposit(key, asset, amount, on_behalf_of)

    def _deposit(self, key, asset, amount, on_behalf_of=None, expect_ok=True):
        data = (_sel('deposit(address,uint256,address)') + _addr_arg(asset)
                + _word(amount) + _addr_arg(on_behalf_of or _addr_of(key)))
        if expect_ok:
            return self._send(self.engine, key, self.pool, data)
        return self._send_revert(self.engine, key, self.pool, data)

    def _withdraw(self, key, asset, amount, to=None, expect_ok=True):
        data = (_sel('withdraw(address,uint256,address)') + _addr_arg(asset)
                + _word(amount) + _addr_arg(to or _addr_of(key)))
        if expect_ok:
            return self._send(self.engine, key, self.pool, data)
        return self._send_revert(self.engine, key, self.pool, data)

    def _borrow(self, key, asset, amount, on_behalf_of=None, expect_ok=True):
        data = (_sel('borrow(address,uint256,address)') + _addr_arg(asset)
                + _word(amount) + _addr_arg(on_behalf_of or _addr_of(key)))
        if expect_ok:
            return self._send(self.engine, key, self.pool, data)
        return self._send_revert(self.engine, key, self.pool, data)

    def _repay(self, key, asset, amount, on_behalf_of=None, expect_ok=True):
        data = (_sel('repay(address,uint256,address)') + _addr_arg(asset)
                + _word(amount) + _addr_arg(on_behalf_of or _addr_of(key)))
        if expect_ok:
            return self._send(self.engine, key, self.pool, data)
        return self._send_revert(self.engine, key, self.pool, data)

    def _liquidate(self, key, collateral_asset, debt_asset, user, amount,
                   expect_ok=True):
        data = (_sel('liquidationCall(address,address,address,uint256)')
                + _addr_arg(collateral_asset) + _addr_arg(debt_asset)
                + _addr_arg(user) + _word(amount))
        if expect_ok:
            return self._send(self.engine, key, self.pool, data)
        return self._send_revert(self.engine, key, self.pool, data)

    def _accrue(self, asset, key=None):
        return self._send(self.engine, key or self.key, self.pool,
                          _sel('accrue(address)') + _addr_arg(asset))

    # ─── leituras ────────────────────────────────────────────────

    def _balance_of(self, key, asset):
        return self._token_balance(asset, _addr_of(key))

    def _token_balance(self, token, address):
        return _uint(self.engine.call(token, _sel('balanceOf(address)')
                                      + _addr_arg(address)))

    def _account(self, address) -> dict:
        out = _words(self.engine.call(
            self.pool, _sel('getUserAccountData(address)') + _addr_arg(address)), 6)
        keys_ = ('totalCollateralBase', 'totalDebtBase', 'availableBorrowsBase',
                 'currentLiquidationThreshold', 'ltv', 'healthFactor')
        return dict(zip(keys_, out))

    def _reserve_data(self, asset) -> dict:
        out = _words(self.engine.call(
            self.pool, _sel('getReserveData(address)') + _addr_arg(asset)), 6)
        keys_ = ('liquidityIndex', 'borrowIndex', 'totalBorrows',
                 'availableLiquidity', 'utilizationRate', 'borrowRatePerSecond')
        return dict(zip(keys_, out))

    def _indexes(self, asset):
        return _words(self.engine.call(
            self.pool, _sel('getIndexes(address)') + _addr_arg(asset)), 2)

    def _user_reserve(self, address, asset):
        return _words(self.engine.call(
            self.pool, _sel('getUserReserveData(address,address)')
            + _addr_arg(address) + _addr_arg(asset)), 2)

    def _treasury(self, asset):
        return _uint(self.engine.call(
            self.pool, _sel('accruedTreasury(address)') + _addr_arg(asset)))

    def _borrow_rate(self, asset):
        return _uint(self.engine.call(
            self.pool, _sel('borrowRate(address)') + _addr_arg(asset)))

    def _price(self, asset):
        return _uint(self.engine.call(
            self.prices, _sel('getAssetPrice(address)') + _addr_arg(asset)))


# ─── KurPriceOracle ──────────────────────────────────────────────

class TestKurPriceOracle(_PriceOracleTestBase):
    """Fase 4 — registro de preços por ativo consumido pelo pool."""

    def test_price_is_normalized_to_18_decimals(self):
        self._set_feed(self.coll, self.feed)
        # feed em 8 decimais (1000 USD) → 18 decimais (1000 * 1e18)
        self.assertEqual(self._price(self.coll), ORACLE_PRICE * 10 ** 10)
        self.assertEqual(_uint(self.engine.call(self.prices, _sel('maxAge()'))),
                         EVM_LENDING_PRICE_MAX_AGE)
        out = _words(self.engine.call(
            self.prices, _sel('assetPriceInfo(address)') + _addr_arg(self.coll)), 3)
        self.assertEqual(out[0], ORACLE_PRICE * 10 ** 10)
        self.assertNotEqual(out[1], 0)       # updatedAt
        self.assertNotEqual(out[2], 0)       # fresh
        self.assertEqual(_uint(self.engine.call(self.prices, _sel('assetsLength()'))), 1)
        self.assertEqual(_address(self.engine.call(
            self.prices, _sel('assets(uint256)') + _word(0))), self.coll)

    def test_unknown_asset_has_no_price(self):
        self.assertRaises(Exception, self.engine.call, self.prices,
                          _sel('getAssetPrice(address)') + _addr_arg(self.coll))
        # assetPriceInfo é diagnóstico: devolve zeros em vez de reverter
        self.assertEqual(_words(self.engine.call(
            self.prices, _sel('assetPriceInfo(address)') + _addr_arg(self.coll)), 3),
            [0, 0, 0])

    def test_removing_feed(self):
        self._set_feed(self.coll, self.feed)
        self.assertEqual(self._price(self.coll), ORACLE_PRICE * 10 ** 10)
        self._set_feed(self.coll, '0x' + '00' * 20)
        self.assertRaises(Exception, self.engine.call, self.prices,
                          _sel('getAssetPrice(address)') + _addr_arg(self.coll))
        # registrar de novo não duplica a lista de ativos
        self._set_feed(self.coll, self.feed)
        self.assertEqual(_uint(self.engine.call(self.prices, _sel('assetsLength()'))), 1)
        self.assertEqual(self._price(self.coll), ORACLE_PRICE * 10 ** 10)

    def test_stale_price_is_rejected(self):
        # maxAge = 1h (default do config)
        self._set_feed(self.coll, self.feed)
        self.engine.advance_time(7200)
        self.assertRaises(Exception, self.engine.call, self.prices,
                          _sel('getAssetPrice(address)') + _addr_arg(self.coll))
        # preço republicado volta a valer
        self._submit(self.key, self.feed, 990 * USD)
        self.assertEqual(self._price(self.coll), 990 * WAD)

    def test_max_age_zero_disables_freshness_check(self):
        _, oracle = deploy_price_oracle(self.engine, max_age=0)
        self.assertEqual(_uint(self.engine.call(oracle, _sel('maxAge()'))), 0)
        self._send(self.engine, self.key, oracle,
                   _sel('setAssetFeed(address,address)')
                   + _addr_arg(self.coll) + _addr_arg(self.feed))
        self.engine.advance_time(365 * 24 * 3600)
        self.assertEqual(_uint(self.engine.call(
            oracle, _sel('getAssetPrice(address)') + _addr_arg(self.coll))),
            ORACLE_PRICE * 10 ** 10)

    def test_set_asset_feed_is_owner_only(self):
        self._set_feed(self.coll, self.feed, key=OTHER_KEY, expect_ok=False)

    def test_oracle_node_publishes_price_read_by_the_registry(self):
        """Nó oráculo (Fase 3) alimenta o preço que o pool consome."""
        self._set_feed(self.coll, self.feed)
        node = KurOracleNode(engine=self.engine, feed=self.feed,
                             private_key=self.key,
                             source=FixedPriceSource(1234.5),
                             max_deviation_pct=0)
        result = node.publish_once()
        self.assertEqual(int(self.engine.get_transaction_receipt(
            result['tx'])['status'], 16), 1)
        # 1234,5 USD em 8 decimais → 18 decimais
        self.assertEqual(self._price(self.coll), (1234 * USD + 50 * 10 ** 6) * 10 ** 10)


# ─── Reservas / depósito / saque ─────────────────────────────────

class TestKurLendingReserves(_MarketTestBase):
    """Fase 4 — abertura de mercado, depósito (aToken) e saque."""

    def test_init_reserve_creates_market_and_uses_config_defaults(self):
        self.assertEqual(_uint(self.engine.call(
            self.pool, _sel('getReservesCount()'))), 2)
        reserves = bytes(self.engine.call(self.pool, _sel('getReservesList()')))
        self.assertEqual(_address(reserves[64:96]), self.coll)     # elemento 0
        self.assertEqual(_address(reserves[96:128]), self.debt)    # elemento 1

        raw = bytes(self.engine.call(
            self.pool, _sel('getReserveConfigurationData(address)')
            + _addr_arg(self.coll)))
        out = _words(raw, 9)
        self.assertEqual(_address(raw[0:32]), self.aColl)
        self.assertEqual(_address(raw[32:64]), self.dColl)
        self.assertEqual(out[2], 18)                       # decimals do ativo
        # LTV / limiar / bônus / reserve factor vêm do config (EVM_LENDING_*)
        self.assertEqual(out[3], EVM_LENDING_LTV_BPS)
        self.assertEqual(out[4], EVM_LENDING_LIQ_THRESHOLD_BPS)
        self.assertEqual(out[5], EVM_LENDING_LIQ_BONUS_BPS)
        self.assertEqual(out[6], EVM_LENDING_RESERVE_FACTOR_BPS)
        self.assertEqual(out[7], 1)                        # active
        self.assertEqual(out[8], 1)                        # borrowingEnabled

        # os tokens da reserva referenciam o pool e o ativo subjacente
        for token, symbol in ((self.aColl, 'aCOLL'), (self.dColl, 'dCOLL')):
            self.assertEqual(_address(self.engine.call(token, _sel('pool()'))),
                             self.pool)
            self.assertEqual(_address(self.engine.call(token, _sel('underlying()'))),
                             self.coll)
            out = bytes(self.engine.call(token, _sel('symbol()')))
            length = int.from_bytes(out[32:64], 'big')
            self.assertEqual(out[64:64 + length].decode(), symbol)
            self.assertEqual(_uint(self.engine.call(token, _sel('index()'))), RAY)

    def test_init_reserve_is_owner_only_and_validates_params(self):
        extra = self._deploy_token(self.engine, self.key, 'Extra', 'EXT')
        init = _sel('initReserve(address,uint16,uint16,uint16,uint16)')

        def args(ltv=7500, threshold=8000, bonus=10500, factor=1000):
            return (_addr_arg(extra) + _word(ltv) + _word(threshold)
                    + _word(bonus) + _word(factor))

        # só o owner
        self._send_revert(self.engine, OTHER_KEY, self.pool, init + args(),
                          gas=RESERVE_GAS)
        # LTV > limiar de liquidação
        self._send_revert(self.engine, self.key, self.pool,
                          init + args(ltv=9000), gas=RESERVE_GAS)
        # limiar acima de 100%
        self._send_revert(self.engine, self.key, self.pool,
                          init + args(threshold=10001), gas=RESERVE_GAS)
        # bônus de liquidação abaixo de 100% (o liquidante sairia no prejuízo)
        self._send_revert(self.engine, self.key, self.pool,
                          init + args(bonus=9900), gas=RESERVE_GAS)
        # reserve factor > 100%
        self._send_revert(self.engine, self.key, self.pool,
                          init + args(factor=10001), gas=RESERVE_GAS)
        # parâmetros válidos abrem o mercado...
        self._send(self.engine, self.key, self.pool, init + args(), gas=RESERVE_GAS)
        self.assertEqual(_uint(self.engine.call(self.pool, _sel('getReservesCount()'))), 3)
        # ...e não podem ser repetidos
        self._send_revert(self.engine, self.key, self.pool, init + args(),
                          gas=RESERVE_GAS)

    def test_deposit_mints_atoken_and_holds_underlying(self):
        amount = _tokens(1_000)
        before = self._balance_of(self.key, self.coll)
        self._supply(self.key, self.coll, amount)

        self.assertEqual(self._token_balance(self.aColl, self.deployer), amount)
        self.assertEqual(_uint(self.engine.call(self.aColl, _sel('totalSupply()'))),
                         amount)
        self.assertEqual(self._token_balance(self.coll, self.pool), amount)
        # o depositante pagou o subjacente ao pool
        self.assertEqual(self._balance_of(self.key, self.coll), before - amount)
        self.assertEqual(self._reserve_data(self.coll)['availableLiquidity'], amount)
        a_balance, debt_balance = self._user_reserve(self.deployer, self.coll)
        self.assertEqual((a_balance, debt_balance), (amount, 0))
        # 1.000 COLL a 2 USD → 2.000 USD de colateral
        self.assertEqual(self._account(self.deployer)['totalCollateralBase'], 2000 * WAD)

    def test_deposit_requires_allowance_and_nonzero_amount(self):
        amount = _tokens(10)
        self._deposit(self.key, self.coll, amount, expect_ok=False)  # sem approve
        self._approve(self.key, self.coll, self.pool, amount)
        self._deposit(self.key, self.coll, 0, expect_ok=False)       # valor zero
        self._deposit(self.key, self.coll, amount)                   # agora vai

    def test_deposit_on_behalf_of_credits_other_account(self):
        amount = _tokens(100)
        self._supply(self.key, self.coll, amount, on_behalf_of=self.other)
        self.assertEqual(self._token_balance(self.aColl, self.other), amount)
        self.assertEqual(self._token_balance(self.aColl, self.deployer), 0)
        # o aToken é transferível
        self._send(self.engine, self.other_key, self.aColl,
                   _sel('transfer(address,uint256)')
                   + _addr_arg(self.deployer) + _word(amount // 2))
        self.assertEqual(self._token_balance(self.aColl, self.deployer), amount // 2)
        a_balance, _ = self._user_reserve(self.other, self.coll)
        self.assertEqual(a_balance, amount // 2)

    def test_withdraw_returns_underlying(self):
        before = self._balance_of(self.key, self.coll)
        self._supply(self.key, self.coll, _tokens(1_000))
        self._withdraw(self.key, self.coll, _tokens(400))
        self.assertEqual(self._token_balance(self.aColl, self.deployer), _tokens(600))
        self.assertEqual(self._balance_of(self.key, self.coll), before - _tokens(600))
        # saque total com type(uint256).max
        self._withdraw(self.key, self.coll, MAX_UINT)
        self.assertEqual(self._token_balance(self.aColl, self.deployer), 0)
        self.assertEqual(self._balance_of(self.key, self.coll), before)
        # sem colateral, outro saque reverte
        self._withdraw(self.key, self.coll, _tokens(1), expect_ok=False)

    def test_withdraw_more_than_available_liquidity_reverts(self):
        # outro usuário deposita 5000 DEBT e o dev toma 1500 emprestado
        self._supply(self.liquidator_key, self.debt, _tokens(5_000))
        self._supply(self.key, self.coll, _tokens(2_000))
        self._borrow(self.key, self.debt, _tokens(1_500))
        # restam 3500 DEBT no pool, mas o depositante tem 5000
        self.assertEqual(self._reserve_data(self.debt)['availableLiquidity'],
                         _tokens(3_500))
        self._withdraw(self.liquidator_key, self.debt, _tokens(5_000), expect_ok=False)
        # o que cabe na liquidez disponível funciona
        self._withdraw(self.liquidator_key, self.debt, _tokens(3_000))
        self.assertEqual(self._reserve_data(self.debt)['availableLiquidity'],
                         _tokens(500))


# ─── Empréstimo / pagamento / juros ──────────────────────────────

class TestKurLendingBorrow(_MarketTestBase):
    """Fase 4 — empréstimo com garantia, pagamento e juros por utilização."""

    def test_borrow_respects_ltv_and_updates_account_data(self):
        self._supply(self.liquidator_key, self.debt, _tokens(10_000))
        self._supply(self.key, self.coll, _tokens(1_000))   # 1.000 COLL = 2.000 USD
        before = self._balance_of(self.key, self.debt)

        # colateral de 2.000 USD, LTV 7500 bps → 1.500 USD no máximo
        self._borrow(self.key, self.debt, _tokens(1_500) + 1, expect_ok=False)
        self._borrow(self.key, self.debt, _tokens(1_500))

        self.assertEqual(self._balance_of(self.key, self.debt),
                         before + _tokens(1_500))
        data = self._account(self.deployer)
        self._assert_close(data['totalCollateralBase'], 2000 * WAD)
        self._assert_close(data['totalDebtBase'], 1500 * WAD)
        self.assertEqual(data['ltv'], EVM_LENDING_LTV_BPS)
        self.assertEqual(data['currentLiquidationThreshold'],
                         EVM_LENDING_LIQ_THRESHOLD_BPS)
        self._assert_close(data['availableBorrowsBase'], 0)   # LTV esgotado
        # HF = 2.000 * 0,8 / 1.500 > 1 (posição saudável)
        self._assert_close(data['healthFactor'],
                           (2000 * WAD * EVM_LENDING_LIQ_THRESHOLD_BPS // BPS)
                           * WAD // (1500 * WAD), tolerance=10 ** 12)

        # debtToken reflete a dívida e o aToken o colateral
        self._assert_close(self._user_reserve(self.deployer, self.debt)[1], 1500 * WAD)
        self._assert_close(self._user_reserve(self.deployer, self.coll)[0], 1000 * WAD)

    def test_borrow_requires_collateral_and_liquidity(self):
        # sem colateral (mas com liquidez do ativo emprestado)
        self._supply(self.liquidator_key, self.debt, _tokens(10_000))
        self._borrow(self.key, self.debt, _tokens(1), expect_ok=False)
        # com colateral, mas pedindo mais do que o pool tem
        self._supply(self.key, self.coll, _tokens(1_000))
        self._borrow(self.key, self.coll, _tokens(2_000), expect_ok=False)

    def test_borrow_disabled_reserve_reverts(self):
        self._supply(self.liquidator_key, self.debt, _tokens(1_000))
        self._supply(self.key, self.coll, _tokens(1_000))
        data = (_sel('setReserveConfig(address,uint16,uint16,uint16,uint16,bool,bool)')
                + _addr_arg(self.debt) + _word(EVM_LENDING_LTV_BPS)
                + _word(EVM_LENDING_LIQ_THRESHOLD_BPS) + _word(EVM_LENDING_LIQ_BONUS_BPS)
                + _word(EVM_LENDING_RESERVE_FACTOR_BPS) + _word(1) + _word(0))
        self._send(self.engine, self.key, self.pool, data)
        self._borrow(self.key, self.debt, _tokens(1), expect_ok=False)

    def test_repay_partial_and_full(self):
        self._supply(self.liquidator_key, self.debt, _tokens(10_000))
        self._supply(self.key, self.coll, _tokens(1_000))
        self._borrow(self.key, self.debt, _tokens(700))

        self._approve(self.key, self.debt, self.pool, MAX_UINT)
        self._repay(self.key, self.debt, _tokens(200))
        self._assert_close(self._user_reserve(self.deployer, self.debt)[1],
                           500 * WAD)

        # pagar mais do que deve quita a dívida e não cobra o excedente
        balance_before = self._balance_of(self.key, self.debt)
        self._repay(self.key, self.debt, _tokens(5_000))
        self.assertEqual(self._user_reserve(self.deployer, self.debt)[1], 0)
        self.assertEqual(self._token_balance(self.dDebt, self.deployer), 0)
        self._assert_close(self._balance_of(self.key, self.debt),
                           balance_before - _tokens(500))
        # sem dívida, novo pagamento reverte
        self._repay(self.key, self.debt, _tokens(1), expect_ok=False)

    def test_interest_accrues_on_debt_and_atoken(self):
        self._supply(self.key, self.debt, _tokens(10_000))          # LP
        self._supply(self.liquidator_key, self.coll, _tokens(1_000))
        self._borrow(self.liquidator_key, self.debt, _tokens(100))

        data = self._reserve_data(self.debt)
        self.assertEqual(data['utilizationRate'], RAY // 100)        # 1% (100/10.000)
        rate = data['borrowRatePerSecond']
        # taxa = slope1 * u / optimal = 4% * (1/80) = 0,05 % a.a.
        expected_apr = 400 * RAY // BPS * (RAY // 100) // (8 * RAY // 10)
        self.assertLess(abs(rate * YEAR - expected_apr), expected_apr // 1000)

        self.engine.advance_time(YEAR)
        self._set_prices()          # os preços acompanham o novo relógio
        self._accrue(self.debt)

        liquidity_index, borrow_index = self._indexes(self.debt)
        self.assertGreater(borrow_index, RAY)
        self.assertGreater(liquidity_index, RAY)
        # o devedor paga ~1 ano de juros sobre 100 DEBT
        debt = self._user_reserve(self.liquidator, self.debt)[1]
        expected_debt = 100 * WAD + 100 * WAD * rate * YEAR // RAY
        self.assertLess(abs(debt - expected_debt), expected_debt // 1000)
        # o aToken do LP rende a taxa de liquidez (utilização × (1 - reserveFactor))
        a_balance = self._token_balance(self.aDebt, self.deployer)
        self.assertGreater(a_balance, 10_000 * WAD)
        self.assertLess(a_balance - 10_000 * WAD, 10_000 * WAD * rate * YEAR // RAY)
        # parte dos juros fica com o protocolo
        treasury = self._treasury(self.debt)
        self.assertGreater(treasury, 0)
        self.assertLess(treasury, debt - 100 * WAD)

    def test_accrue_is_permissionless_and_claim_treasury(self):
        self._supply(self.key, self.debt, _tokens(10_000))
        self._supply(self.liquidator_key, self.coll, _tokens(1_000))
        self._borrow(self.liquidator_key, self.debt, _tokens(700))

        self.engine.advance_time(YEAR)
        # qualquer conta pode aplicar os juros
        self._accrue(self.debt, key=self.other_key)
        treasury = self._treasury(self.debt)
        self.assertGreater(treasury, 0)

        claim = (_sel('claimTreasury(address,address)')
                 + _addr_arg(self.debt) + _addr_arg(self.deployer))
        # só o owner resgata
        self._send_revert(self.engine, self.other_key, self.pool, claim)
        self._send_revert(self.engine, self.other_key, self.pool,
                          _sel('setCloseFactor(uint16)') + _word(9000))
        before = self._balance_of(self.key, self.debt)
        self._send(self.engine, self.key, self.pool, claim)
        self.assertGreater(self._balance_of(self.key, self.debt), before)
        self.assertEqual(self._treasury(self.debt), 0)
        # nada mais para resgatar
        self._send_revert(self.engine, self.key, self.pool, claim)

    def test_rate_model_increases_with_utilization(self):
        self._supply(self.key, self.debt, _tokens(10_000))
        self._supply(self.liquidator_key, self.coll, _tokens(1_000))
        self._borrow(self.liquidator_key, self.debt, _tokens(100))
        low = self._borrow_rate(self.debt)
        self.assertLess(_apr_bps(low), 400)          # abaixo de 4% a.a.

        # utilização vai para 90% (> ótima de 80%) → inclinação 2 (75% a.a.)
        self._supply(self.other_key, self.coll, _tokens(20_000))
        self._borrow(self.other_key, self.debt, _tokens(8_900))
        data = self._reserve_data(self.debt)
        self.assertLess(abs(data['utilizationRate'] - 9 * RAY // 10), RAY // 10_000)
        high = self._borrow_rate(self.debt)
        self.assertGreater(high, low)
        # 41,5% a.a. (4% + 75% * 0,5) contra 0,05% a.a. da utilização baixa
        self.assertGreater(_apr_bps(high), 4000)
        self.assertGreater(_apr_bps(high), _apr_bps(low) * 10)

    def test_set_rate_params_and_close_factor(self):
        data = (_sel('setRateParams(uint256,uint256,uint256,uint256)')
                + _word(100) + _word(500) + _word(10000) + _word(5000))
        self._send(self.engine, self.key, self.pool, data)
        self.assertEqual(_uint(self.engine.call(self.pool, _sel('baseRate()'))),
                         100 * RAY // BPS // YEAR)
        self.assertEqual(_uint(self.engine.call(
            self.pool, _sel('optimalUtilization()'))), RAY // 2)
        self.assertEqual(_uint(self.engine.call(self.pool, _sel('closeFactor()'))),
                         EVM_LENDING_CLOSE_FACTOR_BPS)
        # não-owner e valores inválidos
        self._send_revert(self.engine, self.other_key, self.pool, data)
        self._send_revert(self.engine, self.key, self.pool,
                          _sel('setRateParams(uint256,uint256,uint256,uint256)')
                          + _word(0) + _word(0) + _word(0) + _word(0))
        self._send_revert(self.engine, self.key, self.pool,
                          _sel('setCloseFactor(uint16)') + _word(0))
        self._send(self.engine, self.key, self.pool,
                   _sel('setCloseFactor(uint16)') + _word(9000))
        self.assertEqual(_uint(self.engine.call(self.pool, _sel('closeFactor()'))), 9000)


# ─── Liquidação por oráculo ──────────────────────────────────────

class TestKurLiquidation(_MarketTestBase):
    """Fase 4 — liquidação de posição subcolateralizada com o preço do feed."""

    def _open_position(self, coll_amount=_tokens(1_000), borrow_amount=_tokens(1_400)):
        """
        O liquidante fornece o ativo emprestado; o dev deposita 1.000 COLL
        (2.000 USD) e toma 1.400 DEBT emprestado (LTV de 70%, HF = 1,14).
        """
        self._supply(self.liquidator_key, self.debt, _tokens(10_000))
        self._supply(self.key, self.coll, coll_amount)
        self._borrow(self.key, self.debt, borrow_amount)

    def _drop_collateral_price(self, price=COLL_DROP_PRICE):
        """Republica o preço do colateral (queda) via nó oráculo."""
        node = KurOracleNode(engine=self.engine, feed=self.coll_feed,
                             private_key=self.key,
                             source=FixedPriceSource(price / USD),
                             max_deviation_pct=0)
        node.publish_once()
        self.assertEqual(self._price(self.coll), price * WAD // USD)

    def test_healthy_position_cannot_be_liquidated(self):
        self._open_position()
        self.assertGreater(self._account(self.deployer)['healthFactor'], WAD)
        self._liquidate(self.liquidator_key, self.coll, self.debt, self.deployer,
                        _tokens(1), expect_ok=False)

    def test_price_drop_lowers_health_factor_below_one(self):
        self._open_position()
        self._drop_collateral_price()
        # colateral 1.600 USD e dívida 1.400 USD → 1.400/1.600 = 87% > limiar (80%)
        data = self._account(self.deployer)
        self.assertLess(data['healthFactor'], WAD)
        self._assert_close(data['totalCollateralBase'], 1600 * WAD)
        self._assert_close(data['totalDebtBase'], 1400 * WAD)

    def test_liquidation_call_seizes_collateral_with_bonus(self):
        self._open_position()
        self._drop_collateral_price()

        # fecha 50% da dívida (closeFactor) e recebe colateral + 5% de bônus
        debt_to_cover = _tokens(700)
        debt_value = debt_to_cover * (DEBT_PRICE * 10 ** 10) // WAD    # 700 USD
        # liquidationBonus é o multiplicador em bps (10500 = 1,05 = +5%)
        expected_collateral = (debt_value * EVM_LENDING_LIQ_BONUS_BPS // BPS
                               * WAD // (COLL_DROP_PRICE * 10 ** 10))
        self.assertEqual(expected_collateral, 459375 * 10 ** 15)   # 459,375 COLL
        hf_before = self._account(self.deployer)['healthFactor']
        self.assertLess(hf_before, WAD)

        liquidator_debt_before = self._balance_of(self.liquidator_key, self.debt)
        collateral_before = self._balance_of(self.liquidator_key, self.coll)
        self._approve(self.liquidator_key, self.debt, self.pool, MAX_UINT)
        self._liquidate(self.liquidator_key, self.coll, self.debt, self.deployer,
                        debt_to_cover)

        self._assert_close(self._user_reserve(self.deployer, self.debt)[1],
                           700 * WAD)
        self._assert_close(self._user_reserve(self.deployer, self.coll)[0],
                           _tokens(1_000) - expected_collateral)
        # o liquidante pagou a dívida e recebeu o colateral com bônus
        self.assertEqual(self._balance_of(self.liquidator_key, self.debt),
                         liquidator_debt_before - debt_to_cover)
        self.assertEqual(self._balance_of(self.liquidator_key, self.coll),
                         collateral_before + expected_collateral)
        # 1.000 - 459,375 COLL a 1,60 USD → 865 USD de colateral
        self._assert_close(self._account(self.deployer)['totalCollateralBase'],
                           865 * WAD)
        # a posição melhora, mas segue liquidável (o bônus sai do colateral)
        hf_after = self._account(self.deployer)['healthFactor']
        self.assertGreater(hf_after, hf_before)
        self.assertLess(hf_after, WAD)

    def test_liquidation_is_capped_by_close_factor(self):
        self._open_position()
        self._drop_collateral_price()
        self._approve(self.liquidator_key, self.debt, self.pool, MAX_UINT)
        # pede a dívida inteira (1.400), mas só 50% são aceitos
        self._liquidate(self.liquidator_key, self.coll, self.debt, self.deployer,
                        _tokens(1_400))
        self._assert_close(self._user_reserve(self.deployer, self.debt)[1],
                           700 * WAD)

    def test_liquidation_checks_selected_assets(self):
        """Posição liquidável, mas com par de ativos inválido, é recusada."""
        self._open_position()
        self._drop_collateral_price()
        self.assertLess(self._account(self.deployer)['healthFactor'], WAD)

        # colateral igual à dívida
        self._liquidate(self.liquidator_key, self.coll, self.coll, self.deployer,
                        _tokens(1), expect_ok=False)
        # dívida escolhida (COLL) inexistente para o usuário
        self._liquidate(self.liquidator_key, self.debt, self.coll, self.deployer,
                        _tokens(1), expect_ok=False)

        # o par correto segue liquidando normalmente
        self._approve(self.liquidator_key, self.debt, self.pool, MAX_UINT)
        self._liquidate(self.liquidator_key, self.coll, self.debt, self.deployer,
                        _tokens(200))
        self._assert_close(self._user_reserve(self.deployer, self.debt)[1],
                           1200 * WAD)

    def test_liquidator_without_funds_cannot_liquidate(self):
        self._open_position()
        self._drop_collateral_price()
        # OTHER não aprovou o pool para gastar seu DEBT
        data = (_sel('liquidationCall(address,address,address,uint256)')
                + _addr_arg(self.coll) + _addr_arg(self.debt)
                + _addr_arg(self.deployer) + _word(_tokens(100)))
        self._send_revert(self.engine, self.other_key, self.pool, data)

    def test_borrow_and_withdraw_blocked_by_stale_price(self):
        self._supply(self.liquidator_key, self.debt, _tokens(10_000))
        self._supply(self.key, self.coll, _tokens(1_000))
        # o preço só vale 1h (default do config): passa a ser recusado
        self.engine.advance_time(7200)
        self._borrow(self.key, self.debt, _tokens(100), expect_ok=False)
        self._withdraw(self.key, self.coll, _tokens(10), expect_ok=False)
        # depósito não depende de preço: continua funcionando
        self._supply(self.other_key, self.coll, _tokens(10))
        # com o preço republicado, emprestar volta a funcionar
        self._set_prices()
        self._borrow(self.key, self.debt, _tokens(100))
        self.assertEqual(self._user_reserve(self.deployer, self.debt)[1] > 0, True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
