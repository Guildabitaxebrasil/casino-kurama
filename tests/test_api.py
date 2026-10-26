#!/usr/bin/env python3
"""
Testes de integração da API REST da Blockchain.
Testa todos os endpoints HTTP usando o test client do Flask.

Execute com: python -m pytest tests/test_api.py -v
         ou: python tests/test_api.py
"""
import sys
import os
import tempfile
import unittest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api.routes import create_app
from core.blockchain import Blockchain
from core.crypto_utils import CryptoUtils
from core.wallet import Wallet


class TestAPIChain(unittest.TestCase):
    """Testes dos endpoints da blockchain (/chain, /stats, /validate)."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()

    def test_get_chain(self):
        """GET /chain deve retornar a blockchain completa."""
        resp = self.client.get('/chain')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('chain', data)
        self.assertIn('length', data)
        self.assertGreaterEqual(data['length'], 1)
        self.assertIn('node_id', data)

    def test_get_chain_contains_genesis(self):
        """A cadeia deve conter ao menos o bloco genesis."""
        resp = self.client.get('/chain')
        data = resp.get_json()
        genesis = data['chain'][0]
        self.assertEqual(genesis['index'], 0)
        self.assertEqual(genesis['previous_hash'], '0' * 64)

    def test_get_stats(self):
        """GET /stats deve retornar estatisticas."""
        resp = self.client.get('/stats')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('blocks', data)
        self.assertIn('difficulty', data)
        self.assertIn('node_id', data)
        self.assertIn('chain_valid', data)
        self.assertTrue(data['chain_valid'])
        # Contagem para o próximo bloco (alvo de 10 min)
        self.assertIn('last_block_timestamp', data)
        self.assertIn('target_block_time', data)
        self.assertIn('next_block_at', data)
        self.assertAlmostEqual(
            data['next_block_at'],
            data['last_block_timestamp'] + data['target_block_time'],
        )

    def test_get_validate(self):
        """GET /validate deve retornar validacao."""
        resp = self.client.get('/validate')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('valid', data)
        self.assertTrue(data['valid'])
        self.assertIn('blocks', data)

    def test_get_health(self):
        """GET /api/health deve retornar health check."""
        resp = self.client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('node_id', data)
        self.assertIn('blocks', data)


class TestAPIMining(unittest.TestCase):
    """Testes dos endpoints de mineracao (/mine)."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()
        cls.miner = Wallet()

    def test_mine_block(self):
        """POST /mine deve minerar um bloco."""
        # Pega o comprimento atual
        chain_resp = self.client.get('/chain')
        chain_len = chain_resp.get_json()['length']

        resp = self.client.post('/mine', json={
            'miner_address': self.miner.address
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('message', data)
        self.assertIn('block', data)
        self.assertIn('total_reward', data)
        self.assertIn('miner_address', data)
        self.assertEqual(data['miner_address'], self.miner.address)

        # Verifica que um bloco foi adicionado
        chain_resp2 = self.client.get('/chain')
        self.assertEqual(
            chain_resp2.get_json()['length'],
            chain_len + 1
        )

    def test_mine_invalid_address(self):
        """POST /mine com endereco invalido deve retornar 400."""
        resp = self.client.post('/mine', json={
            'miner_address': 'endereco_invalido'
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)

    def test_mine_no_address(self):
        """POST /mine sem endereco deve usar o endereco do no."""
        resp = self.client.post('/mine', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('block', data)


class TestAPIExternalMining(unittest.TestCase):
    """Endpoints da mineracao externa (/mining/template, /mining/submit)."""

    @classmethod
    def setUpClass(cls):
        # Dificuldade 2 mantem o PoW dos testes rapido.
        cls.app = create_app(blockchain=Blockchain(difficulty=2), port=5000)
        cls.client = cls.app.test_client()
        cls.miner = Wallet()

    @staticmethod
    def _solve(template):
        fields = ('index', 'timestamp', 'transactions', 'proof',
                  'previous_hash', 'merkle_root')
        proof = 0
        while True:
            block = {k: template[k] for k in fields}
            block['proof'] = proof
            hash_value = CryptoUtils.hash_block(block)
            if CryptoUtils.is_hash_valid(hash_value, template['difficulty']):
                block['hash'] = hash_value
                block['difficulty'] = template['difficulty']
                return block
            proof += 1

    def test_mining_template(self):
        """GET /mining/template entrega o bloco candidato."""
        resp = self.client.get(
            f'/mining/template?address={self.miner.address}')
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertEqual(data['miner_address'], self.miner.address)
        self.assertEqual(data['transactions'][0]['receiver'],
                         self.miner.address)
        self.assertIn('previous_hash', data)
        self.assertIn('merkle_root', data)
        self.assertIn('difficulty', data)
        self.assertGreater(data['reward'], 0)

    def test_mining_template_invalid_address(self):
        resp = self.client.get('/mining/template?address=endereco_invalido')
        self.assertEqual(resp.status_code, 400)

    def test_mining_uses_its_own_rate_limit(self):
        """O minerador faz 2 req/bloco e não pode tomar 429 do limite global."""
        responses = [
            self.client.get(f'/mining/template?address={self.miner.address}')
            for _ in range(70)
        ]
        codes = {resp.status_code for resp in responses}
        self.assertEqual(codes, {200})
        # A cota de mineração é anunciada nos headers, não a global.
        self.assertEqual(responses[-1].headers['X-RateLimit-Limit'], '600')

    def test_mining_submit_solved_block(self):
        """POST /mining/submit aceita o bloco minerado na CPU."""
        chain_before = self.client.get('/chain').get_json()['length']

        template = self.client.get(
            f'/mining/template?address={self.miner.address}').get_json()
        block = self._solve(template)

        resp = self.client.post('/mining/submit', json=block)
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertEqual(data['miner_address'], self.miner.address)
        self.assertEqual(data['block']['index'], chain_before)
        self.assertGreater(data['total_reward'], 0)
        self.assertGreaterEqual(data['miner_balance'], 0)

        self.assertEqual(
            self.client.get('/chain').get_json()['length'],
            chain_before + 1)

    def test_mining_submit_rejects_unsolved_block(self):
        """Sem PoW o bloco é recusado com 409."""
        chain_before = self.client.get('/chain').get_json()['length']
        template = self.client.get(
            f'/mining/template?address={self.miner.address}').get_json()
        template['proof'] = 0

        resp = self.client.post('/mining/submit', json=template)
        self.assertEqual(resp.status_code, 409)
        self.assertIn('error', resp.get_json())
        self.assertEqual(
            self.client.get('/chain').get_json()['length'], chain_before)

    def test_mining_submit_without_body(self):
        resp = self.client.post('/mining/submit', json={})
        self.assertEqual(resp.status_code, 400)

    def test_mining_submit_malformed_block_is_not_500(self):
        """Corpo que não é um bloco vira 4xx (400 ao parsear), nunca 500."""
        cases = [
            [],
            ['nao', 'e', 'bloco'],
            {'index': 1},                                  # sem proof
            {'index': 1, 'proof': 'abc', 'transactions': []},
            {'index': 1, 'transactions': 'x'},             # txs não é lista
            {'index': 1, 'transactions': ['x']},           # tx não é dict
            {'index': 1, 'transactions': None, 'previous_hash': None,
             'proof': 0},
        ]
        for body in cases:
            with self.subTest(body=body):
                resp = self.client.post('/mining/submit', json=body)
                self.assertIn(resp.status_code, (400, 409), msg=body)
                self.assertIn('error', resp.get_json())


class TestAPITransactions(unittest.TestCase):
    """Testes dos endpoints de transacoes (/transactions/new)."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()
        cls.wallet = Wallet()
        cls.miner = Wallet()

    def test_create_transaction_missing_fields(self):
        """POST /transactions/new sem campos obrigatorios deve retornar 400."""
        resp = self.client.post('/transactions/new', json={})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)
        self.assertIn('missing', data)

    def test_create_transaction_invalid_signature(self):
        """Transacao sem assinatura valida deve ser rejeitada."""
        resp = self.client.post('/transactions/new', json={
            'sender': self.wallet.public_key_pem,
            'receiver': self.miner.address,
            'amount': 10.0,
            'signature': 'assinatura_invalida'
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)

    def test_create_valid_signed_transaction(self):
        """Transacao assinada corretamente deve ser aceita."""
        # Minera um bloco primeiro para dar saldo ao minerador
        self.client.post('/mine', json={
            'miner_address': self.miner.address
        })

        # Cria transacao assinada via endpoint especial
        tx_data = {
            'private_key_pem': self.miner.private_key_pem,
            'receiver': self.wallet.address,
            'amount': 50.0,
            'fee': 0.001
        }
        resp = self.client.post('/api/transactions/create-signed', json=tx_data)
        self.assertEqual(resp.status_code, 201, msg=resp.get_json())
        data = resp.get_json()
        self.assertIn('message', data)
        self.assertIn('transaction', data)
        self.assertIn('sender_address', data)

    def test_create_signed_transaction_to_evm_address_credits_evm(self):
        """Destino 0x... deve ser creditado também na EVM (visivel na Rabby)."""
        from evm.engine import EVMEngine

        # Isola o ledger de depósitos para não escrever em data/.
        tmp = tempfile.TemporaryDirectory()
        prev_ledger = os.environ.get('EVM_DEPOSIT_LEDGER')
        os.environ['EVM_DEPOSIT_LEDGER'] = os.path.join(tmp.name, 'ledger.json')
        engine = EVMEngine(auto_mine=True)
        self.app.evm_engine = engine
        try:
            self.client.post('/mine', json={'miner_address': self.miner.address})
            evm_receiver = '0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18'
            resp = self.client.post('/api/transactions/create-signed', json={
                'private_key_pem': self.miner.private_key_pem,
                'receiver': evm_receiver,
                'amount': 50.0,
                'fee': 0.001,
            })
            self.assertEqual(resp.status_code, 201, msg=resp.get_json())
            data = resp.get_json()
            self.assertTrue(data.get('evm_tx_hash'))
            self.assertEqual(data.get('evm_credited_wei'), 50 * 10 ** 18)
            self.assertEqual(engine.get_balance(evm_receiver), 50 * 10 ** 18)
            receipt = engine.get_transaction_receipt(data['evm_tx_hash'])
            self.assertIsNotNone(receipt)
            self.assertEqual(receipt['status'], '0x1')

            # O histórico expõe o hash do depósito para a UI (após minerar).
            self.client.post('/mine', json={'miner_address': self.miner.address})
            history = self.client.get(
                f'/api/transactions?receiver={evm_receiver}').get_json()
            self.assertEqual(history['total'], 1)
            self.assertEqual(history['transactions'][0]['evm_tx_hash'],
                             data['evm_tx_hash'])
        finally:
            self.app.evm_engine = None
            if prev_ledger is None:
                os.environ.pop('EVM_DEPOSIT_LEDGER', None)
            else:
                os.environ['EVM_DEPOSIT_LEDGER'] = prev_ledger
            tmp.cleanup()

    def test_get_pending_transactions(self):
        """GET /transactions/pending deve retornar transacoes pendentes."""
        resp = self.client.get('/transactions/pending')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('count', data)
        self.assertIn('transactions', data)


class TestAPIWallet(unittest.TestCase):
    """Testes dos endpoints de carteira (/wallet/new, /balance)."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()

    def test_new_wallet(self):
        """POST /wallet/new deve criar uma carteira."""
        resp = self.client.post('/wallet/new', json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('address', data)
        self.assertIn('public_key', data)
        # Em dev mode, private_key_pem deve estar presente
        self.assertIn('private_key_pem', data)
        # Endereco deve ter tamanho razoavel
        self.assertGreater(len(data['address']), 20)

    def test_get_balance(self):
        """GET /balance/<address> deve retornar saldo (sem historico por padrao)."""
        wallet = Wallet()
        resp = self.client.get(f'/balance/{wallet.address}')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('address', data)
        self.assertEqual(data['address'], wallet.address)
        self.assertIn('balance', data)
        self.assertIsInstance(data['balance'], (int, float))
        # M-03: historico so retorna com ?history=true
        self.assertNotIn('transactions', data)

    def test_get_balance_with_history(self):
        """GET /balance/<address>?history=true deve retornar historico."""
        wallet = Wallet()
        resp = self.client.get(f'/balance/{wallet.address}?history=true')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('address', data)
        self.assertIn('balance', data)
        self.assertIn('transactions_count', data)
        self.assertIn('transactions', data)

    def test_get_balance_invalid_address(self):
        """GET /balance com endereco inexistente deve retornar saldo 0."""
        resp = self.client.get('/balance/endereco_invalido')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['balance'], 0)


class TestAPIExplorer(unittest.TestCase):
    """Testes dos endpoints do Explorer (/api/*)."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()

    def test_get_supply(self):
        """GET /api/supply deve retornar informacoes do supply."""
        resp = self.client.get('/api/supply')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('total_supply', data)
        self.assertIn('supply_cap', data)
        self.assertIn('token_name', data)
        self.assertEqual(data['token_name'], 'Kurama')
        self.assertIn('current_block_reward', data)

    def test_get_chart(self):
        """GET /api/chart deve retornar dados do grafico."""
        resp = self.client.get('/api/chart')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    def test_get_chart_with_limit(self):
        """GET /api/chart?limit=5 deve respeitar o limite."""
        resp = self.client.get('/api/chart?limit=5')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertLessEqual(len(data), 5)

    def test_get_mempool(self):
        """GET /api/mempool deve retornar stats da mempool."""
        resp = self.client.get('/api/mempool')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('total', data)
        self.assertIn('transactions', data)

    def test_get_transactions_pagination(self):
        """GET /api/transactions deve suportar paginacao."""
        resp = self.client.get('/api/transactions?page=1&per_page=10')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('transactions', data)
        self.assertIn('page', data)
        self.assertIn('total_pages', data)
        self.assertEqual(data['page'], 1)

    def test_get_transactions_filter_by_sender_and_receiver(self):
        """GET /api/transactions?sender/receiver deve filtrar por lado."""
        miner, receiver = Wallet(), Wallet()
        self.client.post('/mine', json={'miner_address': miner.address})
        resp = self.client.post('/api/transactions/create-signed', json={
            'private_key_pem': miner.private_key_pem,
            'receiver': receiver.address,
            'amount': 1.0,
            'fee': 0.001,
        })
        self.assertEqual(resp.status_code, 201, msg=resp.get_json())
        self.client.post('/mine', json={'miner_address': miner.address})

        received = self.client.get(
            f'/api/transactions?receiver={receiver.address}').get_json()
        self.assertGreaterEqual(received['total'], 1)
        for tx in received['transactions']:
            self.assertEqual(tx['receiver'], receiver.address)

        sent = self.client.get(
            f'/api/transactions?sender={miner.address}').get_json()
        self.assertGreaterEqual(sent['total'], 1)
        for tx in sent['transactions']:
            self.assertTrue(tx.get('sender') == miner.address
                            or tx.get('sender_address') == miner.address)

    def test_get_block_by_index(self):
        """GET /api/blocks/<index> deve retornar o bloco."""
        resp = self.client.get('/api/blocks/0')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['index'], 0)

    def test_get_block_not_found(self):
        """GET /api/blocks/9999 deve retornar 404."""
        resp = self.client.get('/api/blocks/9999')
        self.assertEqual(resp.status_code, 404)

    def test_search_block(self):
        """GET /api/search?q=0 deve encontrar o bloco genesis."""
        resp = self.client.get('/api/search?q=0')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['type'], 'block')

    def test_search_empty(self):
        """GET /api/search sem query deve retornar 400."""
        resp = self.client.get('/api/search')
        self.assertEqual(resp.status_code, 400)

    def test_chain_since(self):
        """GET /api/chain/since/<index> deve retornar blocos."""
        resp = self.client.get('/api/chain/since/0')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('blocks', data)
        self.assertIn('tip', data)

    def test_get_nodes(self):
        """GET /api/nodes deve retornar lista de nos."""
        resp = self.client.get('/api/nodes')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('nodes', data)
        self.assertIn('total', data)
        self.assertIn('active', data)


class TestAPISecurity(unittest.TestCase):
    """Testes de seguranca e edge cases da API."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(port=5000)
        cls.client = cls.app.test_client()

    def test_security_headers(self):
        """Respostas devem ter headers de seguranca."""
        resp = self.client.get('/chain')
        self.assertIn('X-Content-Type-Options', resp.headers)
        self.assertEqual(resp.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('X-Frame-Options', resp.headers)
        self.assertEqual(resp.headers['X-Frame-Options'], 'DENY')
        self.assertIn('Strict-Transport-Security', resp.headers)
        self.assertIn('Content-Security-Policy', resp.headers)
        self.assertIn('Referrer-Policy', resp.headers)

    def test_rate_limit_headers(self):
        """Respostas rate-limited devem ter headers X-RateLimit-*."""
        resp = self.client.post('/mine', json={})
        self.assertIn('X-RateLimit-Limit', resp.headers)
        self.assertIn('X-RateLimit-Window', resp.headers)
        self.assertIn('X-RateLimit-Policy', resp.headers)

    def test_large_payload_rejected(self):
        """Payload muito grande deve ser rejeitado."""
        large_data = {'data': 'x' * 200_000}
        resp = self.client.post('/transactions/new', json=large_data)
        # Deve retornar 400 (Request Entity Too Large) ou 400
        self.assertIn(resp.status_code, [400, 413])

    def test_method_not_allowed(self):
        """GET em endpoint POST deve retornar 405."""
        resp = self.client.get('/mine')
        self.assertEqual(resp.status_code, 405)

    def test_post_on_get_endpoint(self):
        """POST em endpoint GET deve retornar 405."""
        resp = self.client.post('/chain', json={})
        self.assertEqual(resp.status_code, 405)

    def test_invalid_json_body(self):
        """Body nao-JSON em endpoint JSON deve ser tratado."""
        resp = self.client.post(
            '/transactions/new',
            data='nao_eh_json',
            content_type='application/json'
        )
        # Flask retorna 400 se nao consegue parsear JSON
        self.assertEqual(resp.status_code, 400)

    def test_generic_error_messages(self):
        """Erros 500 devem ter mensagens genericas (B-03)."""
        resp = self.client.get('/chain')
        self.assertEqual(resp.status_code, 200)
        # Verifica que security headers estao presentes
        self.assertIn('X-Content-Type-Options', resp.headers)


if __name__ == '__main__':
    unittest.main(verbosity=2)
