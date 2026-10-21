#!/usr/bin/env python3
"""
Testes dos depósitos nativo → EVM (``evm/deposits.py``).

Cobre o crédito na EVM, o ledger persistido e a reconciliação no startup
(o estado EVM é em memória e recomeça do gênesis a cada processo).

Execute com: python -m pytest tests/test_deposits.py -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.blockchain import Blockchain
from core.transaction import Transaction
from core.wallet import Wallet
from evm.deposits import (
    credit_native_deposit,
    kur_to_wei,
    load_ledger,
    reconcile_native_deposits,
)
from evm.engine import EVMEngine


class TestNativeToEvmDeposits(unittest.TestCase):
    """Depósitos de endereços 0x vindos do ledger nativo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev_ledger = os.environ.get('EVM_DEPOSIT_LEDGER')
        os.environ['EVM_DEPOSIT_LEDGER'] = os.path.join(
            self._tmp.name, 'evm_deposits.json')
        self.chain = Blockchain(difficulty=1)
        self.engine = EVMEngine(auto_mine=True)
        self.miner = Wallet()
        self.receiver = '0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18'
        self.chain.mine_block(self.miner.address)

    def tearDown(self):
        if self._prev_ledger is None:
            os.environ.pop('EVM_DEPOSIT_LEDGER', None)
        else:
            os.environ['EVM_DEPOSIT_LEDGER'] = self._prev_ledger
        self._tmp.cleanup()

    def _send_native(self, amount: float) -> Transaction:
        tx = Transaction(
            sender=self.miner.public_key_pem,
            receiver=self.receiver,
            amount=amount,
            fee=0.001,
            sender_address=self.miner.address,
        )
        tx.sign(self.miner.private_key_pem)
        self.chain.add_transaction(
            sender=tx.sender,
            receiver=tx.receiver,
            amount=tx.amount,
            signature=tx.signature,
            sender_address=tx.sender_address,
            timestamp=tx.timestamp,
            fee=tx.fee,
            transaction_id=tx.transaction_id,
        )
        self.chain.mine_block(self.miner.address)
        return tx

    def test_kur_to_wei_exato(self):
        """Conversão usa Decimal (sem erro de ponto flutuante)."""
        self.assertEqual(kur_to_wei(0.1), 10 ** 17)
        self.assertEqual(kur_to_wei('1000'), 1000 * 10 ** 18)

    def test_reconcile_credits_native_deposits(self):
        """Depósitos já minerados são creditados na EVM e ficam no ledger."""
        first = self._send_native(250.0)
        second = self._send_native(50.0)

        report = reconcile_native_deposits(self.chain, self.engine)

        self.assertEqual(report['credited'], 2)
        self.assertEqual(report['failed'], [])
        self.assertEqual(self.engine.get_balance(self.receiver),
                         300 * 10 ** 18)

        ledger = load_ledger()
        self.assertIn(first.transaction_id, ledger)
        self.assertIn(second.transaction_id, ledger)
        self.assertTrue(
            ledger[first.transaction_id]['evm_tx_hash'].startswith('0x'))
        receipt = self.engine.get_transaction_receipt(
            ledger[first.transaction_id]['evm_tx_hash'])
        self.assertEqual(receipt['status'], '0x1')

    def test_reconcile_is_idempotent_in_process(self):
        """Chamar a reconciliação duas vezes no mesmo processo não duplica."""
        self._send_native(100.0)
        reconcile_native_deposits(self.chain, self.engine)
        report = reconcile_native_deposits(self.chain, self.engine)

        self.assertEqual(report['credited'], 0)
        self.assertEqual(self.engine.get_balance(self.receiver),
                         100 * 10 ** 18)

    def test_reconcile_after_chain_reload(self):
        """Simula restart: chain nativa recarregada do disco + EVM nova."""
        self._send_native(75.0)
        path = os.path.join(self._tmp.name, 'chain.json')
        self.chain.save_to_file(path)
        reloaded = Blockchain.load_from_file(path)

        fresh_engine = EVMEngine(auto_mine=True)
        report = reconcile_native_deposits(reloaded, fresh_engine)

        self.assertEqual(report['credited'], 1)
        self.assertEqual(fresh_engine.get_balance(self.receiver),
                         75 * 10 ** 18)

    def test_credit_rejects_non_evm_receiver(self):
        """Destino que não é 0x... não é crédito EVM."""
        with self.assertRaises(ValueError):
            credit_native_deposit(self.engine, self.miner.address, 10.0)

    def test_reserve_shortfall_is_reported(self):
        """Depósito maior que a reserva de dev falha sem quebrar o nó."""
        too_big = 20_000.0  # reserva do gênesis: 10.000 KUR
        tx = Transaction(
            sender=self.miner.public_key_pem,
            receiver=self.receiver,
            amount=too_big,
            fee=0.001,
            sender_address=self.miner.address,
        )
        # Cadeia falsa: só o objeto da tx importa para a reconciliação.
        fake_chain = type('FakeChain', (), {
            'chain': [type('FakeBlock', (), {'transactions': [tx]})()],
        })()
        report = reconcile_native_deposits(fake_chain, self.engine)
        self.assertEqual(report['credited'], 0)
        self.assertEqual(len(report['failed']), 1)


if __name__ == '__main__':
    unittest.main()
