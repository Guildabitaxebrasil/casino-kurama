"""
Gerenciador de Nós (Node Manager).
Simula múltiplos nós rodando em paralelo, cada um com sua própria
blockchain e carteira. Permite testar o mecanismo de consenso.

Cada nó tem:
- Instância própria da blockchain
- Endereço na rede (URL) — HTTPS com certificado auto-assinado
- Carteira para receber recompensas
- Lista de nós vizinhos

A comunicação entre nós é criptografada via HTTPS. Certificados
auto-assinados são aceitos com verificação SSL reduzida (modo dev).
"""
import json
import os
import hashlib
import base64
import threading
import time
import urllib3
import requests
from typing import Dict, List, Optional

from core.blockchain import Blockchain
from core.wallet import Wallet
from core.crypto_utils import CryptoUtils
from config import (
    NODE_HEALTH_TIMEOUT, SYNC_INTERVAL, CA_CERT_FILE,
    NODE_AUTH_HEADER, NETWORK_SECRET, SSL_CERT_DIR,
    P2P_SIGNATURE_HEADER, P2P_PUBKEY_HEADER
)

# ─── Suprime warnings de certificado auto-assinado ─────────────
# Em ambiente educacional/desenvolvimento, certificados SSL
# auto-assinados são esperados. Em produção, use certificados
# de uma CA confiável e remova este suppress.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class NodeInfo:
    """
    Representa um nó na rede simulada.
    Armazena estado, configuração e carteira do nó.
    """

    def __init__(self, node_id: str, host: str = 'localhost',
                 port: int = 5000, use_ssl: bool = True):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        protocol = 'https' if use_ssl else 'http'
        self.url = f'{protocol}://{host}:{port}'
        self.blockchain = Blockchain(difficulty=4)
        self.wallet = Wallet()
        self.active = False


