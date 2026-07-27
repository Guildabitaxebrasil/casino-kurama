"""
Módulo de Identidade de Nó (NodeIdentity).

Gerencia a identidade criptográfica persistente de um nó na rede.
Cada nó tem um par de chaves ECDSA SECP256k1 que:
- Identifica o nó unicamente na rede (node_id derivado da chave pública)
- Assina todas as mensagens P2P (não-repúdio)
- Persiste entre reinicializações (arquivo criptografado AES-256-GCM)

Segurança:
- Chave gerada com os.urandom via ecdsa library (curva SECP256k1)
- Persistência opcionalmente criptografada com AES-256-GCM + Argon2/PBKDF2
- node_id = SHA-256(public_key)[:16] (determinístico, imutável)
"""
import json
import os
import hashlib


class NodeIdentity:
    """
    Identidade criptográfica persistente de um nó na rede KuramaChain.

    Fornece:
    - Geração de par de chaves ECDSA SECP256k1
    - Persistência em disco (JSON ou criptografado)
    - Assinatura de mensagens P2P
    - node_id determinístico (derivado da chave pública)

    Uso:
        identity = NodeIdentity()
        identity.generate()           # Gera novo par de chaves
        identity.save_to_file(path)   # Persiste em disco
        identity.load_from_file(path) # Carrega do disco
        signature = identity.sign(message_dict)  # Assina mensagem
    """

    def __init__(self):
        self._signing_key = None
        self._verifying_key = None
        self._node_id = None
        self._address = None
        self._public_key_pem = None
        self._private_key_pem = None

    @property
    def node_id(self) -> str:
        """ID do nó: SHA-256(public_key)[:16] — determinístico."""
        return self._node_id

    @property
    def public_key_pem(self) -> str:
        return self._public_key_pem

    @property
    def private_key_pem(self) -> str:
        return self._private_key_pem

    @property
    def address(self) -> str:
        """Endereço estilo Bitcoin (Base58Check) derivado da chave pública."""
        return self._address

    def generate(self):
        """
        Gera um novo par de chaves ECDSA SECP256k1.
        O node_id é derivado deterministicamente da chave pública.
        """
        from ecdsa import SigningKey, SECP256k1
        from .crypto_utils import CryptoUtils

        self._signing_key = SigningKey.generate(curve=SECP256k1)
        self._verifying_key = self._signing_key.get_verifying_key()
        self._private_key_pem = self._signing_key.to_pem().decode('utf-8')
        self._public_key_pem = self._verifying_key.to_pem().decode('utf-8')

        # node_id = SHA-256(public_key)[:16] — determinístico e imutável
        pub_key_bytes = self._verifying_key.to_string()
        self._node_id = hashlib.sha256(pub_key_bytes).hexdigest()[:16]

        # Endereço estilo Bitcoin
        self._address = CryptoUtils.public_key_to_address(self._public_key_pem)

    def to_dict(self) -> dict:
        """Serializa identidade para dicionário."""
        return {
            'node_id': self._node_id,
            'private_key': self._private_key_pem,
            'public_key': self._public_key_pem,
            'address': self._address
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'NodeIdentity':
        """Reconstrói identidade a partir de dicionário."""
        identity = cls()
        from ecdsa import SigningKey, SECP256k1
        from .crypto_utils import CryptoUtils

        identity._private_key_pem = data['private_key']
        identity._signing_key = SigningKey.from_pem(
            data['private_key'].encode('utf-8')
        )
        identity._verifying_key = identity._signing_key.get_verifying_key()
        identity._public_key_pem = data.get(
            'public_key',
            identity._verifying_key.to_pem().decode('utf-8')
        )

        pub_key_bytes = identity._verifying_key.to_string()
        identity._node_id = data.get(
            'node_id',
            hashlib.sha256(pub_key_bytes).hexdigest()[:16]
        )
        identity._address = data.get(
            'address',
            CryptoUtils.public_key_to_address(identity._public_key_pem)
        )
        return identity

    def get_data_for_signing(self, payload: dict) -> str:
        """
        Retorna a string canônica para assinatura.
        Inclui node_id do remetente para vinculação de identidade.

        Args:
            payload: Dicionário com os dados da mensagem

        Returns:
            String JSON canônica (sort_keys) com node_id + payload
        """
        to_sign = {
            'node_id': self._node_id,
            'payload': payload
        }
        return json.dumps(to_sign, sort_keys=True)

    def sign(self, payload: dict) -> str:
        """
        Assina uma mensagem P2P com a chave privada do nó.

        O formato inclui node_id + payload para vincular a
        assinatura à identidade do remetente (non-repudiation).

        Args:
            payload: Dicionário com dados da mensagem

        Returns:
            Assinatura Base64-encoded

        Raises:
            ValueError: Se a identidade não foi gerada/carregada
        """
        if not self._signing_key:
            raise ValueError(
                "NodeIdentity não inicializada. Chame generate() "
                "ou load_from_file() primeiro."
            )
        from .crypto_utils import CryptoUtils
        data_str = self.get_data_for_signing(payload)
        sig_bytes = CryptoUtils.sign_data(self._signing_key, data_str)
        import base64
        return base64.b64encode(sig_bytes).decode('utf-8')

    def verify(self, payload: dict, signature_b64: str,
               public_key_pem: str) -> bool:
        """
        Verifica assinatura de uma mensagem P2P.

        Args:
            payload: Dicionário com dados da mensagem
            signature_b64: Assinatura Base64
            public_key_pem: Chave pública PEM do remetente

        Returns:
            True se a assinatura é válida
        """
        from .crypto_utils import CryptoUtils
        import base64
        try:
            data_str = self.get_data_for_signing(payload)
            sig_bytes = base64.b64decode(signature_b64)
            return CryptoUtils.verify_signature(
                public_key_pem, data_str, sig_bytes
            )
        except Exception:
            return False

    def save_to_file(self, filepath: str, password: str = None):
        """
        Salva a identidade em arquivo.

        Se uma senha for fornecida, o arquivo é criptografado
        com AES-256-GCM + Argon2. Caso contrário, salva como
        JSON puro (apenas para desenvolvimento).

        Args:
            filepath: Caminho para salvar
            password: Senha para criptografia (opcional)
        """
        data = self.to_dict()
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

        if password:
            # Salva criptografado
            from .crypto_utils import CryptoUtils
            key = CryptoUtils.derive_key(
                password,
                CryptoUtils.generate_salt(32)
            )
            nonce, ciphertext = CryptoUtils.aes256gcm_encrypt(
                key,
                json.dumps(data).encode('utf-8')
            )
            salt = CryptoUtils.generate_salt(32)
            full_key = CryptoUtils.derive_key(password, salt)
            nonce2, ct2 = CryptoUtils.aes256gcm_encrypt(
                full_key,
                json.dumps(data).encode('utf-8')
            )
            with open(filepath, 'wb') as f:
                f.write(salt + nonce2 + ct2)
        else:
            # JSON puro (dev apenas)
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)

    @classmethod
    def load_from_file(cls, filepath: str,
                       password: str = None) -> 'NodeIdentity':
        """
        Carrega identidade de arquivo.

        Tenta carregar como JSON primeiro. Se falhar, tenta
        como formato criptografado.

        Args:
            filepath: Caminho do arquivo
            password: Senha (se criptografado)

        Returns:
            Instância de NodeIdentity

        Raises:
            FileNotFoundError: Se o arquivo não existe
            ValueError: Se a senha está incorreta ou dados corrompidos
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Arquivo de identidade não encontrado: {filepath}"
            )

        if password:
            # Tenta carregar criptografado
            from .crypto_utils import CryptoUtils
            with open(filepath, 'rb') as f:
                raw = f.read()
            salt = raw[:32]
            nonce = raw[32:44]
            ct = raw[44:]
            key = CryptoUtils.derive_key(password, salt)
            plaintext = CryptoUtils.aes256gcm_decrypt(key, nonce, ct)
            data = json.loads(plaintext.decode('utf-8'))
        else:
            # Tenta JSON
            with open(filepath, 'r') as f:
                data = json.load(f)

        return cls.from_dict(data)

    def __str__(self) -> str:
        return f"NodeIdentity(node_id={self._node_id}, addr={self._address[:16]}...)"


# ─── Função utilitária para criar/carregar identidade ─────────────

def get_or_create_identity(identity_file: str = None,
                           password: str = None) -> NodeIdentity:
    """
    Carrega identidade existente ou cria uma nova.

    Se o arquivo de identidade existe, carrega. Caso contrário,
    gera uma nova identidade e salva.

    Args:
        identity_file: Caminho do arquivo de identidade
        password: Senha para criptografia

    Returns:
        Instância de NodeIdentity
    """
    identity = NodeIdentity()
    if identity_file and os.path.exists(identity_file):
        try:
            identity = NodeIdentity.load_from_file(identity_file, password)
            print(f"[ID] Identidade carregada: {identity.node_id}")
            return identity
        except Exception as e:
            print(f"[WARN] Erro ao carregar identidade: {e}. Gerando nova.")

    identity.generate()
    if identity_file:
        try:
            identity.save_to_file(identity_file, password)
            print(f"[ID] Nova identidade gerada: {identity.node_id}")
            print(f"   Salva em: {identity_file}")
        except Exception as e:
            print(f"[WARN] Erro ao salvar identidade: {e}")
    else:
        print(f"[ID] Nova identidade gerada: {identity.node_id}")

    return identity
