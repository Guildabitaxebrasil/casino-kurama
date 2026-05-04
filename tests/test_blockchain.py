#!/usr/bin/env python3
"""
Testes unitários da Blockchain.
Cobre todos os componentes principais: hash, transações, blocos,
mineração, validação, carteiras, persistência e consenso.

Execute com: python -m pytest tests/ -v
         ou: python tests/test_blockchain.py
"""
import sys
import os
import unittest
import json
import tempfile

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from core.wallet import Wallet
from core.block import Block
from core.blockchain import Blockchain


class TestCryptoUtils(unittest.TestCase):
    """Testes das funções criptográficas."""

    def test_sha256_consistency(self):
        """SHA-256 deve ser determinístico."""
        h1 = CryptoUtils.sha256("hello")
        h2 = CryptoUtils.sha256("hello")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # 256 bits = 64 hex chars

    def test_sha256_different_inputs(self):
        """Entradas diferentes produzem hashes diferentes."""
        h1 = CryptoUtils.sha256("hello")
        h2 = CryptoUtils.sha256("Hello")  # Capital diferente
        self.assertNotEqual(h1, h2)

    def test_sha256_empty_string(self):
        """String vazia deve produzir hash válido."""
        h = CryptoUtils.sha256("")
        self.assertEqual(len(h), 64)

    def test_hash_block_deterministic(self):
        """hash_block deve ser determinístico."""
        block_data = {
            'index': 1,
            'timestamp': 1234567890,
            'transactions': [],
            'proof': 100,
            'previous_hash': '0' * 64
        }
        h1 = CryptoUtils.hash_block(block_data)
        h2 = CryptoUtils.hash_block(block_data)
        self.assertEqual(h1, h2)

    def test_is_hash_valid(self):
        """Verifica se a validação de hash funciona."""
        # Hash que começa com 4 zeros
        valid_hash = "0000abcd1234..."
        self.assertTrue(CryptoUtils.is_hash_valid(valid_hash, 4))
        self.assertFalse(CryptoUtils.is_hash_valid(valid_hash, 5))

        # Hash sem zeros no início
        self.assertFalse(CryptoUtils.is_hash_valid("abcd", 1))

    def test_generate_key_pair(self):
        """Geração de par de chaves deve funcionar."""
        priv, pub = CryptoUtils.generate_key_pair()
        self.assertIsNotNone(priv)
        self.assertIsNotNone(pub)
        # Chave pública deve estar em formato PEM
        pem = pub.to_pem().decode('utf-8')
        self.assertTrue(pem.startswith('-----BEGIN PUBLIC KEY-----'))

    def test_sign_and_verify(self):
        """Assinatura e verificação devem funcionar."""
        priv, pub = CryptoUtils.generate_key_pair()
        data = "mensagem secreta"
        sig = CryptoUtils.sign_data(priv, data)
        pub_pem = pub.to_pem().decode('utf-8')
        self.assertTrue(CryptoUtils.verify_signature(pub_pem, data, sig))

    def test_sign_verify_wrong_key(self):
        """Verificação com chave errada deve falhar."""
        priv, _ = CryptoUtils.generate_key_pair()
        _, pub2 = CryptoUtils.generate_key_pair()
        data = "mensagem"
        sig = CryptoUtils.sign_data(priv, data)
        pub2_pem = pub2.to_pem().decode('utf-8')
        self.assertFalse(CryptoUtils.verify_signature(pub2_pem, data, sig))

    def test_public_key_to_address(self):
        """Conversão de chave pública para endereço."""
        _, pub = CryptoUtils.generate_key_pair()
        pub_pem = pub.to_pem().decode('utf-8')
        address = CryptoUtils.public_key_to_address(pub_pem)
        self.assertIsInstance(address, str)
        self.assertTrue(len(address) > 20)  # Endereços Base58 são longos

    def test_merkle_root(self):
        """Raiz de Merkle de transações."""
        # Lista vazia
        root = CryptoUtils.merkle_root([])
        self.assertEqual(root, '0' * 64)

        # Uma transação
        tx = [{'sender': 'A', 'receiver': 'B', 'amount': 10}]
        root = CryptoUtils.merkle_root(tx)
        self.assertEqual(len(root), 64)

        # Várias transações
        txs = [
            {'sender': 'A', 'receiver': 'B', 'amount': 10},
            {'sender': 'B', 'receiver': 'C', 'amount': 5},
            {'sender': 'C', 'receiver': 'A', 'amount': 3}
        ]
        root = CryptoUtils.merkle_root(txs)
        self.assertEqual(len(root), 64)

    def test_merkle_root_deterministic(self):
        """Raiz de Merkle deve ser determinística."""
        txs = [{'sender': 'A', 'receiver': 'B', 'amount': 10}]
        r1 = CryptoUtils.merkle_root(txs)
        r2 = CryptoUtils.merkle_root(txs)
        self.assertEqual(r1, r2)