class NodeManager:
    """
    Gerencia múltiplos nós para simular uma rede blockchain.

    Facilita:
    - Criação de múltiplos nós
    - Registro de nós vizinhos
    - Mineração distribuída
    - Testes de consenso
    """

    def __init__(self, base_port: int = 5000, use_ssl: bool = True,
                 identity: 'NodeIdentity' = None):
        """
        Inicializa o gerenciador de nós.

        Args:
            base_port: Porta base para o primeiro nó
            use_ssl: Usar HTTPS em vez de HTTP
            identity: Identidade criptográfica do nó (ECDSA persistente)
        """
        self.base_port = base_port
        self.use_ssl = use_ssl
        self.nodes: Dict[str, NodeInfo] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.owner = identity

    @staticmethod
    def _request(method: str, url: str,
                 sign_payload: bool = False,
                 signing_key_pem: str = None,
                 **kwargs) -> requests.Response:
        """
        Faz requisição HTTP(S) com verificação de certificado,
        autenticação P2P e ASSINATURA ECDSA do payload.

        Cada requisição P2P é:
        1. Autenticada via header X-Kurama-Auth (shared secret)
        2. ASSINADA via ECDSA SECP256k1 com a chave privada do nó
           (quando sign_payload=True e signing_key_pem é fornecido)
        3. Criptografada via TLS com verificação de CA

        A assinatura ECDSA garante NÃO-REPÚDIO: o receptor pode
        provar que a mensagem veio deste nó específico, mesmo
        que o secret compartilhado seja comprometido.

        Args:
            method: 'GET' ou 'POST'
            url: URL completa
            sign_payload: Se True, assina o payload JSON com ECDSA
            signing_key_pem: Chave privada ECDSA PEM para assinar
            **kwargs: Argumentos adicionais

        Returns:
            Response object
        """
        import os
        kwargs.setdefault('timeout', NODE_HEALTH_TIMEOUT)

        # ─── Verificação de Certificado ─────────────────────────
        if os.path.exists(CA_CERT_FILE):
            kwargs['verify'] = CA_CERT_FILE
        elif os.environ.get('KURAMA_PRODUCTION', '').lower() in ('1', 'true', 'yes'):
            raise RuntimeError(
                "MODO PRODUÇÃO: CA_CERT_FILE não encontrado. "
                "Gere a CA com: openssl req -x509 -newkey rsa:2048 "
                "-keyout certs/ca.key -out certs/ca.pem -days 3650 -nodes"
            )
        else:
            import warnings
            warnings.warn(
                "[WARN] verify=False: MITM vulnerável! "
                f"Configure CA em {CA_CERT_FILE}",
                RuntimeWarning, stacklevel=2
            )
            kwargs['verify'] = False

        # ─── Headers (Autenticação HMAC-SHA256) ────────────────
        # Em vez de enviar NETWORK_SECRET em texto puro, envia
        # HMAC-SHA256(secret, body). O secret NUNCA viaja no header.
        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        from core.crypto_utils import CryptoUtils
        body_data = kwargs.get('data', b'')
        if isinstance(body_data, str):
            body_data = body_data.encode('utf-8')
        elif isinstance(body_data, dict):
            body_data = json.dumps(body_data, sort_keys=True).encode('utf-8')
        elif kwargs.get('json'):
            # Handle requests.json parameter
            body_data = json.dumps(kwargs['json'], sort_keys=True).encode('utf-8')
        kwargs['headers'][NODE_AUTH_HEADER] = CryptoUtils.hmac_sha256(
            NETWORK_SECRET, body_data
        )

        # ─── AEAD Encryption (AES-256-GCM) ──────────────────────
        # Segunda camada de proteção além do TLS: o payload JSON
        # é criptografado com AES-256-GCM usando NETWORK_SECRET
        # como chave compartilhada. Garante confidencialidade e
        # integridade mesmo que o TLS seja comprometido (verify=False em dev).
        from config import P2P_ENCRYPTION
        if (P2P_ENCRYPTION and method.upper() == 'POST'
                and (kwargs.get('json') is not None)):
            from core.crypto_utils import CryptoUtils
            # Deriva chave AES-256 do NETWORK_SECRET via SHA-256
            enc_key = hashlib.sha256(
                NETWORK_SECRET.encode('utf-8')
            ).digest()
            plaintext = json.dumps(
                kwargs['json'], sort_keys=True
            ).encode('utf-8')
            # AAD = URL da requisição (liga ciphertext ao destino)
            aad = url.encode('utf-8')
            enc_nonce, ciphertext = CryptoUtils.aes256gcm_encrypt(
                enc_key, plaintext, aad
            )
            # Substitui o payload JSON pelo envelope criptografado
            kwargs['json'] = {
                '_encrypted': True,
                '_ciphertext': base64.b64encode(ciphertext).decode('utf-8'),
                '_nonce': base64.b64encode(enc_nonce).decode('utf-8')
            }
            # Atualiza o HMAC para cobrir o payload criptografado
            new_body = json.dumps(kwargs['json'], sort_keys=True).encode('utf-8')
            kwargs['headers'][NODE_AUTH_HEADER] = CryptoUtils.hmac_sha256(
                NETWORK_SECRET, new_body
            )
            kwargs['headers']['X-Kurama-Encrypted'] = 'aes256gcm'

        # ─── Assinatura ECDSA do Payload P2P ───────────────────
        # Se for POST com JSON e temos chave privada, assinamos
        # o payload para garantir integridade e não-repúdio.
        if (sign_payload and signing_key_pem
                and method.upper() == 'POST'
                and 'json' in kwargs):
            from core.crypto_utils import CryptoUtils
            payload_str = json.dumps(kwargs['json'], sort_keys=True)
            signature = CryptoUtils.sign_p2p_message(
                signing_key_pem, kwargs['json']
            )
            kwargs['headers'][P2P_SIGNATURE_HEADER] = signature
            kwargs['headers'][P2P_PUBKEY_HEADER] = (
                Wallet.get_public_key_from_private(signing_key_pem)
            )

        if method.upper() == 'GET':
            return requests.get(url, **kwargs)
        elif method.upper() == 'POST':
            return requests.post(url, **kwargs)
        else:
            raise ValueError(f"Método HTTP inválido: {method}")

    def create_node(self, node_id: str = None, port: int = None,
                    difficulty: int = 4) -> NodeInfo:
        """
        Cria um novo nó na rede.

        Args:
            node_id: Identificador único (auto-gerado se None)
            port: Porta do servidor (auto-atribuída se None)

        Returns:
            Informações do nó criado
        """
        node_id = node_id or CryptoUtils.generate_node_id()[:8]
        port = port or (self.base_port + len(self.nodes))

        node = NodeInfo(node_id=node_id, port=port, use_ssl=self.use_ssl)
        node.blockchain = Blockchain(difficulty=difficulty)
        node.wallet = Wallet()

        self.nodes[node_id] = node
        print(f"[CREATE] Nó '{node_id}' criado em {node.url}")
        print(f"   Carteira: {node.wallet.address[:20]}...")

        return node

    def start_node(self, node_id: str) -> bool:
        """
        Inicia o servidor Flask de um nó em uma thread separada.

        Args:
            node_id: Identificador do nó

        Returns:
            True se iniciou com sucesso
        """
        if node_id not in self.nodes:
            print(f"[ERR] Nó '{node_id}' não encontrado")
            return False

        node = self.nodes[node_id]
        if node.active:
            print(f"[WARN] Nó '{node_id}' já está ativo")
            return False

        # Importa aqui para evitar circular imports
        from api.routes import create_app
        app = create_app(
            blockchain=node.blockchain,
            node_address=node.wallet.address,
            port=node.port
        )

        # Registra os vizinhos no app (dict compatível com app.nodes)
        for other_id, other_node in self.nodes.items():
            if other_id != node_id and other_node.active:
                app.nodes[other_node.url] = {
                    'url': other_node.url,
                    'hostname': other_node.host,
                    'resolved_ip': '127.0.0.1',
                    'registered_at': time.time(),
                    'last_seen': time.time()
                }

        # Inicia em thread separada
        # Configura SSL se habilitado
        ssl_context = None
        if self.use_ssl:
            from config import SSL_CERT_FILE, SSL_KEY_FILE
            import os
            if os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE):
                ssl_context = (SSL_CERT_FILE, SSL_KEY_FILE)

        def run():
            print(f"[START] Nó '{node_id}' rodando em {node.url}")
            print(f"   Endereço do minerador: {node.wallet.address[:20]}...")
            app.run(
                host=node.host,
                port=node.port,
                ssl_context=ssl_context,
                debug=False,
                use_reloader=False
            )

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.threads[node_id] = thread
        node.active = True

        # Pequena pausa para o servidor iniciar
        time.sleep(1)
        return True

    def stop_node(self, node_id: str) -> bool:
        """
        Para um nó (marca como inativo).
        Nota: Flask não tem shutdown programático fácil,
        então marcamos como inativo.

        Args:
            node_id: Identificador do nó
        """
        if node_id not in self.nodes:
            return False

        self.nodes[node_id].active = False
        print(f"[STOP] Nó '{node_id}' parado")
        return True

    def register_neighbors(self):
        """
        Registra todos os nós ativos como vizinhos entre si.
        Cria uma rede completamente conectada via chamadas HTTP reais.
        """
        active_nodes = {
            nid: n for nid, n in self.nodes.items()
            if n.active
        }

        if len(active_nodes) < 2:
            print("[WARN] São necessários pelo menos 2 nós ativos")
            return

        print(f"[LINK] Registrando {len(active_nodes)} nós como vizinhos via HTTP...")

        for nid, node in active_nodes.items():
            others = [
                other.url
                for other_id, other in active_nodes.items()
                if other_id != nid
            ]

            try:
                resp = self._request(
                    'POST',
                    f'{node.url}/nodes/register',
                    json={'nodes': others},
                    timeout=2
                )
                if resp.status_code == 201:
                    data = resp.json()
                    print(f"   [OK] {nid} → {data.get('total_nodes', 0)} vizinhos")
                else:
                    print(f"   [WARN] {nid} → erro: {resp.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"   [ERR] {nid} → falha: {e}")

        print("[OK] Rede configurada com sucesso!")

    # ─── Health Check ────────────────────────────────────────────

    def check_node_health(self, node_url: str) -> dict:
        """
        Verifica a saúde de um nó via /api/health.

        Args:
            node_url: URL base do nó

        Returns:
            Dict com status, latência e informações
        """
        try:
            start = time.time()
            resp = self._request(
                'GET', f'{node_url}/api/health',
                timeout=NODE_HEALTH_TIMEOUT
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'url': node_url,
                    'active': True,
                    'blocks': data.get('blocks', 0),
                    'node_id': data.get('node_id', 'unknown'),
                    'latency_ms': latency
                }
        except requests.exceptions.RequestException:
            pass

        return {
            'url': node_url,
            'active': False,
            'blocks': 0,
            'node_id': 'unknown',
            'latency_ms': None
        }

    # ─── Broadcast ──────────────────────────────────────────────

    def broadcast_block(self, block_dict: dict):
        """
        Transmite um novo bloco para todos os nós ativos via POST.
        A requisição é ASSINADA com ECDSA (chave privada do nó)
        para garantir integridade e não-repúdio.

        Inclui envelope de segurança: nonce + timestamp + expiração
        para prevenir replay attacks.

        Args:
            block_dict: Dicionário do bloco a ser transmitido
        """
        signing_key = self.owner.private_key_pem if self.owner else None
        payload = {'block': block_dict}
        for nid, node in self.nodes.items():
            if not node.active:
                continue
            try:
                from core.p2p_security import P2PNonceManager
                nm = P2PNonceManager()
                secured = nm.create_message_envelope(payload)
                self._request(
                    'POST',
                    f'{node.url}/blocks/new',
                    json=secured,
                    sign_payload=True,
                    signing_key_pem=signing_key,
                    timeout=1
                )
            except requests.exceptions.RequestException:
                pass

    def broadcast_transaction(self, tx_dict: dict):
        """
        Transmite uma nova transação para todos os nós ativos.
        A requisição é ASSINADA com ECDSA (chave privada do nó).

        Args:
            tx_dict: Dicionário da transação a ser transmitida
        """
        signing_key = self.owner.private_key_pem if self.owner else None
        for nid, node in self.nodes.items():
            if not node.active:
                continue
            try:
                self._request(
                    'POST',
                    f'{node.url}/transactions/new',
                    json=tx_dict,
                    sign_payload=True,
                    signing_key_pem=signing_key,
                    timeout=1
                )
            except requests.exceptions.RequestException:
                pass

    # ─── Sincronização em Background ────────────────────────────

    def _sync_loop(self, node_id: str):
        """
        Loop de sincronização em background com proteção anti-eclipse.
        Periodicamente executa o consenso com os vizinhos.

        Proteções:
        1. EclipseProtection.select_peers() — amostra aleatória ponderada
        2. EclipseProtection.detect_same_chain() — detecção de chains idênticas
        3. Limite de peers consultados por ciclo (não consulta todos)

        Args:
            node_id: ID do nó que deve executar o sync
        """
        node = self.nodes.get(node_id)
        if not node:
            return

        from core.p2p_security import EclipseProtection
        from config import (ECLIPSE_MAX_PER_SUBNET, ECLIPSE_MIN_DIVERSITY,
                            ECLIPSE_MAX_OUTGOING, ECLIPSE_SYNC_SAMPLE_SIZE,
                            ECLIPSE_SUSPICIOUS_SAME_CHAIN)
        eclipse = EclipseProtection(
            max_per_subnet=ECLIPSE_MAX_PER_SUBNET,
            min_diversity=ECLIPSE_MIN_DIVERSITY,
            max_outgoing=ECLIPSE_MAX_OUTGOING,
            sync_sample_size=ECLIPSE_SYNC_SAMPLE_SIZE,
            suspicious_same_chain=ECLIPSE_SUSPICIOUS_SAME_CHAIN
        )

        while node.active:
            try:
                # Prepara lista de peers ativos
                active_peers = [
                    (other_node.url, 0)
                    for other_id, other_node in self.nodes.items()
                    if other_id != node_id and other_node.active
                ]

                # Seleciona amostra (evita eclipse: não consulta todos)
                selected_urls = eclipse.select_peers(
                    active_peers,
                    sample_size=ECLIPSE_SYNC_SAMPLE_SIZE
                )

                other_chains = []
                for url in selected_urls:
                    try:
                        resp = self._request(
                            'GET',
                            f'{url}/chain',
                            timeout=2
                        )
                        if resp.status_code == 200:
                            chain_data = resp.json().get('chain', [])
                            other_chains.append(chain_data)
                            # Detecta chains idênticas (sinal de eclipse)
                            valid, msg = eclipse.detect_same_chain(
                                {'chain': chain_data}, url
                            )
                            if not valid:
                                print(f"   {msg}")
                    except requests.exceptions.RequestException:
                        pass

                # Executa consenso
                if other_chains:
                    node.blockchain.resolve_conflicts(other_chains)

                time.sleep(SYNC_INTERVAL)
            except Exception as e:
                print(f"[WARN] Erro no sync de {node_id}: {e}")
                time.sleep(SYNC_INTERVAL)

    def start_background_sync(self, node_id: str):
        """
        Inicia a sincronização em background para um nó.

        Args:
            node_id: ID do nó
        """
        thread = threading.Thread(
            target=self._sync_loop,
            args=(node_id,),
            daemon=True
        )
        thread.start()
        print(f"[SYNC] Sincronização em background iniciada para {node_id}")

    def start_all_background_syncs(self):
        """Inicia sincronização em background para todos os nós ativos."""
        for nid, node in self.nodes.items():
            if node.active:
                self.start_background_sync(nid)

    def start_network(self, num_nodes: int = 3):
        """
        Cria e inicia uma rede completa de nós.

        Args:
            num_nodes: Número de nós na rede
        """
        print(f"\n{'='*60}")
        print(f"[NET] INICIANDO REDE BLOCKCHAIN COM {num_nodes} NÓS")
        print(f"{'='*60}\n")

        # Cria todos os nós
        for i in range(num_nodes):
            node_id = f"node_{i}"
            port = self.base_port + i
            self.create_node(node_id=node_id, port=port)

        # Inicia todos os nós
        for nid in self.nodes:
            self.start_node(nid)

        # Registra vizinhos
        self.register_neighbors()

        # Inicia sincronização em background
        self.start_all_background_syncs()

        print(f"\n{'='*60}")
        print("[OK] REDE INICIADA COM SUCESSO!")
        print(f"{'='*60}")
        print(f"\n[LIST] Nós disponíveis:")
        for nid, node in self.nodes.items():
            print(f"   {nid}: {node.url}")
        print(f"\n[TIP] Dica: Use curl ou Postman para interagir com os nós.")
        print(f"   Exemplo: curl {self.nodes[list(self.nodes.keys())[0]].url}/chain")

    def get_network_stats(self) -> dict:
        """
        Retorna estatísticas de toda a rede.

        Returns:
            Dicionário com estatísticas de cada nó
        """
        stats = {}
        for nid, node in self.nodes.items():
            stats[nid] = {
                'url': node.url,
                'active': node.active,
                'blocks': len(node.blockchain.chain),
                'pending_tx': len(node.blockchain.pending_transactions),
                'difficulty': node.blockchain.difficulty,
                'balance': node.blockchain.get_balance(node.wallet.address),
                'wallet': node.wallet.address[:20] + '...'
            }
        return stats

    def print_network_status(self):
        """Imprime o status de todos os nós da rede."""
        print(f"\n{'='*60}")
        print("[STATS] STATUS DA REDE")
        print(f"{'='*60}")

        for nid, node in self.nodes.items():
            status = '[ON]' if node.active else '[OFF]'
            balance = node.blockchain.get_balance(node.wallet.address)
            print(f"\n{status} {nid} ({node.url})")
            print(f"   Blocos: {len(node.blockchain.chain)} | "
                  f"Dificuldade: {node.blockchain.difficulty} | "
                  f"Pendentes: {len(node.blockchain.pending_transactions)}")
            print(f"   Saldo: {balance:.2f} coins")
            print(f"   Carteira: {node.wallet.address}")
