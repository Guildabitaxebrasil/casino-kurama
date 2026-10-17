"""
Testes da camada EVM da KuramaChain (Fase 0) e do token ERC-20 (Fase 1).

Executar com: python -m pytest tests/test_evm.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.engine import EVMEngine
from evm.compiler import compile_source
from config import EVM_DEV_PRIVATE_KEY, EVM_CHAIN_ID, EVM_DEFAULT_GAS_PRICE

OTHER_KEY = '0x' + '22' * 32

KUR_TOKEN_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'evm', 'contracts', 'KurToken.sol'
)


def _selector(signature: str) -> bytes:
    """Seletor de 4 bytes de uma assinatura de função."""
    return keccak(text=signature)[:4]


def _address_arg(address: str) -> bytes:
    """ABI-encoda um endereço 0x... em 32 bytes."""
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _decode_uint(data: bytes) -> int:
    return int.from_bytes(bytes(data), 'big')


def _decode_string(data: bytes) -> str:
    """Decodifica o retorno ABI de uma string (offset + length + data)."""
    raw = bytes(data)
    if len(raw) < 64:
        return raw.rstrip(b'\x00').decode('utf-8', errors='ignore')
    offset = int.from_bytes(raw[0:32], 'big')
    length = int.from_bytes(raw[offset:offset + 32], 'big')
    return raw[offset + 32:offset + 32 + length].decode('utf-8', errors='ignore')


def _encode_constructor(name: str, symbol: str, supply: int) -> bytes:
    """
    ABI-encoda os argumentos do construtor `(string, string, uint256)`.

    Construtores NÃO usam seletor — os argumentos vão direto após o bytecode.
    """
    name_b, symbol_b = name.encode(), symbol.encode()

    def enc_bytes(b: bytes) -> bytes:
        pad = (32 - len(b) % 32) % 32
        return len(b).to_bytes(32, 'big') + b + b'\x00' * pad

    head = (
        (3 * 32).to_bytes(32, 'big')          # offset da 1ª string = 96
        + (3 * 32 + 64).to_bytes(32, 'big')   # offset da 2ª string = 160
        + supply.to_bytes(32, 'big')          # supply (estático)
    )
    return head + enc_bytes(name_b) + enc_bytes(symbol_b)


class TestEVMEngine(unittest.TestCase):
    """Fase 0 — motor EVM."""

    def setUp(self):
        self.engine = EVMEngine(auto_mine=True)
        self.deployer = (
            '0x' + keys.PrivateKey(bytes.fromhex(EVM_DEV_PRIVATE_KEY[2:]))
            .public_key.to_address()[2:]
        )

    def test_chain_id_and_block_number(self):
        self.assertEqual(self.engine.chain_id, EVM_CHAIN_ID)
        self.assertEqual(self.engine.block_number, 0)

    def test_genesis_accounts_funded(self):
        """A conta de desenvolvimento é financiada no gênese."""
        self.assertGreater(self.engine.get_balance(self.deployer), 0)

    def test_deploy_and_call_contract(self):
        """Deploy de contrato Solidity + leitura via eth_call."""
        compiled = compile_source(
            '// SPDX-License-Identifier: MIT\n'
            'pragma solidity ^0.8.19;\n'
            'contract Storage { uint256 public value;'
            ' function set(uint256 v) public { value = v; }'
            ' function get() public view returns (uint256) { return value; } }',
            'Storage',
        )
        tx_hash, contract = self.engine.deploy(compiled['bytecode'], EVM_DEV_PRIVATE_KEY)
        self.assertTrue(contract.startswith('0x'))
        receipt = self.engine.get_transaction_receipt(tx_hash)
        self.assertEqual(int(receipt['status'], 16), 1)
        self.assertEqual(_decode_uint(self.engine.call(contract, _selector('get()'))), 0)

    def test_set_then_get(self):
        """Escrita on-chain (set) reflete na leitura (get)."""
        compiled = compile_source(
            '// SPDX-License-Identifier: MIT\n'
            'pragma solidity ^0.8.19;\n'
            'contract Storage { uint256 public value;'
            ' function set(uint256 v) public { value = v; }'
            ' function get() public view returns (uint256) { return value; } }',
            'Storage',
        )
        _, contract = self.engine.deploy(compiled['bytecode'], EVM_DEV_PRIVATE_KEY)
        self.engine.send(
            EVM_DEV_PRIVATE_KEY, contract,
            _selector('set(uint256)') + (42).to_bytes(32, 'big'),
        )
        self.assertEqual(_decode_uint(self.engine.call(contract, _selector('get()'))), 42)


class TestERC20(unittest.TestCase):
    """Fase 1 — token ERC-20."""

    def setUp(self):
        self.engine = EVMEngine(auto_mine=True)
        self.deployer = (
            '0x' + keys.PrivateKey(bytes.fromhex(EVM_DEV_PRIVATE_KEY[2:]))
            .public_key.to_address()[2:]
        )
        self.other = (
            '0x' + keys.PrivateKey(bytes.fromhex(OTHER_KEY[2:]))
            .public_key.to_address()[2:]
        )
        compiled = compile_source(
            open(KUR_TOKEN_PATH, encoding='utf-8').read(), 'KurToken'
        )
        args = _encode_constructor('Kurama Token', 'KUR', 1_000_000 * 10**18)
        _, self.token = self.engine.deploy(
            compiled['bytecode'] + args, EVM_DEV_PRIVATE_KEY, gas=4_000_000
        )

    def test_metadata(self):
        self.assertEqual(_decode_string(self.engine.call(self.token, _selector('name()'))),
                         'Kurama Token')
        self.assertEqual(_decode_string(self.engine.call(self.token, _selector('symbol()'))),
                         'KUR')
        self.assertEqual(_decode_uint(self.engine.call(self.token, _selector('decimals()'))), 18)

    def test_total_supply(self):
        self.assertEqual(
            _decode_uint(self.engine.call(self.token, _selector('totalSupply()'))),
            1_000_000 * 10**18,
        )

    def test_balance_of_deployer(self):
        data = _selector('balanceOf(address)') + _address_arg(self.deployer)
        self.assertEqual(_decode_uint(self.engine.call(self.token, data)), 1_000_000 * 10**18)

    def test_transfer(self):
        amount = 500 * 10**18
        data = (
            _selector('transfer(address,uint256)')
            + _address_arg(self.other)
            + amount.to_bytes(32, 'big')
        )
        tx_hash = self.engine.send(EVM_DEV_PRIVATE_KEY, self.token, data, gas=200_000)
        self.assertEqual(int(self.engine.get_transaction_receipt(tx_hash)['status'], 16), 1)
        bal = self.engine.call(self.token, _selector('balanceOf(address)') + _address_arg(self.other))
        self.assertEqual(_decode_uint(bal), amount)


class TestEVMRPC(unittest.TestCase):
    """Fase 0 — JSON-RPC eth_*."""

    def setUp(self):
        from api.routes import create_app
        from evm.rpc import create_evm_blueprint
        self.engine = EVMEngine(auto_mine=True)
        self.app = create_app(port=5000)
        self.app.register_blueprint(create_evm_blueprint(self.engine))
        self.client = self.app.test_client()

    def _rpc(self, method, params=None):
        resp = self.client.post('/rpc', json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or [],
        })
        return resp.get_json()

    def test_eth_chainId(self):
        self.assertEqual(int(self._rpc('eth_chainId')['result'], 16), EVM_CHAIN_ID)

    def test_eth_blockNumber(self):
        self.assertEqual(int(self._rpc('eth_blockNumber')['result'], 16), 0)

    def test_web3_clientVersion(self):
        self.assertIn('KuramaChain', self._rpc('web3_clientVersion')['result'])

    def test_eth_call_name(self):
        """eth_call de name() via RPC."""
        compiled = compile_source(
            open(KUR_TOKEN_PATH, encoding='utf-8').read(), 'KurToken'
        )
        args = _encode_constructor('Kurama Token', 'KUR', 0)
        _, token = self.engine.deploy(compiled['bytecode'] + args, EVM_DEV_PRIVATE_KEY,
                                      gas=4_000_000)
        out = self._rpc('eth_call', [{'to': token, 'data': '0x' + _selector('symbol()').hex()},
                                     'latest'])['result']
        self.assertEqual(_decode_string(bytes.fromhex(out[2:])), 'KUR')

    def test_eth_sendRawTransaction_legacy(self):
        """Tx assinada crua no formato legado (como as wallets enviam) entra na cadeia."""
        compiled = compile_source(
            '// SPDX-License-Identifier: MIT\n'
            'pragma solidity ^0.8.19;\n'
            'contract Storage { uint256 public value;'
            ' function set(uint256 v) public { value = v; }'
            ' function get() public view returns (uint256) { return value; } }',
            'Storage',
        )
        _, contract = self.engine.deploy(compiled['bytecode'], EVM_DEV_PRIVATE_KEY)
        sender = ('0x' + keys.PrivateKey(bytes.fromhex(EVM_DEV_PRIVATE_KEY[2:]))
                  .public_key.to_address()[2:])

        signed = self.engine._build_signed(
            EVM_DEV_PRIVATE_KEY, bytes.fromhex(contract[2:]),
            _selector('set(uint256)') + (42).to_bytes(32, 'big'),
            0, 3_000_000, EVM_DEFAULT_GAS_PRICE, self.engine.get_nonce(sender),
        )
        raw = '0x' + bytes(signed.encode()).hex()
        result = self._rpc('eth_sendRawTransaction', [raw])
        self.assertNotIn('error', result, result)
        self.assertEqual(result['result'], '0x' + signed.hash.hex())

        self.assertEqual(
            _decode_uint(self.engine.call(contract, _selector('get()'))), 42)

    def test_unknown_method_returns_error(self):
        self.assertIn('error', self._rpc('eth_naoExiste'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