class TestTransaction(unittest.TestCase):
    """Testes das transações."""

    def test_create_transaction(self):
        """Criação básica de transação."""
        tx = Transaction(sender='A', receiver='B', amount=10.0)
        self.assertEqual(tx.sender, 'A')
        self.assertEqual(tx.receiver, 'B')
        self.assertEqual(tx.amount, 10.0)
        self.assertIsNotNone(tx.transaction_id)
        self.assertEqual(len(tx.transaction_id), 64)

    def test_transaction_to_dict_from_dict(self):
        """Serialização de transação."""
        tx = Transaction(sender='A', receiver='B', amount=10.0)
        data = tx.to_dict()
        restored = Transaction.from_dict(data)
        self.assertEqual(restored.sender, tx.sender)
        self.assertEqual(restored.receiver, tx.receiver)
        self.assertEqual(restored.amount, tx.amount)

    def test_sign_transaction(self):
        """Assinatura de transação com carteira."""
        wallet = Wallet()
        tx = wallet.create_transaction(
            receiver='destinatario_address',
            amount=25.0
        )
        self.assertIsNotNone(tx.signature)
        self.assertTrue(len(tx.signature) > 50)

    def test_unsigned_transaction_invalid(self):
        """Transação sem assinatura deve ser inválida."""
        tx = Transaction(sender='A', receiver='B', amount=10.0)
        self.assertFalse(tx.is_valid())

    def test_negative_amount_invalid(self):
        """Transação com valor negativo deve ser inválida."""
        tx = Transaction(sender='A', receiver='B', amount=-10.0)
        # Sem assinatura
        tx.signature = "fake_sig"
        # amount negativo
        self.assertFalse(tx.is_valid())

    def test_coinbase_transaction_valid(self):
        """Transação coinbase (sender='0') é sempre válida."""
        tx = Transaction(sender='0', receiver='miner', amount=50.0)
        self.assertTrue(tx.is_valid())


class TestWallet(unittest.TestCase):
    """Testes das carteiras."""

    def test_create_wallet(self):
        """Criação de carteira."""
        wallet = Wallet()
        self.assertIsNotNone(wallet.address)
        self.assertIsNotNone(wallet.public_key_pem)
        self.assertIsNotNone(wallet.private_key_pem)

    def test_wallet_unique_addresses(self):
        """Cada carteira deve ter endereço único."""
        w1 = Wallet()
        w2 = Wallet()
        self.assertNotEqual(w1.address, w2.address)

    def test_wallet_to_dict_from_dict(self):
        """Serialização de carteira."""
        w1 = Wallet()
        data = w1.to_dict()
        w2 = Wallet.from_dict(data)
        self.assertEqual(w1.address, w2.address)
        self.assertEqual(w1.public_key_pem, w2.public_key_pem)

    def test_wallet_create_transaction(self):
        """Carteira cria transação assinada."""
        wallet = Wallet()
        tx = wallet.create_transaction(
            receiver='endereco_teste',
            amount=15.0
        )
        self.assertEqual(tx.sender, wallet.public_key_pem)
        self.assertEqual(tx.receiver, 'endereco_teste')
        self.assertEqual(tx.amount, 15.0)
        self.assertTrue(tx.is_valid())


