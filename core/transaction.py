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

    A assinatura cobre sender, receiver, amount, timestamp E
    transaction_id, garantindo que nenhum campo pode ser alterado
    após a assinatura sem invalidá-la.
    """

    def __init__(self, sender: str, receiver: str, amount: float,
                 timestamp: float = None, signature: str = None,
                 transaction_id: str = None, sender_address: str = None,
                 nonce: str = None, fee: float = 0.0):
        """
        Inicializa uma nova transação.

        Args:
            sender: Endereço da carteira do remetente (ou "0" para coinbase)
            receiver: Endereço da carteira do destinatário
            amount: Quantidade a transferir
            timestamp: Timestamp Unix da criação (auto se None)
            signature: Assinatura digital (hex) ou None se não assinada
            transaction_id: ID único da transação
            nonce: Nonce criptográfico para unicidade
        """
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.fee = fee                  # Taxa paga ao minerador

        # ─── Validação de timestamp ───────────────────────────
        # Transações coinbase (sender='0') são criadas internamente
        # pelo sistema de mineração e não passam por validação.
        # Para transações normais, impede timestamps do futuro
        # (tolerância de 5 min) e timestamps muito antigos,
        # prevenindo ataques de replay.
        if sender == '0':
            # Coinbase: aceita timestamps internos sem validação
            self.timestamp = timestamp if timestamp is not None else time.time()
        elif timestamp is not None:
            now = time.time()
            if timestamp > now + 300:
                raise ValueError(
                    f"Timestamp da transação está no futuro: {timestamp}"
                )
            if timestamp < now - 7200:  # 2 horas máximo no passado
                raise ValueError(
                    f"Timestamp da transação é muito antigo: {timestamp}"
                )
            if timestamp < 0:
                raise ValueError(
                    f"Timestamp negativo: {timestamp}"
                )
            self.timestamp = timestamp
        else:
            self.timestamp = time.time()

        self.signature = signature
        self.transaction_id = transaction_id or self._generate_id()
        self.nonce = nonce
        self.sender_address = sender_address

    def _generate_id(self) -> str:
        """
        Gera um ID único para a transação baseado em seus dados
        e um nonce criptográfico.

        O nonce (entropia de os.urandom) garante que mesmo transações
        com mesmos sender, receiver, amount e timestamp gerem IDs
        diferentes, prevenindo colisões intencionais e ataques de replay.

        Returns:
            Hash SHA-256 único de 64 caracteres hex
        """
        nonce = CryptoUtils.generate_nonce()
        self.nonce = nonce
        raw = f"{self.sender}{self.receiver}{self.amount}{self.timestamp}{nonce}"
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
            'fee': self.fee,
            'timestamp': self.timestamp,
            'signature': self.signature,
            'nonce': self.nonce
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
            fee=data.get('fee', 0.0),
            timestamp=data.get('timestamp', time.time()),
            signature=data.get('signature'),
            transaction_id=data.get('transaction_id'),
            sender_address=data.get('sender_address'),
            nonce=data.get('nonce')
        )

    def get_data_for_signing(self) -> str:
        """
        Retorna a string que deve ser assinada.
        Inclui TODOS os campos imutáveis da transação:
        sender, receiver, amount, timestamp E transaction_id.

        A inclusão do transaction_id (com nonce) vincula a assinatura
        ao ID único, impedindo que um atacante substitua o ID
        após a assinatura (transação selada).

        Returns:
            String canônica para assinatura
        """
        data = {
            'sender': self.sender,
            'receiver': self.receiver,
            'amount': self.amount,
            'timestamp': self.timestamp,
            'transaction_id': self.transaction_id
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
        if self.fee < 0:
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
        fee_str = f" + {self.fee:.3f} fee" if self.fee > 0 else ""
        return (f"Transaction({self.transaction_id[:16]}... | "
                f"{self.sender[:16]}... → {self.receiver[:16]}... | "
                f"{self.amount:.2f} KUR{fee_str})")
