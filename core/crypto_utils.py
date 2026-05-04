"""
Módulo de utilidades criptográficas.
Fornece funções de hash, assinatura digital e verificação.
Usa SHA-256 para hashing e ECDSA (Curva Elíptica) para assinaturas.
"""
import hashlib
import json
import warnings
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_der, sigdecode_der
import base58


class CryptoUtils:
    """
    Utilitários criptográficos da blockchain.
    Encapsula todas as operações de segurança: hash, assinatura, chaves.
    """

    @staticmethod
    def sha256(data: str) -> str:
        """
        Calcula o hash SHA-256 de uma string.
        SHA-256 é o algoritmo padrão do Bitcoin para proof-of-work e
        encadeamento de blocos.

        Args:
            data: String a ser hasheada

        Returns:
            Hash hexadigital de 64 caracteres
        """
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    @staticmethod
    def _ripemd160(data: bytes) -> bytes:
        """
        Calcula o hash RIPEMD-160, com fallback para implementação
        alternativa caso o OpenSSL do sistema não inclua suporte.

        No Windows, alguns builds do Python não têm ripemd160
        disponível no hashlib via OpenSSL.

        Args:
            data: Bytes a serem hasheados

        Returns:
            Hash RIPEMD-160 (20 bytes)
        """
        try:
            return hashlib.new('ripemd160', data).digest()
        except ValueError:
            # Fallback: implementação Python pura do RIPEMD-160
            # Apenas para compatibilidade - não é otimizada
            warnings.warn("RIPEMD-160 não disponível via OpenSSL, "
                          "usando fallback Python puro")
            return CryptoUtils._ripemd160_pure(data)

    @staticmethod
    def _ripemd160_pure(data: bytes) -> bytes:
        """
        Implementação Python pura do RIPEMD-160.
        Usada como fallback quando o OpenSSL não oferece suporte.

        Args:
            data: Bytes a serem hasheados

        Returns:
            Hash RIPEMD-160 (20 bytes)
        """
        # Constantes do RIPEMD-160
        K1 = 0x00000000
        K2 = 0x5A827999
        K3 = 0x6ED9EBA1
        K4 = 0x8F1BBCDC
        K5 = 0xA953FD4E
        K6 = 0x50A28BE6
        K7 = 0x5C4DD124
        K8 = 0x6D703EF3
        K9 = 0x7A6D76E9
        K10 = 0x00000000

        # Padding (igual ao SHA-1)
        ml = len(data) * 8
        data = bytearray(data)
        data.append(0x80)
        while (len(data) * 8) % 512 != 448:
            data.append(0x00)
        data += ml.to_bytes(8, 'little')

        # Inicialização
        h0 = 0x67452301
        h1 = 0xEFCDAB89
        h2 = 0x98BADCFE
        h3 = 0x10325476
        h4 = 0xC3D2E1F0

        def _lshift(x: int, n: int) -> int:
            return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

        def _f(j, x, y, z):
            if j < 16:
                return x ^ y ^ z
            elif j < 32:
                return (x & y) | (~x & z)
            elif j < 48:
                return (x | ~y) ^ z
            elif j < 64:
                return (x & z) | (y & ~z)
            else:
                return x ^ (y | ~z)

        # Processa cada bloco de 512 bits
        words = [0] * 16
        for i in range(0, len(data), 64):
            block = data[i:i+64]
            for j in range(16):
                words[j] = int.from_bytes(block[j*4:(j+1)*4], 'little')

            # Expande para 80 palavras
            w = words[:]
            for j in range(16, 80):
                w.append(_lshift(w[j-3] ^ w[j-8] ^ w[j-14] ^ w[j-16], 1))

            a1, b1, c1, d1, e1 = h0, h1, h2, h3, h4
            a2, b2, c2, d2, e2 = h0, h1, h2, h3, h4

            for j in range(80):
                # Linha paralela 1
                T1 = (a1 + _f(j, b1, c1, d1) + w[j] +
                      [K1, K2, K3, K4, K5][j // 16]) & 0xFFFFFFFF
                a1, b1, c1, d1, e1 = (
                    (e1 + _lshift(T1, 10)) & 0xFFFFFFFF, a1,
                    (_lshift(b1, 10)) & 0xFFFFFFFF, c1, d1
                )
                # Linha paralela 2
                T2 = (a2 + _f(79 - j, b2, c2, d2) + w[j] +
                      [K6, K7, K8, K9, K10][j // 16]) & 0xFFFFFFFF
                a2, b2, c2, d2, e2 = (
                    (e2 + _lshift(T2, 10)) & 0xFFFFFFFF, a2,
                    (_lshift(b2, 10)) & 0xFFFFFFFF, c2, d2
                )

            T = (h1 + c1 + d2) & 0xFFFFFFFF
            h1 = (h2 + d1 + e2) & 0xFFFFFFFF
            h2 = (h3 + e1 + a2) & 0xFFFFFFFF
            h3 = (h4 + a1 + b2) & 0xFFFFFFFF
            h4 = (h0 + b1 + c2) & 0xFFFFFFFF
            h0 = T

        # Concatena no formato little-endian
        result = b''
        for h in [h0, h1, h2, h3, h4]:
            result += h.to_bytes(4, 'little')
        return result

    @staticmethod
    def hash_block(block_dict: dict) -> str:
        """
        Calcula o hash de um bloco a partir de sua representação em dicionário.
        O hash é calculado sobre todos os campos IMPORTANTEs do bloco:
        index, timestamp, transações, proof (nonce) e previous_hash.
        Isso garante que qualquer alteração no bloco invalide seu hash.

        Args:
            block_dict: Dicionário com os dados do bloco

        Returns:
            Hash SHA-256 do bloco
        """
        block_string = json.dumps(block_dict, sort_keys=True).encode('utf-8')
        return hashlib.sha256(block_string).hexdigest()

    @staticmethod
    def generate_key_pair() -> tuple:
        """
        Gera um par de chaves (privada/pública) usando ECDSA com curva SECP256k1.
        A mesma curva usada pelo Bitcoin (secp256k1).

        Returns:
            Tupla (chave_privada, chave_publica) em formato PEM/bytes
        """
        # SECP256k1 é a curva elíptica padronizada usada pelo Bitcoin
        private_key = SigningKey.generate(curve=SECP256k1)
        public_key = private_key.verifying_key
        return private_key, public_key

    @staticmethod
    def sign_data(private_key: SigningKey, data: str) -> bytes:
        """
        Assina digitalmente uma string com a chave privada.
        Usa ECDSA com codificação DER.

        Args:
            private_key: Chave privada ECDSA
            data: String a ser assinada

        Returns:
            Assinatura em formato DER (bytes)
        """
        return private_key.sign(
            data.encode('utf-8'),
            hashfunc=hashlib.sha256,
            sigencode=sigencode_der
        )

    @staticmethod
    def verify_signature(public_key_pem: str, data: str, signature: bytes) -> bool:
        """
        Verifica uma assinatura digital usando a chave pública.
        Confirma que os dados foram realmente assinados pelo dono da chave privada.

        Args:
            public_key_pem: Chave pública em formato PEM (string)
            data: String original que foi assinada
            signature: Assinatura em bytes (DER)

        Returns:
            True se a assinatura é válida, False caso contrário
        """
        try:
            vk = VerifyingKey.from_pem(public_key_pem.encode('utf-8'))
            return vk.verify(
                signature,
                data.encode('utf-8'),
                hashfunc=hashlib.sha256,
                sigdecode=sigdecode_der
            )
        except Exception:
            return False

    @staticmethod
    def public_key_to_address(public_key_pem: str) -> str:
        """
        Converte uma chave pública em um endereço estilo Bitcoin.
        Processo:
        1. Hash SHA-256 da chave pública
        2. Hash RIPEMD-160 do resultado (HASH160)
        3. Checksum duplo SHA-256
        4. Codificação Base58 para obter um endereço legível

        Este é o mesmo processo usado pelo Bitcoin para gerar endereços,
        usando a curva secp256k1 para as chaves e Base58Check para o
        formato final do endereço.

        Args:
            public_key_pem: Chave pública em formato PEM

        Returns:
            Endereço da carteira em Base58
        """
        # SHA-256 da chave pública
        sha256_hash = hashlib.sha256(public_key_pem.encode('utf-8')).digest()

        # RIPEMD-160 do resultado
        # No Bitcoin: ripemd160(sha256(pubkey))
        ripe_hash = CryptoUtils._ripemd160(sha256_hash)

        # Versão (0x00 para mainnet) + hash
        version_hash = b'\x00' + ripe_hash

        # Checksum: primeiros 4 bytes do SHA-256(SHA-256(version+hash))
        checksum = hashlib.sha256(hashlib.sha256(version_hash).digest()).digest()[:4]

        # Endereço binário: version + hash + checksum
        binary_address = version_hash + checksum

        # Codificação Base58
        return base58.b58encode(binary_address).decode('utf-8')

    @staticmethod
    def is_valid_address(address: str) -> bool:
        """
        Valida um endereço Base58 com checksum.

        Verifica:
        1. O endereço é uma string não vazia
        2. Tem a codificação Base58 válida
        3. O checksum (4 bytes) é consistente

        Args:
            address: Endereço a validar

        Returns:
            True se o endereço é estruturalmente válido
        """
        if not address or not isinstance(address, str):
            return False

        try:
            decoded = base58.b58decode(address)
        except (ValueError, TypeError):
            return False

        if len(decoded) < 5:  # Mínimo: 1 byte versão + 4 bytes checksum
            return False

        # Separa payload (version + hash) e checksum
        payload = decoded[:-4]
        checksum = decoded[-4:]

        # Verifica checksum: SHA-256(SHA-256(payload))[:4]
        calculated = hashlib.sha256(
            hashlib.sha256(payload).digest()
        ).digest()[:4]

        return checksum == calculated

    @staticmethod
    def merkle_root(transactions: list) -> str:
        """
        Calcula a raiz de Merkle de uma lista de transações.
        A raiz de Merkle é uma árvore binária de hashes que resume
        todas as transações em um bloco. Permite verificar se uma
        transação pertence a um bloco sem precisar do bloco inteiro.

        Args:
            transactions: Lista de dicionários de transações

        Returns:
            Hash da raiz de Merkle (string hex de 64 caracteres)
        """
        if not transactions:
            return '0' * 64

        # Converte cada transação em seu hash
        tree = []
        for tx in transactions:
            tx_str = json.dumps(tx, sort_keys=True)
            tree.append(CryptoUtils.sha256(tx_str))

        # Constrói a árvore binária
        # Em cada nível, pares de hashes são concatenados e hasheados novamente
        while len(tree) > 1:
            # Se ímpar, duplica o último
            if len(tree) % 2 != 0:
                tree.append(tree[-1])

            # Próximo nível da árvore
            next_level = []
            for i in range(0, len(tree), 2):
                combined = tree[i] + tree[i + 1]
                next_level.append(CryptoUtils.sha256(combined))

            tree = next_level

        return tree[0]

    @staticmethod
    def is_hash_valid(hash_value: str, difficulty: int) -> bool:
        """
        Verifica se um hash atende ao requisito de dificuldade (proof of work).
        Um hash é válido se começa com 'difficulty' zeros.

        No Bitcoin, a dificuldade aumenta para que novos blocos sejam
        minerados aproximadamente a cada 10 minutos.

        Args:
            hash_value: Hash a verificar (string hex)
            difficulty: Número de zeros necessários no início

        Returns:
            True se o hash é válido para a dificuldade atual
        """
        target = '0' * difficulty
        return hash_value.startswith(target)

    @staticmethod
    def generate_node_id() -> str:
        """Gera um ID único para identificar nós na rede."""
        import uuid
        return str(uuid.uuid4())
