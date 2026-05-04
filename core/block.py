"""
Módulo do Bloco.
Define a estrutura fundamental da blockchain.
Cada bloco contém transações, um hash, referência ao bloco anterior
e um nonce descoberto pelo processo de mineração (Proof of Work).
"""
import time
from .crypto_utils import CryptoUtils


class Block:
    """
    Representa um bloco na blockchain.

    Um bloco é a unidade fundamental da blockchain. Cada bloco contém:
    - Índice (posição na cadeia)
    - Timestamp (quando foi minerado)
    - Transações (dados armazenados)
    - Proof (nonce do Proof of Work)
    - Previous hash (liga ao bloco anterior)
    - Hash atual (identificador único do bloco)
    - Merkle root (resumo criptográfico das transações)
    """

    def __init__(self, index: int, transactions: list, proof: int,
                 previous_hash: str, timestamp: float = None,
                 hash_value: str = None, merkle_root: str = None,
                 difficulty: int = None):
        """
        Inicializa um novo bloco.

        Args:
            index: Posição do bloco na cadeia (0 = gênese)
            transactions: Lista de transações no bloco
            proof: Nonce descoberto pelo Proof of Work
            previous_hash: Hash do bloco anterior
            timestamp: Timestamp Unix da criação
            hash_value: Hash calculado do bloco (calculado se None)
            merkle_root: Raiz de Merkle das transações
            difficulty: Dificuldade do PoW usada na mineração
        """
        self.index = index
        self.timestamp = timestamp or time.time()
        self.transactions = transactions or []
        self.proof = proof
        self.previous_hash = previous_hash
        self.difficulty = difficulty  # None para bloco gênese
        self.merkle_root = merkle_root or CryptoUtils.merkle_root(
            [tx.to_dict() if hasattr(tx, 'to_dict') else tx
             for tx in self.transactions]
        )
        self.hash = hash_value or self.calculate_hash()

    def calculate_hash(self) -> str:
        """
        Calcula o hash criptográfico do bloco.
        O hash é a "impressão digital" do bloco - qualquer alteração
        mínima nos dados produz um hash completamente diferente.

        O hash inclui: index, timestamp, transações, proof e previous_hash.
        Isso garante a imutabilidade da cadeia.

        Returns:
            Hash SHA-256 do bloco (64 caracteres hex)
        """
        block_data = {
            'index': self.index,
            'timestamp': self.timestamp,
            'transactions': [
                tx.to_dict() if hasattr(tx, 'to_dict') else tx
                for tx in self.transactions
            ],
            'proof': self.proof,
            'previous_hash': self.previous_hash,
            'merkle_root': self.merkle_root
        }
        return CryptoUtils.hash_block(block_data)

    def to_dict(self) -> dict:
        """
        Converte o bloco para dicionário (serializável em JSON).

        Returns:
            Dicionário completo do bloco
        """
        result = {
            'index': self.index,
            'timestamp': self.timestamp,
            'transactions': [
                tx.to_dict() if hasattr(tx, 'to_dict') else tx
                for tx in self.transactions
            ],
            'proof': self.proof,
            'previous_hash': self.previous_hash,
            'merkle_root': self.merkle_root,
            'hash': self.hash
        }
        if self.difficulty is not None:
            result['difficulty'] = self.difficulty
        return result

    @classmethod
    def from_dict(cls, data: dict, transaction_class=None) -> 'Block':
        """
        Reconstrói um bloco a partir de um dicionário.

        Args:
            data: Dicionário com dados do bloco
            transaction_class: Classe de transação para reconstruir objetos

        Returns:
            Nova instância de Block
        """
        transactions = data.get('transactions', [])

        # Se uma classe de transação foi fornecida, reconstrói os objetos
        if transaction_class and transactions:
            transactions = [
                transaction_class.from_dict(tx) if hasattr(tx, 'from_dict') else tx
                for tx in transactions
            ]

        return cls(
            index=data['index'],
            transactions=transactions,
            proof=data['proof'],
            previous_hash=data['previous_hash'],
            timestamp=data.get('timestamp'),
            hash_value=data.get('hash'),
            merkle_root=data.get('merkle_root'),
            difficulty=data.get('difficulty')
        )

    def is_valid_transactions(self) -> bool:
        """
        Verifica se todas as transações no bloco são válidas.
        Isso inclui verificar assinaturas e valores.

        Returns:
            True se todas as transações são válidas
        """
        for tx in self.transactions:
            if hasattr(tx, 'is_valid') and not tx.is_valid():
                return False
        return True

    def __str__(self) -> str:
        """Representação legível do bloco."""
        return (f"Block #{self.index} | "
                f"Proof: {self.proof} | "
                f"Txns: {len(self.transactions)} | "
                f"Hash: {self.hash[:16]}... | "
                f"Prev: {self.previous_hash[:16]}...")

    def __repr__(self) -> str:
        return self.__str__()
