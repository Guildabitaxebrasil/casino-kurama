"""
Testes do DEX da KuramaChain (Fase 2): factory, par de liquidez e swap AMM.

Executar com: python -m pytest tests/test_dex.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.engine import EVMEngine
from evm.compiler import compile_contracts
from config import EVM_DEV_PRIVATE_KEY

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'evm', 'contracts')


def _read(name: str) -> str:
    with open(os.path.join(CONTRACTS_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def _sel(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def _addr_arg(address: str) -> bytes:
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _enc_string(s: str) -> bytes:
    b = s.encode()
    pad = (32 - len(b) % 32) % 32
    return len(b).to_bytes(32, 'big') + b + b'\x00' * pad


def _enc_constructor(name: str, symbol: str, supply: int) -> bytes:
    head = (3 * 32).to_bytes(32, 'big') + (3 * 32 + 64).to_bytes(32, 'big') + supply.to_bytes(32, 'big')
    return head + _enc_string(name) + _enc_string(symbol)


def _uint(data: bytes) -> int:
    return int.from_bytes(bytes(data), 'big')


def _address(data: bytes) -> str:
    return '0x' + bytes(data)[-20:].hex()


class TestDEX(unittest.TestCase):
    def setUp(self):
        self.engine = EVMEngine(auto_mine=True)
        self.deployer = (
            '0x' + keys.PrivateKey(bytes.fromhex(EVM_DEV_PRIVATE_KEY[2:]))
            .public_key.to_address()[2:]
        )
        sources = {
            name: _read(name)
            for name in ('KurToken.sol', 'KurPair.sol', 'KurFactory.sol',
                         'KurRouter.sol', 'UQ112x112.sol')
        }
        self.token_abi = compile_contracts(sources, 'KurToken.sol', 'KurToken')
        factory = compile_contracts(sources, 'KurFactory.sol', 'KurFactory')
        router = compile_contracts(sources, 'KurRouter.sol', 'KurRouter')

        supply = 1_000_000 * 10**18
        _, self.tokenA = self.engine.deploy(
            self.token_abi['bytecode'] + _enc_constructor('Token A', 'TKA', supply),
            EVM_DEV_PRIVATE_KEY, gas=4_000_000)
        _, self.tokenB = self.engine.deploy(
            self.token_abi['bytecode'] + _enc_constructor('Token B', 'TKB', supply),
            EVM_DEV_PRIVATE_KEY, gas=4_000_000)
        _, self.factory = self.engine.deploy(factory['bytecode'], EVM_DEV_PRIVATE_KEY, gas=5_000_000)
        # Router(factory): argumento do construtor = endereço da factory
        _, self.router = self.engine.deploy(
            router['bytecode'] + _addr_arg(self.factory), EVM_DEV_PRIVATE_KEY, gas=5_000_000)

        # Cria o par A/B
        self.engine.send(EVM_DEV_PRIVATE_KEY, self.factory,
                         _sel('createPair(address,address)') + _addr_arg(self.tokenA) + _addr_arg(self.tokenB))
        out = self.engine.call(self.factory, _sel('getPair(address,address)') + _addr_arg(self.tokenA) + _addr_arg(self.tokenB))
        self.pair = _address(out)

    def _balance_of(self, token, who):
        return _uint(self.engine.call(token, _sel('balanceOf(address)') + _addr_arg(who)))

    def _reserves(self):
        out = bytes(self.engine.call(self.pair, _sel('getReserves()')))
        return _uint(out[0:32]), _uint(out[32:64])

    def test_pair_created(self):
        self.assertNotEqual(self.pair, '0x' + '00' * 20)
        self.assertEqual(len(self.pair), 42)

    def test_add_liquidity_and_swap(self):
        amt_a, amt_b = 100_000 * 10**18, 200_000 * 10**18
        # Aprova o router para gastar os tokens do deployer
        for token in (self.tokenA, self.tokenB):
            self.engine.send(EVM_DEV_PRIVATE_KEY, token,
                             _sel('approve(address,uint256)') + _addr_arg(self.router)
                             + (2**256 - 1).to_bytes(32, 'big'))
        self.engine.send(EVM_DEV_PRIVATE_KEY, self.router,
                         _sel('addLiquidity(address,address,uint256,uint256,address)')
                         + _addr_arg(self.tokenA) + _addr_arg(self.tokenB)
                         + amt_a.to_bytes(32, 'big') + amt_b.to_bytes(32, 'big')
                         + _addr_arg(self.deployer))

        r0, r1 = self._reserves()
        self.assertEqual(sorted([r0, r1]), sorted([amt_a, amt_b]))
        lp = self._balance_of(self.pair, self.deployer)
        self.assertGreater(lp, 0)

        # Swap: 1000 TKA -> TKB
        amount_in = 1_000 * 10**18
        bal_b_before = self._balance_of(self.tokenB, self.deployer)
        tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.router,
            _sel('swapExactTokensForTokens(uint256,uint256,address[],address)')
            + amount_in.to_bytes(32, 'big')
            + (0).to_bytes(32, 'big')
            + (128).to_bytes(32, 'big')               # offset do array path
            + _addr_arg(self.deployer)
            + (2).to_bytes(32, 'big')                  # len(path) = 2
            + _addr_arg(self.tokenA) + _addr_arg(self.tokenB),
            gas=500_000,
        )
        self.assertEqual(int(self.engine.get_transaction_receipt(tx)['status'], 16), 1)

        bal_b_after = self._balance_of(self.tokenB, self.deployer)
        self.assertGreater(bal_b_after, bal_b_before, 'swap deveria aumentar o saldo de TKB')


if __name__ == '__main__':
    unittest.main(verbosity=2)
