"""
Módulo de utilidades criptográficas.
Fornece funções de hash, assinatura digital e verificação.
Usa SHA-256 para hashing e ECDSA (Curva Elíptica) para assinaturas.
"""
import hashlib
import json
import os
import base64
import traceback
import warnings
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_der, sigdecode_der
import base58

# ─── Keccak-256 (Ethereum compatível) ──────────────────────────
# O Ethereum usa o algoritmo Keccak ORIGINAL (SHA-3 proposal de 2007)
# que difere do NIST SHA-3 finalizado em 2015 no padding.
# Python's hashlib.sha3_256 e shake_256 usam padding NIST (0x06/0x1F),
# então NÃO produzem hashes compatíveis com Ethereum.
# 
# Dependências corretas (em ordem de preferência):
#   1. pycryptodome (Cryptodome.Hash.keccak)
#   2. pysha3 (sha3.keccak_256)
def _keccak256_impl(data: bytes) -> bytes:
    """
    Implementação keccak-256 compatível com Ethereum.
    
    ATENÇÃO: hashlib.sha3_256 e shake_256 NÃO são compatíveis
    com Ethereum! Eles usam padding NIST (diferente do Keccak original).
    
    Args:
        data: Bytes a serem hasheados
    Returns:
        32 bytes do hash keccak-256
    Raises:
        ImportError: Se nenhuma implementação de keccak estiver disponível
    """
    # Tenta pycryptodome (namespace Crypto)
    try:
        from Crypto.Hash import keccak as _ck
        k = _ck.new(data=data, digest_bits=256)
        return k.digest()
    except ImportError:
        pass
    # Tenta pycryptodome (namespace Cryptodome - versão antiga)
    try:
        from Cryptodome.Hash import keccak as _ck
        k = _ck.new(data=data, digest_bits=256)
        return k.digest()
    except ImportError:
        pass
    # Tenta pysha3
    try:
        import sha3 as _s3
        return _s3.keccak_256(data).digest()
    except ImportError:
        pass
    raise ImportError(
        "keccak-256 não disponível. Instale: pip install pycryptodome"
    )

RE_ETH_ADDRESS = None
try:
    import re
    RE_ETH_ADDRESS = re.compile(r'^0x[a-fA-F0-9]{40}$')