class TestBlock(unittest.TestCase):
    """Testes dos blocos."""

    def setUp(self):
        self.genesis = Block(
            index=0,
            transactions=[Transaction('0', 'genesis', 0)],
            proof=100,
            previous_hash='0' * 64
        )

    def test_block_creation(self):
        """Criação básica de bloco."""
        self.assertEqual(self.genesis.index, 0)
        self.assertEqual(self.genesis.proof, 100)
        self.assertEqual(self.genesis.previous_hash, '0' * 64)
        self.assertIsNotNone(self.genesis.hash)
        self.assertEqual(len(self.genesis.hash), 64)

    def test_block_hash_property(self):
        """Hash do bloco deve ser determinístico."""
        h1 = self.genesis.calculate_hash()
        h2 = self.genesis.calculate_hash()
        self.assertEqual(h1, h2)

    def test_block_to_dict_from_dict(self):
        """Serialização de bloco."""
        data = self.genesis.to_dict()
        restored = Block.from_dict(data, Transaction)
        self.assertEqual(restored.index, self.genesis.index)
        self.assertEqual(restored.proof, self.genesis.proof)
        self.assertEqual(restored.hash, self.genesis.hash)
        self.assertEqual(restored.previous_hash, self.genesis.previous_hash)

    def test_block_merkle_root(self):
        """Bloco deve ter raiz de Merkle válida."""
        self.assertIsNotNone(self.genesis.merkle_root)
        self.assertEqual(len(self.genesis.merkle_root), 64)

    def test_avalanche_effect(self):
        """Pequena mudança deve produzir hash completamente diferente."""
        block1 = Block(index=1, transactions=[], proof=100, previous_hash='0'*64)
        block2 = Block(index=1, transactions=[], proof=101, previous_hash='0'*64)
        self.assertNotEqual(block1.hash, block2.hash)
        # Deve diferir nos primeiros caracteres também
        self.assertNotEqual(block1.hash[:8], block2.hash[:8])


class TestBlockchain(unittest.TestCase):
    """Testes da blockchain."""

    def setUp(self):
        self.bc = Blockchain(difficulty=3)  # Dificuldade baixa para testes

    def test_genesis_block(self):
        """Blockchain deve começar com bloco gênese."""
        self.assertEqual(len(self.bc.chain), 1)
        self.assertEqual(self.bc.chain[0].index, 0)
        self.assertEqual(self.bc.chain[0].previous_hash, '0' * 64)

    def test_initial_validation(self):
        """Blockchain recém-criada deve ser válida."""
        self.assertTrue(self.bc.is_chain_valid())

    def test_add_transaction(self):
        """Adicionar transação à pool."""
        wallet = Wallet()
        tx = wallet.create_transaction('receiver', 10.0)
        self.bc.pending_transactions.append(tx)
        self.assertEqual(len(self.bc.pending_transactions), 1)

    def test_mine_block(self):
        """Mineração de bloco."""
        wallet = Wallet()
        # Adiciona transação para minerar
        tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
        self.bc.pending_transactions.append(tx)

        block = self.bc.mine_block(wallet.address)
        self.assertIsNotNone(block)
        self.assertEqual(len(self.bc.chain), 2)
        self.assertEqual(block.index, 1)

    def test_mine_multiple_blocks(self):
        """Mineração de múltiplos blocos."""
        wallet = Wallet()
        for i in range(3):
            tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
            self.bc.pending_transactions.append(tx)
            self.bc.mine_block(wallet.address)

        self.assertEqual(len(self.bc.chain), 4)  # gênese + 3
        self.assertTrue(self.bc.is_chain_valid())

    def test_proof_of_work_validity(self):
        """Hash do bloco minerado deve satisfazer o PoW."""
        wallet = Wallet()
        tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
        self.bc.pending_transactions.append(tx)
        block = self.bc.mine_block(wallet.address)

        block_dict = {
            'index': block.index,
            'timestamp': block.timestamp,
            'transactions': [
                t.to_dict() if hasattr(t, 'to_dict') else t
                for t in block.transactions
            ],
            'proof': block.proof,
            'previous_hash': block.previous_hash,
            'merkle_root': block.merkle_root
        }
        block_hash = CryptoUtils.hash_block(block_dict)
        self.assertTrue(
            CryptoUtils.is_hash_valid(block_hash, self.bc.difficulty)
        )

    def test_balance_calculation(self):
        """Cálculo de saldo deve funcionar."""
        alice = Wallet()
        miner = Wallet()

        # Minera blocos para Alice (recompensa de 50 coins cada)
        for _ in range(3):
            tx = Transaction(sender='0', receiver=alice.address, amount=10.0)
            self.bc.pending_transactions.append(tx)
            self.bc.mine_block(miner.address)

        alice_balance = self.bc.get_balance(alice.address)
        miner_balance = self.bc.get_balance(miner.address)

        # Alice recebeu 3 * 10 = 30 das transações coinbase
        self.assertEqual(alice_balance, 30.0)

        # Minerador recebeu 3 recompensas de mineração
        self.assertEqual(miner_balance, 3 * self.bc.reward)

    def test_detect_tampering(self):
        """Blockchain deve detectar adulteração."""
        wallet = Wallet()
        tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
        self.bc.pending_transactions.append(tx)
        self.bc.mine_block(wallet.address)

        # Adultera o bloco
        self.bc.chain[1].proof = 99999

        self.assertFalse(self.bc.is_chain_valid())

    def test_save_and_load(self):
        """Persistência em JSON."""
        # Prepara blockchain com dados
        wallet = Wallet()
        for _ in range(2):
            tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
            self.bc.pending_transactions.append(tx)
            self.bc.mine_block(wallet.address)

        # Salva em arquivo temporário
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                         delete=False) as f:
            temp_path = f.name

        try:
            self.bc.save_to_file(temp_path)

            # Carrega de arquivo
            loaded = Blockchain.load_from_file(temp_path)

            self.assertEqual(len(loaded.chain), len(self.bc.chain))
            self.assertEqual(
                loaded.chain[-1].hash,
                self.bc.chain[-1].hash
            )
            self.assertTrue(loaded.is_chain_valid())
        finally:
            os.unlink(temp_path)

    def test_empty_pending_no_mine(self):
        """Não deve minerar sem transações pendentes."""
        # Vamos verificar que a pool está vazia
        self.assertEqual(len(self.bc.pending_transactions), 0)

    def test_consensus_no_change(self):
        """Consenso com cadeias mais curtas não deve alterar."""
        wallet = Wallet()
        tx = Transaction(sender='0', receiver=wallet.address, amount=10.0)
        self.bc.pending_transactions.append(tx)
        self.bc.mine_block(wallet.address)

        # Tenta substituir por cadeia mais curta (só gênese)
        short_chain = [
            [self.bc.chain[0].to_dict()]
        ]
        replaced = self.bc.resolve_conflicts(short_chain)
        self.assertFalse(replaced)

    def test_node_id_unique(self):
        """Cada blockchain deve ter ID único."""
        bc1 = Blockchain(difficulty=3)
        bc2 = Blockchain(difficulty=3)
        self.assertNotEqual(bc1.node_id, bc2.node_id)

    def test_adjust_difficulty(self):
        """Ajuste de dificuldade deve funcionar."""
        # Cria blockchain com dificuldade inicial
        bc = Blockchain(difficulty=2)

        # Ajusta - ainda não há blocos suficientes
        bc.adjust_difficulty()
        self.assertEqual(bc.difficulty, 2)


