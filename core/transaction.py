"""
Módulo de Transação.
Define a estrutura de uma transação na blockchain.
Cada transação contém remetente, destinatário, valor, assinatura
e outros metadados para garantir segurança e rastreabilidade.
"""
import time
import json
from .crypto_utils import CryptoUtils


class Transaction:
    """
    Representa uma transação na blockchain.

    Uma transação transfere valor de uma carteira para outra e é
    assinada digitalmente pelo remetente para garantir autenticidade.
    """

    def __init__(self, sender: str, receiver: str, amount: float,
                 timestamp: float = None, signature: str = None,
                 transaction_id: str = None, sender_address: str = None):
        """
        Inicializa uma nova transação.

        Args:
            sender: Endereço da carteira do remetente (ou "0" para coinbase)
            receiver: Endereço da carteira do destinatário
            amount: Quantidade a transferir
            timestamp: Timestamp Unix da criação (auto se None)
            signature: Assinatura digital (hex) ou None se não assinada
            transaction_id: ID único da transação
        """
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.timestamp = timestamp or time.time()
        self.signature = signature
        self.transaction_id = transaction_id or self._generate_id()
        self.sender_address = sender_address

    def _generate_id(self) -> str:
        """
        Gera um ID único para a transação baseado em seus dados.
        Isso garante que cada transação seja identificável de forma única.
        """
        raw = f"{self.sender}{self.receiver}{self.amount}{self.timestamp}"
        return CryptoUtils.sha256(raw)

    def to_dict(self) -> dict:
        """
        Converte a transação para dicionário (serializável em JSON).

        Returns:
            Dicionário com todos os campos da transação
        """
        result = {
            'transaction_id': self.transaction_id,
            'sender': self.sender,
            'receiver': self.receiver,
            'amount': self.amount,
            'timestamp': self.timestamp,
            'signature': self.signature
        }
        if self.sender_address:
            result['sender_address'] = self.sender_address
        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'Transaction':
        """
        Reconstrói uma transação a partir de um dicionário.

        Args:
            data: Dicionário com dados da transação

        Returns:
            Nova instância de Transaction
        """
        return cls(
            sender=data['sender'],
            receiver=data['receiver'],
            amount=data['amount'],
            timestamp=data.get('timestamp', time.time()),
            signature=data.get('signature'),
            transaction_id=data.get('transaction_id'),
            sender_address=data.get('sender_address')
        )

    def get_data_for_signing(self) -> str:
        """
        Retorna a string que deve ser assinada.
        Inclui apenas os campos imutáveis da transação.

        Returns:
            String canônica para assinatura
        """
        data = {
            'sender': self.sender,
            'receiver': self.receiver,
            'amount': self.amount,
            'timestamp': self.timestamp
        }
        return json.dumps(data, sort_keys=True)

    def sign(self, private_key_pem: str) -> str:
        """
        Assina a transação com a chave privada do remetente.
        A assinatura prova que o dono da carteira autorizou a transferência.

        Args:
            private_key_pem: Chave privada em formato PEM

        Raises:
            ValueError: Se sender é "0" (transação coinbase não deve ser assinada)
        """
        if self.sender == '0':
            raise ValueError("Transações coinbase (mineração) não são assinadas")

        from ecdsa import SigningKey
        sk = SigningKey.from_pem(private_key_pem.encode('utf-8'))
        sig_bytes = CryptoUtils.sign_data(sk, self.get_data_for_signing())
        self.signature = sig_bytes.hex()
        return self.signature

    def is_valid(self) -> bool:
        """
        Valida a transação:
        1. Verifica se valores são positivos
        2. Verifica a assinatura (se não for coinbase)

        Returns:
            True se a transação é válida
        """
        # Transação coinbase (recompensa de mineração) é sempre válida
        if self.sender == '0':
            return True

        # Verificações básicas de integridade
        if self.amount <= 0:
            return False
        if not self.sender or not self.receiver:
            return False
        if not self.signature:
            return False

        # Verificação da assinatura digital
        try:
            sig_bytes = bytes.fromhex(self.signature)
            return CryptoUtils.verify_signature(
                self.sender,  # Neste projeto, usamos a chave pública como sender
                self.get_data_for_signing(),
                sig_bytes
            )
        except Exception:
            return False

    def __str__(self) -> str:
        """Representação legível da transação."""
        return (f"Transaction({self.transaction_id[:16]}... | "
                f"{self.sender[:16]}... → {self.receiver[:16]}... | "
                f"{self.amount:.2f} coins)")
