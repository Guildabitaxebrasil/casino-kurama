#!/usr/bin/env python3
"""
Testes do minerador automático (miner.py).

Sobe um nó Flask real em uma porta livre e minera por HTTP, como o
minerador faz em produção. Execute com:

    python -m pytest tests/test_miner.py -v
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from werkzeug.serving import make_server

import miner
from api.routes import create_app
from core.blockchain import Blockchain
from core.wallet import Wallet


class TestSlotScheduling(unittest.TestCase):
    """Matemática do slot de 10 minutos (padrão Bitcoin)."""

    def test_wait_full_slot(self):
        """No início do slot, espera o intervalo inteiro."""
        self.assertAlmostEqual(
            miner.seconds_until_next_slot(1_000.0, 600, now=1_000.0), 600.0)

    def test_wait_remaining(self):
        """No meio do slot, espera só o restante."""
        self.assertAlmostEqual(
            miner.seconds_until_next_slot(1_000.0, 600, now=1_300.0), 300.0)

    def test_wait_zero_when_late(self):
        """Slot vencido minera na hora."""
        self.assertEqual(
            miner.seconds_until_next_slot(1_000.0, 600, now=5_000.0), 0.0)

    def test_wait_without_last_block(self):
        """Sem bloco anterior, não espera."""
        self.assertEqual(miner.seconds_until_next_slot(None, 600), 0.0)


class TestMinerAgainstNode(unittest.TestCase):
    """Minerador falando com um nó real (Flask em thread, HTTP puro)."""

    @classmethod
    def setUpClass(cls):
        # Dificuldade 2 só para o PoW não dominar o tempo de teste; o
        # caminho exercitado (HTTP /mine + scheduling) é o de produção.
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
        """O cliente lê a altura da cadeia do nó."""
        self.assertGreaterEqual(self.client.block_count(), 1)

    def test_mine_one_block(self):
        """POST /mine cria um bloco e paga a coinbase."""
        before = self.client.block_count()

        result = self.client.mine(self.wallet.address)

        self.assertEqual(result['miner_address'], self.wallet.address)
        self.assertGreater(result['total_reward'], 0)
        self.assertEqual(result['block']['index'], before)
        self.assertEqual(self.client.block_count(), before + 1)

    def test_mine_invalid_address_is_not_retryable(self):
        """Endereço inválido (HTTP 400) para o minerador, não fica em loop."""
        with self.assertRaises(miner.MinerError) as ctx:
            self.client.mine('endereco_invalido')
        self.assertEqual(ctx.exception.status, 400)
        self.assertFalse(ctx.exception.retryable)

    def test_mine_forever_waits_between_blocks(self):
        """Duas mineradas respeitam o intervalo entre slots."""
        start = time.time()

        mined = miner.mine_forever(
            self.client, address=self.wallet.address,
            interval=0.3, max_blocks=2, out=lambda *a: None)

        elapsed = time.time() - start
        self.assertEqual(mined, 2)
        self.assertGreaterEqual(elapsed, 0.3)

    def test_main_returns_done_after_blocks(self):
        """`python miner.py --blocks 1` minera um bloco e sai com 0."""
        code = miner.main([
            '--url', self.base_url,
            '--address', self.wallet.address,
            '--interval', '0.2',
            '--blocks', '1',
        ])
        self.assertEqual(code, 0)

    def test_main_rejects_zero_interval(self):
        """Intervalo inválido falha antes de tentar falar com o nó."""
        self.assertEqual(miner.main(['--interval', '0']), 2)


if __name__ == '__main__':
    unittest.main()
