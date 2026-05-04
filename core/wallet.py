"""
Módulo de Carteira (Wallet).
Gerencia pares de chaves criptográficas e endereços.
Cada carteira pode gerar transações assinadas digitalmente.
"""
from .crypto_utils import CryptoUtils
from .transaction import Transaction


class Wallet:
    """
    Representa uma carteira na blockchain.

    A carteira não armazena saldo - ele é calculado pela blockchain
    varrendo todas as transações. A carteira armazena apenas as chaves
    criptográficas necessárias para assinar transações.
    """

    def __init__(self, private_key_pem: str = None):
        """
        Inicializa uma nova carteira.
        Gera um novo par de chaves se nenhuma for fornecida.

        Args:
            private_key_pem: Chave privada em PEM (opcional)
        """
        if private_key_pem:
            from ecdsa import SigningKey
            self._private_key = SigningKey.from_pem(private_key_pem.encode('utf-8'))
        else:
            self._private_key, self._public_key = CryptoUtils.generate_key_pair()
            self._address = CryptoUtils.public_key_to_address(
                self._public_key.to_pem().decode('utf-8')
            )
            return

        # Se a chave privada foi fornecida, derivamos a pública
        self._public_key = self._private_key.verifying_key

    @property
    def address(self) -> str:
        """
        Endereço público da carteira (derivado da chave pública).
        É o identificador usado para receber transações.
        """
        if not hasattr(self, '_address'):
            self._address = CryptoUtils.public_key_to_address(
                self._public_key.to_pem().decode('utf-8')
            )
        return self._address

    @property
    def public_key_pem(self) -> str:
        """Retorna a chave pública em formato PEM."""
        return self._public_key.to_pem().decode('utf-8')

    @property
    def private_key_pem(self) -> str:
        """Retorna a chave privada em formato PEM."""
        return self._private_key.to_pem().decode('utf-8')

    def create_transaction(self, receiver: str, amount: float) -> Transaction:
        """
        Cria e assina uma nova transação.

        Args:
            receiver: Endereço do destinatário
            amount: Quantidade a transferir

        Returns:
            Transação assinada pronta para ser enviada à rede
        """
        # A chave pública é usada como identificador do remetente
        # em vez do endereço, para permitir verificação da assinatura
        # O sender_address é usado para cálculo de saldo
        tx = Transaction(
            sender=self.public_key_pem,
            receiver=receiver,
            amount=amount,
            sender_address=self.address
        )
        tx.sign(self.private_key_pem)
        return tx

    def to_dict(self) -> dict:
        """
        Exporta a carteira para dicionário (para persistência segura).

        ATENÇÃO: A chave privada NUNCA deve ser compartilhada!
        """
        return {
            'address': self.address,
            'public_key': self.public_key_pem,
            'private_key': self.private_key_pem  # Mantenha seguro!
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Wallet':
        """Reconstrói uma carteira a partir de dados salvos."""
        return cls(private_key_pem=data['private_key'])

    def __str__(self) -> str:
        return f"Wallet(address={self.address[:16]}...)"