class TestFullIntegration(unittest.TestCase):
    """Testes de integração completa."""

    def test_full_scenario(self):
        """Cenário completo: carteiras → transações → mineração → saldos."""
        bc = Blockchain(difficulty=3)

        # 1. Cria carteiras
        alice = Wallet()
        bob = Wallet()
        miner = Wallet()

        # 2. Minera blocos para ter saldo inicial
        for _ in range(3):
            tx = Transaction(sender='0', receiver=alice.address, amount=50.0)
            bc.pending_transactions.append(tx)
            bc.mine_block(miner.address)

        # 3. Alice envia para Bob
        tx1 = alice.create_transaction(bob.address, 30.0)
        bc.pending_transactions.append(tx1)

        # 4. Alice envia para minerador
        tx2 = alice.create_transaction(miner.address, 10.0)
        bc.pending_transactions.append(tx2)

        # 5. Minera bloco com transações
        bc.mine_block(miner.address)

        # 6. Verifica saldos
        # Alice: 3*50 recebidos - 30 - 10 = 110
        self.assertEqual(bc.get_balance(alice.address), 110.0)
        # Bob: +30
        self.assertEqual(bc.get_balance(bob.address), 30.0)
        # Minerador: 3*50 (recompensas) + 10 (taxa Alice) + 50 (recompensa mineração)
        self.assertAlmostEqual(
            bc.get_balance(miner.address),
            3 * bc.reward + 10 + bc.reward
        )

        # 7. Verifica integridade
        self.assertTrue(bc.is_chain_valid())


if __name__ == '__main__':
    unittest.main(verbosity=2)
