#!/usr/bin/env python3
"""
Testes do minerador (miner.py) — Proof of Work na CPU.

Sobe um nó Flask real em uma porta livre e minera de verdade: o
minerador pede o template, resolve o nonce na CPU e entrega o bloco
pronto ao nó, como em produção. Execute com:

    python -m pytest tests/test_miner.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from werkzeug.serving import make_server

import miner
from api.routes import create_app
from core.blockchain import Blockchain
from core.crypto_utils import CryptoUtils
from core.wallet import Wallet


class TestProofOfWork(unittest.TestCase):
    """Hash e busca de nonce — precisam bater com a regra do nó."""

    def setUp(self):
        self.blockchain = Blockchain(difficulty=2)
        self.wallet = Wallet()
        self.template = self.blockchain.create_mining_template(
            self.wallet.address)

    def test_hash_matches_node_rule(self):
        """O hash do minerador é o mesmo que o nó calcula."""
        template = {**self.template, 'proof': 0}
        expected = CryptoUtils.hash_block(
            {k: template[k] for k in miner.HASH_FIELDS})
        self.assertEqual(miner.block_hash(template), expected)

    def test_prepare_pow_rebuilds_json(self):
        """Prefixo + nonce + sufixo = JSON canônico do bloco."""
        prefix, suffix = miner.prepare_pow(self.template)
        expected = miner.hash_input({**self.template, 'proof': 7})
        self.assertEqual(prefix + b'7' + suffix, expected.encode('utf-8'))

    def test_prepare_pow_ignores_metadata(self):
        """Campos como difficulty/reward não entram no hash."""
        prefix, suffix = miner.prepare_pow(self.template)
        rebuilt = json.loads((prefix + b'0' + suffix).decode('utf-8'))
        self.assertEqual(set(rebuilt), set(miner.HASH_FIELDS))

    def test_solve_finds_valid_nonce(self):
        """O nonce devolvido faz o hash começar com os zeros exigidos."""
        proof = miner.solve(self.template, out=lambda *a: None)
        solved = {**self.template, 'proof': proof}
        self.assertTrue(
            miner.is_valid_hash(miner.block_hash(solved),
                                self.template['difficulty']))

    def test_rule_matches_node_for_fractional_difficulty(self):
        """A regra do minerador é idêntica à do nó, inclusive com fração."""
        for difficulty in (2, 2.2, 2.5, 2.9, 3):
            self.assertEqual(miner.difficulty_digits(difficulty),
                             CryptoUtils.difficulty_digits(difficulty))
            for digit in '0123456789abcdef':
                hash_hex = '00' + digit + 'f' * 61
                self.assertEqual(
                    miner.is_valid_hash(hash_hex, difficulty),
                    CryptoUtils.is_hash_valid(hash_hex, difficulty))

    def test_solve_fractional_difficulty(self):
        """O nonce encontrado vale para a dificuldade quebrada do template."""
        template = {**self.template, 'difficulty': 2.4}
        proof = miner.solve(template, out=lambda *a: None)
        solved = {**template, 'proof': proof}

        self.assertTrue(
            miner.is_valid_hash(miner.block_hash(solved), 2.4))

    def test_format_hashrate(self):
        self.assertEqual(miner.format_hashrate(999), '999 H/s')
        self.assertEqual(miner.format_hashrate(2500), '2.5 kH/s')
        self.assertEqual(miner.format_hashrate(2_500_000), '2.50 MH/s')


class TestMinerAgainstNode(unittest.TestCase):
    """Minerador falando com um nó real (Flask em thread, HTTP puro)."""

    @classmethod
    def setUpClass(cls):
        # Dificuldade 2 só para o PoW não dominar o tempo de teste; o
        # caminho exercitado (template → nonce → submit) é o de produção.
        cls.app = create_app(blockchain=Blockchain(difficulty=2), port=0)
        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base_url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.client = miner.NodeClient(cls.base_url)
        cls.wallet = Wallet()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_block_count(self):
        self.assertGreaterEqual(self.client.block_count(), 1)

    def test_template_fits_the_chain_tip(self):
        """O template vem no topo da cadeia e com a dificuldade atual."""
        template = self.client.template(self.wallet.address)
        chain = self.app.blockchain.chain

        self.assertEqual(template['index'], len(chain))
        self.assertEqual(template['previous_hash'], chain[-1].hash)
        self.assertEqual(template['difficulty'], self.app.blockchain.difficulty)
        self.assertEqual(template['transactions'][0]['receiver'],
                         self.wallet.address)
        self.assertGreater(template['reward'], 0)

    def test_template_rejects_invalid_address(self):
        with self.assertRaises(miner.MinerError) as ctx:
            self.client.template('endereco_invalido')
        self.assertEqual(ctx.exception.status, 400)
        self.assertFalse(ctx.exception.retryable)

    def test_submit_solved_block(self):
        """Bloco com o nonce resolvido na CPU é aceito e paga a coinbase."""
        before = self.client.block_count()
        template = self.client.template(self.wallet.address)
        template['proof'] = miner.solve(template, out=lambda *a: None)
        template['hash'] = miner.block_hash(template)

        result = self.client.submit(template)

        self.assertEqual(result['miner_address'], self.wallet.address)
        self.assertEqual(result['block']['index'], before)
        self.assertEqual(self.client.block_count(), before + 1)
        self.assertGreater(result['total_reward'], 0)
        self.assertGreaterEqual(result['miner_balance'], 0)

    def test_submit_unsolved_block_is_rejected(self):
        """Sem Proof of Work o nó recusa (nada de bloco de graça)."""
        template = self.client.template(self.wallet.address)
        template['proof'] = 0  # sorte não garantida em dificuldade 2
        template['hash'] = miner.block_hash(template)

        with self.assertRaises(miner.MinerError) as ctx:
            self.client.submit(template)
        self.assertEqual(ctx.exception.status, 409)

    def test_submit_stale_template_is_rejected(self):
        """Template velho (outro bloco entrou) é 409 → pedir um novo."""
        template = self.client.template(self.wallet.address)
        template['proof'] = miner.solve(template, out=lambda *a: None)
        template['hash'] = miner.block_hash(template)
        self.client.submit(template)

        with self.assertRaises(miner.MinerError) as ctx:
            self.client.submit(template)
        self.assertEqual(ctx.exception.status, 409)
        self.assertTrue(ctx.exception.stale)

    def test_mine_forever_mines_two_blocks(self):
        start = time.time()

        mined = miner.mine_forever(
            self.client, address=self.wallet.address,
            max_blocks=2, out=lambda *a: None)

        self.assertEqual(mined, 2)
        self.assertGreaterEqual(time.time() - start, 0)

    def test_main_returns_done_after_blocks(self):
        """`python miner.py --blocks 1` minera um bloco e sai com 0."""
        code = miner.main([
            '--url', self.base_url,
            '--address', self.wallet.address,
            '--blocks', '1',
        ])
        self.assertEqual(code, 0)


class TestNodeRestart(unittest.TestCase):
    """
    Reinício do nó: a cadeia minerada volta do disco.

    Repete o ciclo de produção — minerar, derrubar o nó, subir de novo com
    `Blockchain.load_from_file` (o que `run.py --load` faz) — e confere que
    o bloco aceito continua lá e serve de base para o próximo.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chain_file = os.path.join(self.tmp.name, 'blockchain.json')
        self.wallet = Wallet()
        self.servers = []

    def tearDown(self):
        for server, _ in self.servers:
            server.shutdown()
        self.tmp.cleanup()

    def _start_node(self, blockchain):
        """Sobe um nó em porta livre com o autosave que o run.py registra."""
        blockchain.on('on_block_mined',
                      lambda block: blockchain.save_to_file(self.chain_file))
        app = create_app(blockchain=blockchain, port=0)
        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return miner.NodeClient(f'http://127.0.0.1:{server.server_port}')

    def _mine_one_block(self, client):
        """Pede template, resolve o PoW na CPU e entrega o bloco ao nó."""
        template = client.template(self.wallet.address)
        template['proof'] = miner.solve(template, out=lambda *a: None)
        template['hash'] = miner.block_hash(template)
        return client.submit(template)

    def test_mined_chain_survives_restart(self):
        # 1. Nó no ar: o minerador entrega um bloco.
        client = self._start_node(Blockchain(difficulty=2))
        result = self._mine_one_block(client)
        mined = result['block']
        height = client.block_count()
        balance = result['miner_balance']

        # 2. Nó cai logo depois: o bloco já precisa estar no disco.
        server, thread = self.servers.pop()
        server.shutdown()
        thread.join(timeout=5)

        self.assertTrue(os.path.exists(self.chain_file))
        self.assertFalse(os.path.exists(self.chain_file + '.tmp'))
        with open(self.chain_file, encoding='utf-8') as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk['chain'][-1]['hash'], mined['hash'])
        self.assertEqual(on_disk['difficulty'], 2)

        # 3. Sobe de novo carregando o arquivo: nada foi perdido.
        reloaded = Blockchain.load_from_file(self.chain_file)
        client_after = self._start_node(reloaded)

        self.assertEqual(client_after.block_count(), height)
        self.assertEqual(reloaded.chain[-1].hash, mined['hash'])
        self.assertEqual(reloaded.chain[-1].proof, mined['proof'])
        self.assertEqual(reloaded.get_balance(self.wallet.address), balance)
        self.assertTrue(reloaded.is_chain_valid())

        # 4. E a cadeia recarregada aceita o próximo bloco do minerador.
        next_result = self._mine_one_block(client_after)

        self.assertEqual(next_result['block']['index'], height)
        self.assertEqual(next_result['block']['previous_hash'], mined['hash'])
        self.assertEqual(client_after.block_count(), height + 1)
        self.assertTrue(reloaded.is_chain_valid())


if __name__ == '__main__':
    unittest.main()
