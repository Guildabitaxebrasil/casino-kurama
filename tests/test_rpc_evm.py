"""
Testes dos métodos JSON-RPC que MetaMask/ethers.js/web3.js usam (Fase 6).

Cobre ``evm/engine.py`` + ``evm/rpc.py``:
- ``eth_getTransactionReceipt`` com **logs/eventos** e endereços;
- ``eth_getLogs`` com filtro de endereço e de topic;
- ``eth_getTransactionByHash``, ``eth_getBlockByNumber``/``ByHash`` (com
  transações completas), ``eth_getBlockTransactionCountBy*``;
- ``eth_getStorageAt`` (leitura de slot de contrato);
- ``eth_feeHistory`` e os headers CORS do ``POST /rpc``.

Executar com: python -m pytest tests/test_rpc_evm.py -v
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.compiler import compile_source
from evm.engine import EVMEngine
from config import EVM_CHAIN_ID, EVM_DEV_PRIVATE_KEY

KUR_TOKEN_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'evm', 'contracts', 'KurToken.sol')

TOKEN_NAME = 'Kurama Token'
TOKEN_SYMBOL = 'KUR'
SUPPLY = 1_000_000 * 10 ** 18
TRANSFER_TOPIC = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
OP_GAS = 4_000_000


def _selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def _address_arg(address: str) -> bytes:
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _decode_string(data: bytes) -> str:
    raw = bytes(data)
    if len(raw) < 64:
        return raw.rstrip(b'\x00').decode('utf-8', errors='ignore')
    offset = int.from_bytes(raw[0:32], 'big')
    length = int.from_bytes(raw[offset:offset + 32], 'big')
    return raw[offset + 32:offset + 32 + length].decode('utf-8', errors='ignore')


def _encode_constructor(name: str, symbol: str, supply: int) -> bytes:
    def enc(b: bytes) -> bytes:
        pad = (32 - len(b) % 32) % 32
        return len(b).to_bytes(32, 'big') + b + b'\x00' * pad

    name_b, symbol_b = enc(name.encode()), enc(symbol.encode())
    return ((3 * 32).to_bytes(32, 'big')
            + (3 * 32 + len(name_b)).to_bytes(32, 'big')
            + supply.to_bytes(32, 'big')
            + name_b + symbol_b)


class TestWalletJsonRpc(unittest.TestCase):
    """Métodos eth_* que uma wallet precisa para operar."""

    def setUp(self):
        from api.routes import create_app
        from evm.rpc import create_evm_blueprint
        self.engine = EVMEngine(auto_mine=True)
        self.app = create_app(port=5000)
        self.app.register_blueprint(create_evm_blueprint(self.engine))
        self.client = self.app.test_client()
        self.sender = '0x' + keys.PrivateKey(
            bytes.fromhex(EVM_DEV_PRIVATE_KEY[2:])).public_key.to_address()[2:]

        compiled = compile_source(
            open(KUR_TOKEN_PATH, encoding='utf-8').read(), 'KurToken')
        self.token_art = compiled
        _, self.token = self.engine.deploy(
            compiled['bytecode'] + _encode_constructor(TOKEN_NAME, TOKEN_SYMBOL,
                                                       SUPPLY),
            EVM_DEV_PRIVATE_KEY, gas=OP_GAS)
        self.recipient = '0x' + 'ab' * 20
        self.transfer_tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.token,
            _selector('transfer(address,uint256)') + _address_arg(self.recipient)
            + (1234 * 10 ** 18).to_bytes(32, 'big'), gas=200_000)

    # ─── Apoio ───────────────────────────────────────────────────

    def _rpc(self, method, params=None):
        resp = self.client.post('/rpc', json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or [],
        })
        return resp.get_json()

    def _rpc_response(self, method, params=None):
        return self.client.post('/rpc', json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or [],
        })

    # ─── Testes ──────────────────────────────────────────────────

    def test_receipt_contains_logs_with_topics_and_address(self):
        receipt = self._rpc('eth_getTransactionReceipt', [self.transfer_tx])['result']
        self.assertEqual(receipt['status'], '0x1')
        self.assertEqual(receipt['from'].lower(), self.sender.lower())
        self.assertEqual(receipt['to'].lower(), self.token.lower())
        self.assertEqual(len(receipt['logs']), 1)

        log = receipt['logs'][0]
        self.assertEqual(log['address'].lower(), self.token.lower())
        self.assertEqual(log['topics'][0], TRANSFER_TOPIC)
        self.assertTrue(log['topics'][1].lower().endswith(self.sender[2:].lower()),
                        'topic[1] deve ser o remetente')
        self.assertEqual(int(log['data'], 16), 1234 * 10 ** 18)

    def test_get_logs_filters_by_address_and_topic(self):
        by_address = self._rpc('eth_getLogs', [{
            'address': self.token, 'fromBlock': '0x0', 'toBlock': 'latest',
        }])['result']
        # O deploy também emite Transfer (mint do supply) — filtra o destinatário.
        self.assertGreaterEqual(len(by_address), 1)
        self.assertTrue(all(log['address'].lower() == self.token.lower()
                            for log in by_address))

        by_topic = self._rpc('eth_getLogs', [{
            'address': self.token, 'topics': [TRANSFER_TOPIC],
        }])['result']
        self.assertGreaterEqual(len(by_topic), 1)

        # topics[2] = destinatário → exatamente a transferência do teste.
        recipient_topic = '0x' + '00' * 12 + self.recipient[2:].lower()
        by_recipient = self._rpc('eth_getLogs', [{
            'address': self.token, 'topics': [TRANSFER_TOPIC, None, recipient_topic],
        }])['result']
        self.assertEqual(len(by_recipient), 1)
        self.assertEqual(int(by_recipient[0]['data'], 16), 1234 * 10 ** 18)

        other_topic = '0x' + keccak(text='Approval(address,address,uint256)').hex()
        self.assertEqual(len(self._rpc('eth_getLogs', [{
            'address': self.token, 'topics': [other_topic],
        }])['result']), 0)

        wrong_address = self._rpc('eth_getLogs', [{
            'address': '0x' + '00' * 20,
        }])['result']
        self.assertEqual(wrong_address, [])

    def test_get_transaction_by_hash(self):
        tx = self._rpc('eth_getTransactionByHash', [self.transfer_tx])['result']
        self.assertEqual(tx['hash'], self.transfer_tx)
        self.assertEqual(tx['from'].lower(), self.sender.lower())
        self.assertEqual(tx['to'].lower(), self.token.lower())
        self.assertEqual(tx['value'], '0x0')
        self.assertTrue(tx['input'].startswith('0x' + _selector(
            'transfer(address,uint256)').hex()))
        self.assertIsNone(self._rpc('eth_getTransactionByHash',
                                    ['0x' + '11' * 32])['result'])

    def test_get_block_by_number_and_hash(self):
        receipt = self._rpc('eth_getTransactionReceipt', [self.transfer_tx])['result']
        number = receipt['blockNumber']

        block = self._rpc('eth_getBlockByNumber', [number, True])['result']
        self.assertEqual(block['number'], number)
        self.assertEqual(len(block['transactions']), 1)
        self.assertEqual(block['transactions'][0]['hash'], self.transfer_tx)
        for field in ('hash', 'parentHash', 'stateRoot', 'transactionsRoot',
                      'receiptsRoot', 'gasLimit', 'gasUsed', 'timestamp'):
            self.assertIn(field, block)

        by_hash = self._rpc('eth_getBlockByHash', [receipt['blockHash'], False])['result']
        self.assertEqual(by_hash['hash'], receipt['blockHash'])
        self.assertEqual(by_hash['transactions'], [self.transfer_tx])

    def test_block_transaction_count(self):
        receipt = self._rpc('eth_getTransactionReceipt', [self.transfer_tx])['result']
        count = self._rpc('eth_getBlockTransactionCountByNumber',
                          [receipt['blockNumber']])['result']
        self.assertEqual(int(count, 16), 1)

    def test_get_storage_at_reads_contract_slot(self):
        """Slot 0 do KurToken é `name` ("Kurama Token", string curta empacotada)."""
        raw = self._rpc('eth_getStorageAt', [self.token, '0x0', 'latest'])['result']
        word = bytes.fromhex(raw[2:])
        length = word[31] // 2
        self.assertEqual(length, len(TOKEN_NAME))
        self.assertEqual(word[:length].decode(), TOKEN_NAME)

    def test_eth_call_still_works_with_new_dispatch(self):
        out = self._rpc('eth_call', [
            {'to': self.token, 'data': '0x' + _selector('symbol()').hex()},
            'latest',
        ])['result']
        self.assertEqual(_decode_string(bytes.fromhex(out[2:])), TOKEN_SYMBOL)

    def test_fee_history_shape(self):
        result = self._rpc('eth_feeHistory', ['0x2', 'latest', []])['result']
        self.assertEqual(len(result['baseFeePerGas']), 3)
        self.assertEqual(len(result['gasUsedRatio']), 2)
        self.assertIn('oldestBlock', result)

    def _transfer_data(self, to: str, amount: int) -> str:
        return '0x' + (_selector('transfer(address,uint256)')
                       + _address_arg(to) + amount.to_bytes(32, 'big')).hex()

    def test_estimate_gas_uses_real_sender_and_covers_used_gas(self):
        """`eth_estimateGas` simula com o `from` e não deixa a wallet sem gás."""
        fresh = '0x' + 'ef' * 20
        data = self._transfer_data(fresh, 1 * 10 ** 18)

        estimated = int(self._rpc('eth_estimateGas', [{
            'from': self.sender, 'to': self.token, 'data': data,
        }])['result'], 16)

        # Mesma transação de verdade (conta de destino nova, como na estimativa).
        tx = self.engine.send(EVM_DEV_PRIVATE_KEY, self.token,
                              bytes.fromhex(data[2:]), gas=200_000)
        receipt = self._rpc('eth_getTransactionReceipt', [tx])['result']
        used = int(receipt['gasUsed'], 16)

        self.assertGreaterEqual(estimated, used, 'estimativa deve cobrir o gas usado')
        self.assertLess(estimated, used * 2, 'estimativa não pode inflar o gas limit')

    def test_estimate_gas_rejects_transaction_that_would_revert(self):
        # Remetente sem saldo → a transferência reverte; a wallet deve saber
        # antes de assinar/gastar gas.
        resp = self._rpc('eth_estimateGas', [{
            'from': '0x' + 'cd' * 20, 'to': self.token,
            'data': self._transfer_data(self.recipient, 1 * 10 ** 18),
        }])
        self.assertIn('error', resp)
        self.assertEqual(resp['error']['code'], -32000)
        self.assertIn('reverteu', resp['error']['message'])

    def test_estimate_gas_without_from_uses_selector_ceiling(self):
        """Sem `from` não há como simular allowance: devolve teto conservador."""
        resp = self._rpc('eth_estimateGas', [{
            'to': self.token,
            'data': '0x095ea7b3' + '00' * 64,   # approve
        }])
        self.assertEqual(int(resp['result'], 16), 60_000)

    def test_rpc_cors_headers_for_dapps(self):
        resp = self._rpc_response('eth_chainId')
        self.assertEqual(resp.headers.get('Access-Control-Allow-Origin'), '*')
        self.assertEqual(
            int(self._rpc('eth_chainId')['result'], 16), EVM_CHAIN_ID)


if __name__ == '__main__':
    unittest.main(verbosity=2)
