"""
Módulo de Carteira (Wallet).
Gerencia pares de chaves criptográficas e endereços.
Cada carteira pode gerar transações assinadas digitalmente.

Recursos de Segurança:
- AES-256-GCM para criptografia de carteiras em repouso
- PBKDF2-HMAC-SHA256 (100k iterações) para derivação de chave
- Nonce único (12 bytes) por operação de criptografia
- Tag de autenticação GCM de 128 bits (detecta adulteração)
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
        Endereço público da carteira (Base58 Kurama nativo).
        É o identificador usado para receber transações.
        """
        if not hasattr(self, '_address'):
            self._address = CryptoUtils.public_key_to_address(
                self._public_key.to_pem().decode('utf-8')
            )
        return self._address

    @property
    def evm_address(self) -> str:
        """
        Endereço EVM (0x...) derivado da mesma chave pública.
        Compatível com MetaMask e carteiras Ethereum.
        """
        if not hasattr(self, '_evm_address'):
            pub_pem = self._public_key.to_pem().decode('utf-8')
            self._evm_address = CryptoUtils.public_key_to_evm_address(
                pub_pem.encode('utf-8')
            )
        return self._evm_address

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

        ATENÇÃO: A chave privada NUNCA deve ser transmitida pela rede!
        Use este método APENAS para backup local criptografado.
        """
        return {
            'address': self.address,
            'public_key': self.public_key_pem,
            'private_key': self.private_key_pem  # Mantenha seguro! APENAS uso local.
        }

    def export_public(self) -> dict:
        """
        Exporta APENAS dados públicos da carteira.
        SEGURO para transmitir pela rede.
        A chave privada NUNCA está incluída.

        Returns:
            Dict com address e public_key (sem private_key)
        """
        return {
            'address': self.address,
            'public_key': self.public_key_pem,
            'warning': 'A chave privada NUNCA é incluída nesta exportação.'
        }

    @staticmethod
    def get_public_key_from_private(private_key_pem: str) -> str:
        """
        Deriva a chave pública PEM de uma chave privada ECDSA SECP256k1.
        Usado para incluir a chave pública do nó no header P2P
        sem precisar armazená-la separadamente.

        Args:
            private_key_pem: Chave privada em formato PEM

        Returns:
            Chave pública em formato PEM
        """
        from ecdsa import SigningKey, SECP256k1
        sk = SigningKey.from_pem(private_key_pem)
        return sk.verifying_key.to_pem().decode('utf-8')

    @classmethod
    def from_dict(cls, data: dict) -> 'Wallet':
        """Reconstrói uma carteira a partir de dados salvos."""
        return cls(private_key_pem=data['private_key'])

    # ─── Criptografia de Wallet (AES-256-GCM) ─────────────────────
    # A carteira em repouso é protegida com:
    # - PBKDF2-HMAC-SHA256 (100k iterações) para derivação de chave
    # - AES-256-GCM para criptografia autenticada
    # - Salt de 32 bytes (previne ataques rainbow table)
    # - Nonce de 12 bytes (96 bits, único por operação)
    # - Tag de autenticação de 128 bits (detecta adulteração)

    def encrypt_to_file(self, password: str, filepath: str):
        """
        Criptografa a carteira com AES-256-GCM e salva em arquivo.

        Formato do arquivo:
        [salt: 32 bytes][nonce: 12 bytes][ciphertext + tag GCM: variável]

        A tag de autenticação GCM (16 bytes) é anexada ao ciphertext
        automaticamente pelo AESGCM.

        Args:
            password: Senha para criptografia (NUNCA armazenada)
            filepath: Caminho do arquivo para salvar

        Raises:
            Exception: Se a criptografia falhar
        """
        import json, os
        from config import WALLET_ENCRYPTION_ITERATIONS, WALLET_ENCRYPTION_SALT_BYTES

        wallet_data = self.to_dict()

        # Gera salt único para derivação de chave
        salt = CryptoUtils.generate_salt(WALLET_ENCRYPTION_SALT_BYTES)

        # Deriva chave AES-256 via PBKDF2 (100k iterações)
        key = CryptoUtils.derive_key(
            password, salt,
            iterations=WALLET_ENCRYPTION_ITERATIONS,
            key_length=32  # AES-256
        )

        # Criptografa com AES-256-GCM
        plaintext = json.dumps(wallet_data, indent=2).encode('utf-8')
        nonce, ciphertext = CryptoUtils.aes256gcm_encrypt(key, plaintext)

        # Formato: salt (32) + nonce (12) + ciphertext (+ tag GCM interna)
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(salt + nonce + ciphertext)

        print(f"[LOCK] Wallet criptografada salva em {filepath}")
        print(f"   Algoritmo: AES-256-GCM + PBKDF2({WALLET_ENCRYPTION_ITERATIONS} iterações)")
        print(f"   Salt: {salt.hex()[:16]}...")

    @classmethod
    def load_from_encrypted(cls, password: str, filepath: str) -> 'Wallet':
        """
        Carrega e descriptografa uma wallet de arquivo criptografado.

        O arquivo deve estar no formato gerado por encrypt_to_file():
        [salt: 32 bytes][nonce: 12 bytes][ciphertext + tag GCM]

        Se a senha estiver incorreta ou o arquivo estiver adulterado,
        AES-256-GCM detecta a violação (InvalidTag) e levanta exceção.

        Args:
            password: Senha para descriptografia
            filepath: Caminho do arquivo criptografado

        Returns:
            Instância de Wallet recuperada

        Raises:
            ValueError: Se a senha estiver incorreta ou arquivo corrompido
            FileNotFoundError: Se o arquivo não existe
        """
        import json
        from config import WALLET_ENCRYPTION_ITERATIONS

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        with open(filepath, 'rb') as f:
            data = f.read()

        # Parse: salt (32) + nonce (12) + ciphertext
        salt = data[:32]
        nonce = data[32:44]
        ciphertext = data[44:]

        # Deriva a mesma chave via PBKDF2
        key = CryptoUtils.derive_key(
            password, salt,
            iterations=WALLET_ENCRYPTION_ITERATIONS,
            key_length=32
        )

        try:
            # Descriptografa e verifica tag GCM
            plaintext = CryptoUtils.aes256gcm_decrypt(key, nonce, ciphertext)
            wallet_dict = json.loads(plaintext.decode('utf-8'))
            wallet = cls.from_dict(wallet_dict)
            print(f"[UNLOCK] Wallet descriptografada de {filepath}")
            print(f"   Endereço: {wallet.address[:20]}...")
            return wallet
        except Exception as e:
            # AES-GCM levanta InvalidTag se senha incorreta ou dados adulterados
            raise ValueError(
                "Falha ao descriptografar wallet. "
                "Senha incorreta ou arquivo corrompido."
            ) from e

    def __str__(self) -> str:
        return f"Wallet(address={self.address[:16]}...)"