except ImportError:
    pass


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
    def generate_nonce() -> str:
        """
        Gera um nonce criptograficamente seguro usando os.urandom().
        Usado para garantir unicidade de transações e prevenir
        ataques de replay e colisão de IDs.

        Returns:
            String hex com entropia criptográfica
        """
        from config import TX_NONCE_BYTES
        return os.urandom(TX_NONCE_BYTES).hex()

    @staticmethod
    def generate_p2p_nonce() -> str:
        """
        Gera um nonce P2P de 96 bits (12 bytes) para anti-replay.

        96 bits é o tamanho ideal para nonces P2P:
        - Suficiente para 2^96 mensagens únicas
        - Tamanho compacto em headers HTTP (24 chars hex)
        - Alinhado com AES-GCM (nonce de 96 bits é o recomendado NIST)

        Returns:
            Hex string de 24 caracteres
        """
        return os.urandom(12).hex()

    @staticmethod
    def generate_node_id() -> str:
        """
        Gera um ID único para identificar um nó na rede P2P.

        Usa 8 bytes de entropia criptográfica somados ao timestamp
        para garantir unicidade mesmo entre nós criados no mesmo
        milissegundo.

        Returns:
            String hex de 24 caracteres (96 bits)
        """
        import time as _time
        raw = str(_time.time()).encode() + os.urandom(8)
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def hash_equals(a: str, b: str) -> bool:
        """
        Compara duas strings hash em TEMPO CONSTANTE.
        Previne timing attacks onde um atacante mede o tempo de
        resposta para adivinhar caracteres do hash.

        Args:
            a: Primeira string
            b: Segunda string

        Returns:
            True se as strings são iguais
        """
        if len(a) != len(b):
            return False
        result = 0
        for ca, cb in zip(a.encode('utf-8'), b.encode('utf-8')):
            result |= ca ^ cb
        return result == 0

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
        except (ValueError, TypeError) as e:
            # Chave pública inválida ou formato incorreto
            warnings.warn(f"[WARN] verify_signature: chave pública inválida: {e}", RuntimeWarning, stacklevel=2)
            return False
        except Exception as e:
            # Erro inesperado na verificação
            print(f"[ERR] verify_signature: erro inesperado: {e}")
            traceback.print_exc()
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
        Valida um endereço (Base58 Kurama OU EVM 0x...).
        Aceita ambos os formatos para compatibilidade com MetaMask.

        Base58 (Kurama nativo):
        1. String não vazia
        2. Codificação Base58 válida
        3. Checksum (4 bytes) consistente

        EVM (Ethereum):
        1. String começando com 0x
        2. 40 caracteres hex após o 0x
        3. Total: 42 caracteres

        Args:
            address: Endereço a validar

        Returns:
            True se o endereço é estruturalmente válido
        """
        if not address or not isinstance(address, str):
            return False

        # Tenta EVM primeiro (0x...)
        if address.startswith('0x') or address.startswith('0X'):
            return CryptoUtils.is_valid_evm_address(address)

        # Fallback: Base58 (Kurama nativo)
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

        As transações são ordenadas por transaction_id (ordem canônica)
        para garantir que a mesma lista sempre produza a mesma Merkle root,
        independentemente da ordem de chegada.

        Args:
            transactions: Lista de dicionários de transações

        Returns:
            Hash da raiz de Merkle (string hex de 64 caracteres)
        """
        if not transactions:
            return '0' * 64

        # ─── Ordenação Canônica ──────────────────────────────────
        # Ordena por transaction_id para garantir Merkle root
        # determinística independente da ordem das transações.
        sorted_txs = sorted(
            transactions,
            key=lambda tx: tx.get('transaction_id', '')
        )

        # Converte cada transação em seu hash
        tree = []
        for tx in sorted_txs:
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

        Usa CryptoUtils.hash_equals() (TEMPO CONSTANTE) para prevenir
        timing attacks que poderiam vazar informação sobre o hash.

        No Bitcoin, a dificuldade aumenta para que novos blocos sejam
        minerados aproximadamente a cada 10 minutos.

        Args:
            hash_value: Hash a verificar (string hex)
            difficulty: Número de zeros necessários no início

        Returns:
            True se o hash é válido para a dificuldade atual
        """
        target = '0' * difficulty
        if len(hash_value) < difficulty:
            return False
        # Comparação em TEMPO CONSTANTE — previne timing attack
        return CryptoUtils.hash_equals(hash_value[:difficulty], target)

    @staticmethod
    def keccak256(data: bytes) -> str:
        """
        Calcula o hash keccak-256 (Ethereum compatível).
        Usa a implementação original do Keccak (SHA-3 de 2007),
        que difere do NIST SHA-3 final.

        Args:
            data: Bytes a serem hasheados

        Returns:
            Hash hex de 64 caracteres
        """
        return _keccak256_impl(data).hex()

    @staticmethod
    def is_valid_evm_address(address: str) -> bool:
        """
        Valida um endereço EVM (Ethereum).
        Formato: 0x + 40 caracteres hex (20 bytes).

        Args:
            address: Endereço a validar

        Returns:
            True se é um endereço EVM estruturalmente válido
        """
        if not address or not isinstance(address, str):
            return False
        if RE_ETH_ADDRESS is not None:
            return bool(RE_ETH_ADDRESS.match(address))
        # Fallback manual se regex não estiver disponível
        if not address.startswith('0x') or len(address) != 42:
            return False
        try:
            int(address[2:], 16)
            return True
        except ValueError:
            return False

    @staticmethod
    def public_key_to_evm_address(public_key_bytes: bytes) -> str:
        """
        Deriva um endereço EVM (0x...) de uma chave pública.

        Processo Ethereum:
        1. Pega os bytes da chave pública (não comprimida, sem prefixo 04)
        2. Aplica keccak-256
        3. Pega os últimos 20 bytes
        4. Prefixa com 0x

        Args:
            public_key_bytes: Chave pública em bytes (PEM ou raw SECP256k1)

        Returns:
            Endereço EVM (ex: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18)
        """
        # Se for PEM, extrai a chave pública raw
        pem_str = public_key_bytes.decode('utf-8') if isinstance(public_key_bytes, bytes) else str(public_key_bytes)
        if 'BEGIN PUBLIC KEY' in pem_str:
            vk = VerifyingKey.from_pem(pem_str)
            # Ponto da curva em formato não-comprimido (64 bytes: x + y)
            point_bytes = vk.to_string()
            keccak = _keccak256_impl(point_bytes)
            return ('0x' + keccak[-20:].hex()).lower()

        # Se já for bytes raw (64 bytes, x + y)
        keccak = _keccak256_impl(public_key_bytes[:64] if len(public_key_bytes) >= 64 else public_key_bytes)
        return ('0x' + keccak[-20:].hex()).lower()

    # ─── ECDSA Recovery (MetaMask personal_sign) ──────────────────
    # Recupera o endereço Ethereum de uma assinatura personal_sign do MetaMask.
    # O MetaMask prefixa a mensagem com "\x19Ethereum Signed Message:\n{len}"
    # antes de hashear com keccak-256 e assinar com ECDSA (r, s, v).
    # O v (recovery ID) determina qual das 2 possíveis chaves públicas é a correta.

    @staticmethod
    def recover_address_from_personal_sign(message: str, signature_hex: str) -> str:
        """
        Recupera o endereço Ethereum de uma assinatura personal_sign do MetaMask.

        O MetaMask:
        1. Prefixa a mensagem: "\\x19Ethereum Signed Message:\\n{len(msg)}{msg}"
        2. Hasheia com keccak-256
        3. Assina com ECDSA recoverable (r || s || v)

        Args:
            message: Mensagem original (sem prefixo)
            signature_hex: Assinatura hex (0x...) do MetaMask (132 chars + 0x)

        Returns:
            Endereço Ethereum recuperado (0x...)

        Raises:
            ValueError: Se a assinatura for inválida ou não for possível recuperar
        """
        # Remove 0x prefix
        sig = signature_hex[2:] if signature_hex.startswith('0x') else signature_hex
        sig_bytes = bytes.fromhex(sig)

        if len(sig_bytes) != 65:
            raise ValueError(
                f"Comprimento de assinatura inválido: {len(sig_bytes)} (esperado 65)"
            )

        # Extrai r (32B), s (32B), v (1B)
        # v = 27 ou 28 para personal_sign
        r = sig_bytes[:32]
        s = sig_bytes[32:64]
        v = sig_bytes[64]

        # recovery_id = (v - 27) % 2
        # Se v=27 → rid=0, se v=28 → rid=1
        rid = (v - 27) % 2

        # Aplica prefixo Ethereum Signed Message
        prefixed = (
            b"\x19Ethereum Signed Message:\n" +
            str(len(message)).encode() +
            message.encode()
        )

        # Hash com keccak-256
        msg_hash = _keccak256_impl(prefixed)

        # Recupera TODAS as possíveis chaves públicas
        from ecdsa.util import sigdecode_string
        all_keys = VerifyingKey.from_public_key_recovery_with_digest(
            r + s, msg_hash, SECP256k1, hashlib.sha256, sigdecode_string
        )

        if not all_keys or rid >= len(all_keys):
            raise ValueError("Não foi possível recuperar chave pública da assinatura")

        # Pega a chave correta baseada no recovery_id
        vk = all_keys[rid]
        point_bytes = vk.to_string()
        keccak = _keccak256_impl(point_bytes)
        return ('0x' + keccak[-20:].hex()).lower()

    @staticmethod
    def verify_personal_sign(address: str, message: str, signature_hex: str) -> bool:
        """
        Verifica se a assinatura personal_sign foi feita pelo dono do endereço.

        Args:
            address: Endereço Ethereum (0x...) que supostamente assinou
            message: Mensagem original (sem prefixo)
            signature_hex: Assinatura hex do MetaMask

        Returns:
            True se a assinatura corresponde ao endereço
        """
        try:
            recovered = CryptoUtils.recover_address_from_personal_sign(
                message, signature_hex
            )
            return recovered.lower() == address.lower()
        except Exception:
            return False

    # ─── HMAC-SHA256 (Autenticação P2P) ──────────────────────────

    @staticmethod
    def hmac_sha256(secret: str, data: bytes) -> str:
        """
        Calcula HMAC-SHA256 de dados com uma chave secreta.

        HMAC (Hash-based Message Authentication Code) garante:
        - Integridade: os dados não foram alterados
        - Autenticidade: quem gerou o MAC conhece o secret
        - Não-repúdio via prova de conhecimento do secret

        Usa hmac.compare_digest() para verificação em TEMPO CONSTANTE.

        Args:
            secret: Chave secreta compartilhada
            data: Bytes a autenticar

        Returns:
            HMAC-SHA256 hex digest (64 caracteres)
        """
        import hmac
        return hmac.new(
            secret.encode('utf-8'),
            data,
            'sha256'
        ).hexdigest()

    @staticmethod
    def hmac_verify(secret: str, data: bytes, expected_mac: str) -> bool:
        """
        Verifica um HMAC-SHA256 em TEMPO CONSTANTE.
        Usa hmac.compare_digest() para prevenir timing attacks.

        Args:
            secret: Chave secreta compartilhada
            data: Dados originais
            expected_mac: MAC esperado (hex)

        Returns:
            True se o MAC é válido
        """
        import hmac
        computed = CryptoUtils.hmac_sha256(secret, data)
        return hmac.compare_digest(computed, expected_mac)

    # ─── AES-256-GCM (Criptografia Autenticada) ─────────────────

    @staticmethod
    def generate_salt(length: int = 32) -> bytes:
        """
        Gera um salt criptograficamente seguro.
        Usado em PBKDF2/Argon2 para derivação de chave.

        Args:
            length: Número de bytes do salt

        Returns:
            Salt aleatório
        """
        return os.urandom(length)

    @staticmethod
    def derive_key_argon2(password: str, salt: bytes,
                          time_cost: int = 3,
                          memory_cost: int = 65536,
                          parallelism: int = 4,
                          key_length: int = 32) -> bytes:
        """
        Deriva uma chave AES-256 usando Argon2id.

        Argon2id é o vencedor do PHC (Password Hashing Competition)
        e é resistente a:
        - GPU attacks: memory-hard (64 MB por operação)
        - ASIC attacks: time-cost 3 + memory 64 MB
        - Side-channel: data-independent memory access
        - Tradeoff attacks: parâmetros balanceados

        Parâmetros seguem recomendações OWASP 2024:
        - Time cost: 3 (mínimo recomendado)
        - Memory: 64 MB (65536 KB)
        - Parallelism: 4 (cores)
        - Output: 32 bytes (AES-256)

        Fallback: Se o pacote argon2-cffi não estiver instalado,
        usa PBKDF2-HMAC-SHA256 (100k iterações).

        Args:
            password: Senha do usuário
            salt: Salt criptográfico (32 bytes)
            time_cost: Custo de tempo (iterações do Argon2)
            memory_cost: Custo de memória em KB
            parallelism: Paralelismo (threads)
            key_length: Tamanho da chave em bytes (32 = AES-256)

        Returns:
            Chave derivada (key_length bytes)
        """
        try:
            from argon2.low_level import hash_secret_raw, Type
            raw = hash_secret_raw(
            secret=password.encode('utf-8'),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=key_length,
            type=Type.ID  # Argon2id = ID
            )
            return raw
        except ImportError:
            import warnings
            warnings.warn(
                "[WARN] Argon2 não disponível: pacote 'argon2-cffi' não instalado. "
                "Usando PBKDF2 (100k iterações) como fallback. "
                "Instale com: pip install argon2-cffi",
                RuntimeWarning, stacklevel=2
            )
            import hashlib
            return hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt,
                100000,
                dklen=key_length
            )
        except Exception as e:
            import warnings
            warnings.warn(
                f"[WARN] Argon2 falhou ({e}). Usando PBKDF2 como fallback.",
                RuntimeWarning, stacklevel=2
            )
            import hashlib
            return hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt,
                100000,
                dklen=key_length
            )

    @staticmethod
    def derive_key(password: str, salt: bytes,
                   iterations: int = 100000,
                   key_length: int = 32) -> bytes:
        """
        Deriva uma chave AES-256 a partir de uma senha.

        TENTA ARGON2 PRIMEIRO (se o pacote argon2-cffi estiver
        instalado). Fallback para PBKDF2-HMAC-SHA256 (100k iterações).

        Argon2 é superior porque:
        - Memory-hard: requer 64 MB de RAM por operação
        - GPU/ASIC resistant: não pode ser acelerado em hardware
        - Side-channel resistant: acesso à memória independente de dados

        Args:
            password: Senha do usuário
            salt: Salt criptográfico (32 bytes)
            iterations: Número de iterações (apenas PBKDF2)
            key_length: Tamanho da chave em bytes (32 = AES-256)

        Returns:
            Chave derivada (key_length bytes)
        """
        # Tenta Argon2 primeiro (memória-hard, GPU resistant)
        # NOTA: inline do Argon2 para evitar recursão com derive_key_argon2()
        try:
            from argon2.low_level import hash_secret_raw, Type
            raw = hash_secret_raw(
                secret=password.encode('utf-8'),
                salt=salt,
                time_cost=3,
                memory_cost=65536,
                parallelism=4,
                hash_len=key_length,
                type=Type.ID
            )
            return raw
        except ImportError:
            import warnings
            warnings.warn(
                "[WARN] Argon2 não disponível. Usando PBKDF2. "
                "Instale: pip install argon2-cffi",
                RuntimeWarning, stacklevel=2
            )
        except Exception as e:
            import warnings
            warnings.warn(
                f"[WARN] Argon2 falhou ({e}). Usando PBKDF2.",
                RuntimeWarning, stacklevel=2
            )

        # Fallback: PBKDF2-HMAC-SHA256 (100k iterações)
        import hashlib
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            iterations,
            dklen=key_length
        )

    @staticmethod
    def aes256gcm_encrypt(key: bytes, plaintext: bytes,
                          aad: bytes = None) -> tuple:
        """
        Criptografa dados com AES-256-GCM (Autenticado).

        AES-256-GCM é um cifrador autenticado que fornece:
        - Confidencialidade: os dados não podem ser lidos sem a chave
        - Integridade: qualquer alteração é detectada (tag 128-bit)
        - Autenticidade: a tag prova que os dados vieram de quem tem a chave

        Requer o pacote 'cryptography'. Se não estiver instalado, retorna
        os dados em plaintext com aviso (fallback inseguro apenas para dev).

        Args:
            key: Chave AES de 256 bits (32 bytes)
            plaintext: Dados a criptografar
            aad: Additional Authenticated Data (opcional)

        Returns:
            Tupla (nonce, ciphertext) onde ciphertext já inclui a tag GCM
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(key)
            nonce = os.urandom(12)  # 96 bits — tamanho recomendado para GCM
            ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
            return nonce, ciphertext
        except ImportError:
            import warnings
            warnings.warn(
                "[WARN] AES-256-GCM não disponível: pacote 'cryptography' não instalado. "
                "Dados NÃO criptografados! Instale com: pip install cryptography",
                RuntimeWarning, stacklevel=2
            )
            # Fallback inseguro: retorna dados em plaintext + nonce dummy
            return b'\x00' * 12, plaintext

    @staticmethod
    def aes256gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes,
                          aad: bytes = None) -> bytes:
        """
        Descriptografa dados com AES-256-GCM.
        Levanta exceção se a tag de autenticação não for válida
        (dados adulterados ou chave incorreta).

        Se o pacote 'cryptography' não estiver instalado, retorna
        os dados sem descriptografar (fallback apenas para dev).

        Args:
            key: Chave AES de 256 bits (32 bytes)
            nonce: Nonce de 12 bytes usado na criptografia
            ciphertext: Dados criptografados (inclui tag GCM)
            aad: Additional Authenticated Data (mesmo usado na criptografia)

        Returns:
            Dados descriptografados

        Raises:
            ValueError: Se a autenticação falhar ou o pacote não estiver disponível
                        e o modo for produção
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(key)
            return aesgcm.decrypt(nonce, ciphertext, aad)
        except ImportError:
            import warnings
            if os.environ.get('KURAMA_PRODUCTION', '').lower() in ('1', 'true', 'yes'):
                raise ValueError(
                    "MODO PRODUÇÃO: pacote 'cryptography' obrigatório para AES-256-GCM. "
                    "Instale com: pip install cryptography"
                )
            warnings.warn(
                "[WARN] AES-256-GCM não disponível: pacote 'cryptography' não instalado. "
                "Retornando dados sem descriptografar!",
                RuntimeWarning, stacklevel=2
            )
            return ciphertext

    # ─── Assinatura de Mensagens P2P ─────────────────────────────

    @staticmethod
    def sign_p2p_message(private_key_pem: str, payload: dict) -> str:
        """
        Assina uma mensagem P2P (dict) com a chave privada ECDSA do nó.
        A assinatura cobre o payload JSON canônico (sort_keys=True)
        para garantir integridade completa da mensagem.

        Usa ECDSA (SECP256k1) com SHA-256, a mesma curva e hash
        usados nas transações. A assinatura é codificada em Base64
        para transporte via header HTTP.

        Args:
            private_key_pem: Chave privada ECDSA em formato PEM
            payload: Dicionário a ser assinado

        Returns:
            Assinatura Base64 (string segura para header HTTP)
        """
        from ecdsa import SigningKey, SECP256k1
        from ecdsa.util import sigencode_der

        sk = SigningKey.from_pem(private_key_pem)
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        signature = sk.sign(
            payload_str.encode('utf-8'),
            hashfunc=hashlib.sha256,
            sigencode=sigencode_der
        )
        return base64.b64encode(signature).decode('utf-8')

    @staticmethod
    def verify_p2p_signature(payload: dict, signature_b64: str,
                             public_key_pem: str) -> bool:
        """
        Verifica a assinatura P2P de uma mensagem recebida.

        Reconstroi o payload canônico (sort_keys=True) e verifica
        a assinatura ECDSA contra a chave pública do remetente.
        Usa comparação em TEMPO CONSTANTE internamente via ECDSA.

        Args:
            payload: Dicionário recebido (já parseado)
            signature_b64: Assinatura em Base64 (do header HTTP)
            public_key_pem: Chave pública PEM do nó remetente

        Returns:
            True se a assinatura é válida para este payload
        """
        from ecdsa import VerifyingKey, SECP256k1, BadSignatureError
        from ecdsa.util import sigdecode_der

        try:
            vk = VerifyingKey.from_pem(public_key_pem.encode('utf-8'))
            sig_bytes = base64.b64decode(signature_b64)
            payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            return vk.verify(
                sig_bytes,
                payload_str.encode('utf-8'),
                hashfunc=hashlib.sha256,
                sigdecode=sigdecode_der
            )
        except (BadSignatureError, Exception):
            return False
