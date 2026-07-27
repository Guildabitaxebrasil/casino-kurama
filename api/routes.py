"""
API REST da Blockchain.
Fornece endpoints HTTP para interagir com a blockchain.

Endpoints:
  GET  /chain              - Visualizar blockchain completa
  POST /mine               - Minerar um novo bloco
  POST /transactions/new   - Criar nova transação
  POST /wallet/new         - Criar nova carteira
  GET  /balance/<address>  - Consultar saldo
  POST /nodes/register     - Registrar nós vizinhos
  POST /nodes/resolve      - Executar consenso
  GET  /validate           - Validar blockchain
  GET  /stats              - Estatísticas da blockchain
  GET  /api/events         - SSE: Eventos em tempo real da blockchain
  GET  /api/docs           - Documentação Swagger/OpenAPI

Endpoints Explorer (/api/*):
  GET  /api/health              - Health check
  GET  /api/chain/since/<index> - Blocos a partir do índice
  GET  /api/blocks/<identifier> - Bloco por index ou hash
  GET  /api/transactions        - Transações (paginação/filtros)
  GET  /api/search?q=<term>     - Busca unificada
  GET  /api/nodes               - Lista nós com status
  POST /api/nodes/sync          - Trigger de consenso
  GET  /api/chart               - Dados para gráfico do Dashboard
  GET  /api/mempool             - Estatísticas da mempool

Endpoints de Rede (P2P):
  POST /blocks/new              - Receber novo bloco de outro nó
"""
from flask import Flask, jsonify, request, Response, stream_with_context, make_response as _flask_make_response
from flask_cors import CORS
import requests
import json
import base64
import time
import threading
import urllib3
import queue
from functools import wraps
from flasgger import Swagger

from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from core.wallet import Wallet
from core.blockchain import Blockchain
import os
from config import (
    CORS_ORIGINS, CA_CERT_FILE, NODE_AUTH_HEADER, NETWORK_SECRET,
    SSL_CERT_DIR, P2P_SIGNATURE_HEADER, P2P_PUBKEY_HEADER,
    P2P_REQUIRE_SIGNATURE
)

# ─── Suprime warnings SSL para certs auto-assinados (dev) ──────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Helper: Detecção de Modo Produção ──────────────────────────
def _is_production_mode() -> bool:
    """Verifica se o servidor está em modo produção."""
    return os.environ.get('KURAMA_PRODUCTION', '').lower() in ('1', 'true', 'yes')


# ─── Rate Limiter Multi-Camada ────────────────────────────────────
# Rate limit por IP + wallet address + adaptativo por rejeições.
# Previne abuso distribuído (botnet) e waste de CPU via ECDSA verify.
class AdvancedRateLimiter:
    """
    Rate limiter multi-camada para proteção de produção.

    Camadas:
    1. Por IP: limite base por endereço IP
    2. Por wallet: limite por endereço de carteira (anti-botnet)
    3. Adaptativo: IPs com muitas rejeições têm limite reduzido
    4. Suporta X-Forwarded-For para proxies reversos
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._ip_clients: dict = {}
        self._wallet_clients: dict = {}
        self._rejection_count: dict = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip: str, wallet: str = None) -> bool:
        now = time.time()
        with self._lock:
            # Penalidade adaptativa: IPs com muitas rejeições
            # têm limite reduzido progressivamente.
            rejections = self._rejection_count.get(ip, 0)
            effective_max = max(1, self.max_requests - rejections * 5)

            # Rate limit por IP
            if ip not in self._ip_clients:
                self._ip_clients[ip] = []
            self._ip_clients[ip] = [
                t for t in self._ip_clients[ip]
                if now - t < self.window_seconds
            ]
            if len(self._ip_clients[ip]) >= effective_max:
                return False

            # Rate limit por wallet (se fornecido)
            if wallet:
                if wallet not in self._wallet_clients:
                    self._wallet_clients[wallet] = []
                self._wallet_clients[wallet] = [
                    t for t in self._wallet_clients[wallet]
                    if now - t < self.window_seconds
                ]
                # Wallet: 10 req/min (anti-botnet)
                if len(self._wallet_clients[wallet]) >= 10:
                    return False

            self._ip_clients[ip].append(now)
            if wallet:
                self._wallet_clients[wallet].append(now)
            return True

    def register_rejection(self, ip: str):
        """Incrementa contagem de rejeições para rate limit adaptativo."""
        with self._lock:
            self._rejection_count[ip] = self._rejection_count.get(ip, 0) + 1

rate_limiter = AdvancedRateLimiter(max_requests=60, window_seconds=60)


# ─── SSE Event Manager ────────────────────────────────────────────
# Gerencia assinantes de eventos Server-Sent Events (SSE).
# Permite que o frontend receba atualizacoes em tempo real sem polling.
class SSEEventManager:
    """
    Gerenciador de eventos Server-Sent Events.

    Mantem uma lista de filas (uma por cliente SSE) e publica
    eventos para todos os assinantes quando algo muda na blockchain.
    """

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """Cria uma nova fila para um assinante SSE."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """Remove um assinante."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, data: dict):
        """Publica um evento para todos os assinantes ativos."""
        with self._lock:
            dead: list[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait({'event': event_type, 'data': data})
                except queue.Full:
                    dead.append(q)
            # Remove filas cheias (cliente lento/desconectado)
            for q in dead:
                self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

sse_manager = SSEEventManager()


# ─── Rate Limiter P2P (por peer) ──────────────────────────────
# Rate limit distribuído por identidade de peer (node_id).
# Cada peer tem limite independente do rate limit de IP.
from config import P2P_RATE_LIMIT as _P2P_LIMIT
p2p_rate_limiter = AdvancedRateLimiter(
    max_requests=_P2P_LIMIT,
    window_seconds=60
)

# ─── P2P Nonce Manager (anti-replay) ──────────────────────────
# Cache LRU com 100k entradas, TTL de 5 min.
from config import P2P_NONCE_CACHE_SIZE, P2P_NONCE_TTL, P2P_MAX_CLOCK_DRIFT
from core.p2p_security import P2PNonceManager, PeerScoreManager
p2p_nonce_manager = P2PNonceManager(
    max_size=P2P_NONCE_CACHE_SIZE,
    ttl=P2P_NONCE_TTL,
    max_clock_drift=P2P_MAX_CLOCK_DRIFT
)

# ─── Peer Score Manager ───────────────────────────────────────
from config import P2P_PEER_SCORE_BAN_THRESHOLD as _BAN_THRESH
from config import P2P_PEER_SCORE_BAN_BASE as _BAN_BASE
from config import P2P_PEER_SCORE_BAN_MAX as _BAN_MAX
peer_score_manager = PeerScoreManager(
    ban_threshold=_BAN_THRESH,
    ban_base_seconds=_BAN_BASE,
    ban_max_seconds=_BAN_MAX
)

def _get_client_ip() -> str:
    """
    Obtém o IP real do cliente, suportando proxies reversos.
    Usa X-Forwarded-For quando disponível (ex: atrás de nginx/reverse proxy),
    com fallback para request.remote_addr.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # Pega o primeiro IP da cadeia (cliente real)
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'

def _verified_request(method: str, url: str, **kwargs) -> requests.Response:
    """
    Faz requisição HTTPS com verificação de certificado via CA.

    Em MODO PRODUÇÃO (KURAMA_PRODUCTION=1), FAIL HARD se CA não
    existe — sem fallback inseguro. Em dev, aviso de MITM.

    Args:
        method: 'GET' ou 'POST'
        url: URL completa
        **kwargs: Argumentos adicionais

    Returns:
        Response object
    """
    kwargs.setdefault('timeout', 2)

    if os.path.exists(CA_CERT_FILE):
        kwargs['verify'] = CA_CERT_FILE
    elif os.environ.get('KURAMA_PRODUCTION', '').lower() in ('1', 'true', 'yes'):
        raise RuntimeError(
            "MODO PRODUÇÃO: CA_CERT_FILE não encontrado. "
            "Gere a CA e configure certs/ca.pem"
        )
    else:
        import warnings
        warnings.warn(
            "[WARN] verify=False: MITM vulnerável! "
            f"Configure CA em {CA_CERT_FILE}",
            RuntimeWarning, stacklevel=2
        )
        kwargs['verify'] = False

    # mTLS: certificado de cliente se configurado
    client_cert = os.environ.get('KURAMA_CLIENT_CERT')
    client_key = os.environ.get('KURAMA_CLIENT_KEY')
    if client_cert and client_key and os.path.exists(client_cert) and os.path.exists(client_key):
        kwargs['cert'] = (client_cert, client_key)

    # ─── HMAC-SHA256 para Autenticação P2P ────────────────────────
    # Em vez de enviar o NETWORK_SECRET em texto puro no header,
    # envia HMAC-SHA256(secret, body). O receptor verifica com
    # hmac.compare_digest() em TEMPO CONSTANTE.
    # Se não houver body (GET), usa string vazia como body HMAC.
    from config import NETWORK_SECRET as _secret, NODE_AUTH_HEADER
    from core.crypto_utils import CryptoUtils
    body_data = kwargs.get('data', b'')
    if isinstance(body_data, str):
        body_data = body_data.encode('utf-8')
    elif isinstance(body_data, dict):
        body_data = json.dumps(body_data, sort_keys=True).encode('utf-8')
    hmac_value = CryptoUtils.hmac_sha256(_secret, body_data)
    kwargs.setdefault('headers', {})[NODE_AUTH_HEADER] = hmac_value

    if method.upper() == 'GET':
        return requests.get(url, **kwargs)
    elif method.upper() == 'POST':
        return requests.post(url, **kwargs)
    else:
        raise ValueError(f"Método HTTP inválido: {method}")

def _require_p2p_hmac(f):
    """
    Decorator que exige autenticação P2P via HMAC-SHA256 entre nós.

    SEGURANÇA:
    1. HMAC-SHA256 em vez de secret em texto puro — o secret NUNCA
       viaja no header, apenas o HMAC derivado dele
    2. O HMAC cobre o body da requisição — prova de integridade +
       autenticidade (non-repudiation)
    3. hmac.compare_digest() compara em TEMPO CONSTANTE — previne
       timing attacks que podem vazar o secret caractere por caractere
    4. Cada requisição tem HMAC único (body-dependent) — previne replay
       de headers entre requisições diferentes

    Uso:
        @app.route('/blocks/new', methods=['POST'])
        @_require_p2p_hmac
        def receive_block():
            ...

    Header esperado:
        X-Kurama-Auth: <HMAC-SHA256(NETWORK_SECRET, request_body)>
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from config import NETWORK_SECRET as _secret
        from core.crypto_utils import CryptoUtils
        auth_header = request.headers.get(NODE_AUTH_HEADER, '')
        body = request.get_data()
        if not _secret or not CryptoUtils.hmac_verify(_secret, body, auth_header):
            return jsonify({
                'error': 'Acesso P2P não autorizado. HMAC inválido.'
            }), 401
        return f(*args, **kwargs)
    return decorated

# Alias para compatibilidade com código existente
_require_p2p_auth = _require_p2p_hmac

def rate_limit(f):
    """Decorator que aplica rate limiting multi-camada (IP + wallet).
    
    Adiciona headers X-RateLimit-* em todas as respostas para
    que os clientes saibam seus limites (M-01).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = _get_client_ip()
        wallet = None
        if request.is_json:
            data = request.get_json(silent=True) or {}
            if 'sender' in data:
                wallet = data.get('sender')
            elif 'sender_address' in data:
                wallet = data.get('sender_address')

        if not rate_limiter.is_allowed(ip, wallet):
            return jsonify({
                'error': 'Muitas requisições. Aguarde e tente novamente.',
                'retry_after': 60
            }), 429

        try:
            response = f(*args, **kwargs)
        except Exception as e:
            rate_limiter.register_rejection(ip)
            raise e

        # ─── X-RateLimit Headers (M-01) ────────────────────────
        if isinstance(response, tuple):
            response = _flask_make_response(response)
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(rate_limiter.max_requests)
            response.headers['X-RateLimit-Window'] = str(rate_limiter.window_seconds)
            response.headers['X-RateLimit-Policy'] = 'ip;w=' + str(rate_limiter.window_seconds)

        return response
    return decorated


# ─── Rate Limit P2P (por peer) ─────────────────────────────────
# Similar ao rate_limit mas usa o p2p_rate_limiter (por peer_id).
# Uso: endpoints P2P (/blocks/new, /nodes/register, /nodes/resolve)
def rate_limit_peer(f):
    """Rate limit para requisições P2P baseado em node_id."""
    @wraps(f)
    def decorated(*args, **kwargs):
        peer_id = request.headers.get(P2P_PUBKEY_HEADER, _get_client_ip())
        if not p2p_rate_limiter.is_allowed(peer_id):
            return jsonify({
                'error': 'Rate limit P2P excedido. Aguarde.',
                'retry_after': 60
            }), 429
        try:
            response = f(*args, **kwargs)
            return response
        except Exception as e:
            p2p_rate_limiter.register_rejection(peer_id)
            raise e
    return decorated


# ─── P2P Nonce Validation (anti-replay) ────────────────────────
# Verifica nonce + timestamp + expiração em mensagens P2P.
# Previne replay attacks: mesma mensagem reenviada = rejeitada.
def require_p2p_nonce(f):
    """Valida nonce P2P em endpoints que recebem mensagens P2P."""
    @wraps(f)
    def decorated(*args, **kwargs):
        data = request.get_json(silent=True) or {}
        valid, reason = p2p_nonce_manager.validate_message(data)
        if not valid:
            peer_id = request.headers.get(P2P_PUBKEY_HEADER, 'unknown')
            peer_score_manager.record_event(
                peer_id, 'invalid_signature', url=peer_id
            )
            return jsonify({'error': f'Mensagem rejeitada: {reason}'}), 401
        return f(*args, **kwargs)
    return decorated


def create_app(blockchain: Blockchain = None, node_address: str = None,
               port: int = 5000) -> Flask:
    """
    Cria e configura a aplicação Flask.

    Args:
        blockchain: Instância da blockchain (criada se None)
        node_address: Endereço do nó (carteira do minerador)
        port: Porta do servidor

    Returns:
        Aplicação Flask configurada
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024 * 100  # 100 KB max payload
    CORS(app, origins=CORS_ORIGINS)

    # ─── Swagger / OpenAPI ─────────────────────────────────────
    app.config['SWAGGER'] = {
        'title': 'KuramaChain API',
        'description': '''
API REST da Blockchain Kurama.

Endpoints principais:
- **/chain** — Visualizar blockchain completa
- **/mine** — Minerar um novo bloco (Proof of Work)
- **/transactions/new** — Criar nova transação
- **/wallet/new** — Gerar nova carteira
- **/balance/<endereço>** — Consultar saldo
- **/stats** — Estatísticas da blockchain
- **/api/events** — Eventos em tempo real (SSE)

Documentação completa dos endpoints e schemas.
''',
        'version': '1.0.0',
        'termsOfService': '',
        'hide_top_bar': True,
    }
    if _is_production_mode():
        app.config['SWAGGER'] = {'hide_top_bar': True, 'title': ''}
    Swagger(app)

    # ─── Security Headers + Error Sanitization ────────────────
    @app.after_request
    def add_security_headers(response):
        """Adiciona headers de segurança em todas as respostas HTTP e sanitiza erros."""
        # Sanitização de erros: remove detalhes internos das mensagens
        # para prevenir vazamento de informações de implementação.
        if response.status_code >= 500 and response.is_json:
            try:
                data = response.get_json()
                if data and 'error' in data:
                    # Substitui mensagem de erro por versão genérica
                    data['error'] = 'Erro interno do servidor'
                    response.set_data(json.dumps(data))
            except Exception:
                pass
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        # Content-Security-Policy: restritivo para prevenir XSS
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
        )
        # Strict-Transport-Security: força HTTPS no navegador (1 ano)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Referrer-Policy: não enviar referer em requisições cross-origin
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    # Estado da aplicação
    app.blockchain = blockchain or Blockchain(difficulty=4)

    # Nós vizinhos na rede (URLs base)
    # Dict: {url: {resolved_ip, registered_at, last_seen}}
    # Armazena IP resolvido para prevenir DNS rebinding attacks.
    app.nodes = {}

    def _get_node_urls():
        """Retorna lista de URLs de nós registrados."""
        return list(app.nodes.keys())

    def _is_node_registered(url: str) -> bool:
        """Verifica se URL já está registrada."""
        return url in app.nodes

    def _validate_node_dns(url: str, node_info: dict) -> bool:
        """
        Anti-DNS Rebinding: re-resolve o hostname e compara com o IP registrado.
        Se o DNS mudou desde o registro, a requisição é rejeitada.

        Args:
            url: URL do nó
            node_info: Dict com resolved_ip do registro

        Returns:
            True se o DNS ainda resolve para o mesmo IP
        """
        if not node_info:
            return False
        import socket, urllib.parse
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname or ''
            current_ips = socket.getaddrinfo(hostname, None)
            for addr_info in current_ips:
                current_ip = addr_info[4][0]
                if current_ip == node_info.get('resolved_ip'):
                    return True
            return False
        except (socket.gaierror, Exception):
            return False

    # Carteira do nó (para receber recompensas de mineração)
    # A chave privada NUNCA é armazenada no objeto Flask.
    # A wallet completa (com chave) é gerenciada pelo NodeManager.
    if node_address:
        app.node_wallet_address = node_address
    else:
        wallet = Wallet()
        app.node_wallet_address = wallet.address
        # A chave privada fica apenas na instância Wallet,
        # NUNCA exposta via atributos do app Flask.

    # ─── Rotas da API ────────────────────────────────────────────

    @app.route('/chain', methods=['GET'])
    def get_chain():
        """
        Retorna a blockchain completa.
        Endpoint principal para visualizar todos os blocos e transações.
        """
        response = {
            'chain': [block.to_dict() for block in app.blockchain.chain],
            'length': len(app.blockchain.chain),
            'pending_transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ],
            'node_id': app.blockchain.node_id,
            'difficulty': app.blockchain.difficulty
        }
        return jsonify(response), 200

    @app.route('/mine', methods=['POST'])
    @rate_limit
    def mine():
        """
        Minera um novo bloco.
        Executa o Proof of Work e recompensa o minerador com coins.

        A transação coinbase (recompensa) é adicionada automaticamente
        ao bloco durante a mineração — mesmo que não haja transações
        pendentes, o minerador recebe a recompensa do bloco.

        Body (JSON) opcional:
            miner_address: Endereço do minerador para receber a recompensa.
                          Se não fornecido, usa o endereço do nó.

        Exemplos:
            POST /mine                        → minera para o endereço do nó
            POST /mine {"miner_address": "15ZK..."}  → minera para seu endereço
        """
        # Aceita miner_address opcional no body da requisição
        data = request.get_json(silent=True) or {}
        miner_address = data.get('miner_address', app.node_wallet_address)

        # Valida o endereço fornecido
        if miner_address != app.node_wallet_address:
            if not CryptoUtils.is_valid_address(miner_address):
                return jsonify({
                    'error': f'Endereço de minerador inválido: {miner_address[:30]}...',
                    'hint': 'Forneça um endereço Base58 Kurama válido ou deixe vazio para usar o endereço do nó.'
                }), 400

        # Executa a mineração (a coinbase é inserida automaticamente
        # pelo mine_block(), mesmo com mempool vazia)
        block = app.blockchain.mine_block(miner_address)

        if not block:
            return jsonify({'message': 'Falha ao minerar bloco'}), 500

        # Extrai info da coinbase
        coinbase_tx = block.transactions[0] if block.transactions else None
        total_reward = coinbase_tx.amount if coinbase_tx else 0
        base_reward = app.blockchain.get_block_reward(block.index)
        fee_reward = total_reward - base_reward

        # Calcula saldo do minerador após mineração
        miner_balance = app.blockchain.get_balance(miner_address)

        response = {
            'message': 'Novo bloco minerado!',
            'block': block.to_dict(),
            'base_reward': base_reward,
            'fee_reward': max(0, fee_reward),
            'total_reward': total_reward,
            'miner_address': miner_address,
            'miner_balance': miner_balance,
            'difficulty': app.blockchain.difficulty,
            'supply': app.blockchain.get_supply_info()
        }
        # Notifica clientes SSE sobre atualização da chain
        sse_manager.publish('chain_updated', {
            'block_index': block.index,
            'block_hash': block.hash,
            'blocks': len(app.blockchain.chain),
            'miner_address': miner_address
        })
        sse_manager.publish('mempool_updated', {
            'pending': len(app.blockchain.pending_transactions)
        })
        return jsonify(response), 200

    @app.route('/transactions/new', methods=['POST'])
    @rate_limit
    def new_transaction():
        """
        Cria uma nova transação.

        Body (JSON):
        {
            "sender": "<chave pública do remetente>",
            "receiver": "<endereço do destinatário>",
            "amount": 10.0,
            "fee": 0.001,                     # Taxa (mín 0.001 KUR)
            "signature": "<assinatura hex>"   # Opcional
        }

        Se a transação não tem assinatura, ela é rejeitada.
        """
        data = request.get_json()

        # Valida campos obrigatórios
        required = ['sender', 'receiver', 'amount']
        if not data or not all(k in data for k in required):
            missing = [k for k in required if k not in (data or {})]
            return jsonify({
                'error': 'Campos obrigatórios ausentes',
                'required': required,
                'missing': missing
            }), 400

        try:
            # Adiciona a transação à pool de pendentes
            index = app.blockchain.add_transaction(
                sender=data['sender'],
                receiver=data['receiver'],
                amount=float(data['amount']),
                signature=data.get('signature'),
                sender_address=data.get('sender_address'),
                timestamp=data.get('timestamp'),
                fee=float(data.get('fee', 0.001))
            )

            # Notifica clientes SSE
            sse_manager.publish('mempool_updated', {
                'pending': len(app.blockchain.pending_transactions),
                'new_tx_index': index
            })

            return jsonify({
                'message': f'Transação adicionada. Será minerada no bloco #{index}',
                'transaction_index': index,
                'transaction_id': None  # Será definido pelo bloco
            }), 201

        except ValueError as e:
            # B-03: Mensagens de erro genéricas em 4xx (não expõe detalhes internos)
            return jsonify({'error': 'Requisição inválida. Verifique os dados fornecidos.'}), 400
        except Exception:
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @app.route('/wallet/new', methods=['POST'])
    @rate_limit
    def new_wallet():
        """
        Gera uma nova carteira.

        ATENÇÃO (Ambiente de Desenvolvimento):
        - A chave privada é retornada APENAS para facilitar o desenvolvimento
          e aprendizado com o frontend.
        - Em produção, a chave privada NUNCA deve sair do cliente.
          A assinatura deve ser feita exclusivamente no navegador.
        - Guarde a chave privada com segurança!
        """
        wallet = Wallet()
        print(f"[KEY] NOVA CARTEIRA CRIADA: {wallet.address}")
        # NUNCA logar chave privada — vulnerabilidade de segurança (A-03)

        # ─── Retorna dados públicos da carteira ─────────────────
        # A chave privada NUNCA deve ser transmitida pela rede (C-01).
        # Em produção, a assinatura é feita exclusivamente no cliente.
        data = wallet.export_public()
        
        if _is_production_mode():
            data['warning'] = 'Guarde sua chave privada com segurança! Ela não pode ser recuperada.'
        else:
            # DEV ONLY: retorna chave privada para testes locais
            data['private_key_pem'] = wallet.private_key_pem
            data['warning'] = 'DEV MODE: Chave privada retornada apenas para desenvolvimento.'
        
        return jsonify(data), 200

    @app.route('/balance/<address>', methods=['GET'])
    def get_balance(address: str):
        """
        Retorna o saldo de um endereço.

        Query params:
            history: 'true' para retornar histórico (default: false)
            limit: Número de transações no histórico (default: 20, max: 100)

        SEGURANÇA (M-03): Histórico detalhado só retorna com ?history=true
        para evitar vazamento de metad financeiros por padrão.
        """
        balance = app.blockchain.get_balance(address)
        
        # Por padrão, NÃO retorna histórico (proteção de privacidade)
        include_history = request.args.get('history', 'false').lower() == 'true'
        limit = min(request.args.get('limit', 20, type=int), 100)
        
        result = {
            'address': address,
            'balance': balance,
        }
        
        if include_history:
            transactions = app.blockchain.get_transaction_history(address)
            result['transactions_count'] = len(transactions)
            result['transactions'] = transactions[-limit:]
        
        return jsonify(result), 200

    @app.route('/nodes/register', methods=['POST'])
    @rate_limit
    @rate_limit_peer
    @require_p2p_nonce
    @_require_p2p_auth
    def register_nodes():
        """
        Registra nós vizinhos na rede.

        Body (JSON):
        {
            "nodes": ["http://localhost:5001", "http://localhost:5002"]
        }
        """
        data = request.get_json()

        if not data or 'nodes' not in data:
            return jsonify({
                'error': 'Forneça uma lista de "nodes" no body'
            }), 400

        nodes = data['nodes']
        registered = []
        duplicates = []
        invalid = []

        # ─── Validação anti-SSRF ──────────────────────────────
        # Bloqueia URLs que apontam para serviços internos,
        # impedindo ataques de Server-Side Request Forgery.
        import urllib.parse

        for node_url in nodes:
            # Valida URL
            if not node_url.startswith('http'):
                invalid.append(node_url)
                continue

            # Parseia a URL para verificar o host
            try:
                parsed = urllib.parse.urlparse(node_url)
                hostname = parsed.hostname or ''
            except Exception:
                invalid.append(node_url)
                continue

            # Bloqueia IPs privados (SSRF protection)
            # Cobre: loopback, link-local, CGNAT, RFC1918, benchmark
            import socket
            blocked_prefixes = (
                '127.', '10.', '192.168.', '172.16.', '172.17.',
                '172.18.', '172.19.', '172.20.', '172.21.', '172.22.',
                '172.23.', '172.24.', '172.25.', '172.26.', '172.27.',
                '172.28.', '172.29.', '172.30.', '172.31.',
                '0.',                     # 0.0.0.0/8
                '169.254.',               # Link-local
                '198.18.', '198.19.',      # Benchmarking
                '100.64.', '100.65.',      # CGNAT
                '100.66.', '100.67.', '100.68.', '100.69.',
                '100.70.', '100.71.', '100.72.', '100.73.',
                '100.74.', '100.75.', '100.76.', '100.77.',
                '100.78.', '100.79.', '100.80.', '100.81.',
                '100.82.', '100.83.', '100.84.', '100.85.',
                '100.86.', '100.87.', '100.88.', '100.89.',
                '100.90.', '100.91.', '100.92.', '100.93.',
                '100.94.', '100.95.', '100.96.', '100.97.',
                '100.98.', '100.99.', '100.100.', '100.101.',
                '100.102.', '100.103.', '100.104.', '100.105.',
                '100.106.', '100.107.', '100.108.', '100.109.',
                '100.110.', '100.111.', '100.112.', '100.113.',
                '100.114.', '100.115.', '100.116.', '100.117.',
                '100.118.', '100.119.', '100.120.', '100.121.',
                '100.122.', '100.123.', '100.124.', '100.125.',
                '100.126.', '100.127.',
            )
            blocked_hosts = ('localhost', '127.0.0.1', '::1', '0.0.0.0')

            if hostname.lower() in blocked_hosts:
                invalid.append(f"{node_url} (host local bloqueado por segurança)")
                continue

            if any(hostname.startswith(p) for p in blocked_prefixes):
                invalid.append(f"{node_url} (IP privado bloqueado por segurança)")
                continue

            # Verifica se o hostname resolve para IP privado
            # Impede bypass via DNS que resolve para IP interno
            try:
                resolved_ips = socket.getaddrinfo(hostname, None)
                for addr_info in resolved_ips:
                    ip = addr_info[4][0]
                    if any(ip.startswith(p) for p in blocked_prefixes):
                        invalid.append(
                            f"{node_url} (DNS resolve para IP privado: {ip})"
                        )
                        break
                    if ip in blocked_hosts:
                        invalid.append(
                            f"{node_url} (DNS resolve para host local: {ip})"
                        )
                        break
            except socket.gaierror:
                invalid.append(f"{node_url} (DNS não resolve)")
                continue

            # Verifica duplicata
            if _is_node_registered(node_url):
                duplicates.append(node_url)
                continue

            # ─── DNS Rebinding Protection ─────────────────────────
            # Armazena o IP resolvido no momento do registro.
            # Em requisições futuras, re-valida o IP para prevenir
            # DNS rebinding (atacante muda DNS após registro).
            resolved_ip = None
            try:
                # Resolve o IP do hostname novamente para confirmar
                current_ips = socket.getaddrinfo(hostname, None)
                for addr_info in current_ips:
                    ip = addr_info[4][0]
                    if not any(ip.startswith(p) for p in blocked_prefixes):
                        resolved_ip = ip
                        break
            except socket.gaierror:
                pass

            app.nodes[node_url] = {
                'url': node_url,
                'node_id': data.get('node_id', ''),
                'hostname': hostname,
                'resolved_ip': resolved_ip or ip,
                'registered_at': time.time(),
                'last_seen': time.time()
            }
            registered.append(node_url)

        return jsonify({
            'message': f'{len(registered)} nó(s) registrado(s)',
            'total_nodes': len(app.nodes),
            'registered': registered,
            'duplicates': duplicates,
            'invalid': invalid
        }), 201

    @app.route('/nodes/resolve', methods=['POST'])
    @rate_limit
    @rate_limit_peer
    @require_p2p_nonce
    @_require_p2p_auth
    def consensus():
        """
        Executa o algoritmo de consenso.
        Consulta todos os nós vizinhos e substitui a cadeia local
        pela mais longa e válida.

        SEGURANÇA:
        - Requer autenticação P2P (HMAC-SHA256)
        - Rate limited para prevenir DoS e SSRF amplification
        - Método POST (REST correto para operação com side effects)
        """
        replaced = False
        other_chains = []

        # Coleta as cadeias de todos os nós vizinhos
        for node in _get_node_urls():
            # ─── Anti-DNS Rebinding ────────────────────────────
            # Re-resolve o hostname e compara com o IP registrado.
            # Se o DNS mudou, rejeita a requisição.
            if not _validate_node_dns(node, app.nodes.get(node)):
                print(f"   [WARN] Nó {node}: DNS rebinding detectado. Ignorado.")
                continue

            try:
                response = _verified_request('GET', f'{node}/chain')
                if response.status_code == 200:
                    chain_data = response.json().get('chain', [])
                    other_chains.append(chain_data)
                    print(f"   Nó {node}: {len(chain_data)} blocos")
                    # Atualiza last_seen
                    if node in app.nodes:
                        app.nodes[node]['last_seen'] = time.time()
            except requests.exceptions.RequestException as e:
                print(f"   [WARN] Nó {node} não respondeu: {e}")

        # Executa o consenso
        replaced = app.blockchain.resolve_conflicts(other_chains)

        return jsonify({
            'message': 'Cadeia substituída' if replaced else 'Cadeia mantida',
            'chain_length': len(app.blockchain.chain),
            'nodes_consulted': len(other_chains),
            'total_nodes': len(app.nodes),
            'replaced': replaced
        }), 200

    @app.route('/validate', methods=['GET'])
    def validate():
        """
        Valida a integridade de toda a blockchain.
        Verifica hashes, ligações e transações de todos os blocos.
        """
        is_valid = app.blockchain.is_chain_valid()

        # Informações detalhadas
        issues = []
        if not is_valid:
            for i, block in enumerate(app.blockchain.chain):
                if block.hash != block.calculate_hash():
                    issues.append({
                        'block': i,
                        'issue': 'hash_mismatch',
                        'expected': block.calculate_hash(),
                        'actual': block.hash
                    })

        return jsonify({
            'valid': is_valid,
            'blocks': len(app.blockchain.chain),
            'issues': issues if issues else None
        }), 200

    @app.route('/stats', methods=['GET'])
    def stats():
        """
        Retorna estatísticas da blockchain.
        Útil para monitoramento e debug.
        """
        total_tx = sum(
            len(block.transactions) for block in app.blockchain.chain
        )
        supply = app.blockchain.get_supply_info()
        return jsonify({
            'blocks': len(app.blockchain.chain),
            'total_transactions': total_tx,
            'pending_transactions': len(app.blockchain.pending_transactions),
            'difficulty': app.blockchain.difficulty,
            'reward': app.blockchain.reward,
            'node_id': app.blockchain.node_id,
            'miner_address': app.node_wallet_address,
            'peer_nodes': _get_node_urls(),
            'genesis_hash': app.blockchain.chain[0].hash if app.blockchain.chain else None,
            'last_block_hash': app.blockchain.last_block.hash if app.blockchain.last_block else None,
            'chain_valid': app.blockchain.is_chain_valid(),
            'total_supply': supply['total_supply'],
            'supply_cap': supply['supply_cap'],
            'remaining_supply': supply['remaining_supply'],
            'percent_mined': supply['percent_mined'],
            'token_name': supply['token_name'],
            'token_symbol': supply['token_symbol']
        }), 200

    @app.route('/api/supply', methods=['GET'])
    def supply():
        """
        Retorna informações detalhadas sobre o supply do token.
        Inclui: total minerado, supply cap, restante, percentual.
        """
        from config import TOTAL_SUPPLY_CAP, INITIAL_BLOCK_REWARD, HALVING_INTERVAL
        info = app.blockchain.get_supply_info()
        info['initial_reward'] = INITIAL_BLOCK_REWARD
        info['halving_interval'] = HALVING_INTERVAL
        current_reward = app.blockchain.get_block_reward(
            len(app.blockchain.chain)
        )
        info['current_block_reward'] = current_reward
        return jsonify(info), 200

    @app.route('/transactions/pending', methods=['GET'])
    def pending_transactions():
        """Retorna as transações pendentes (mempool)."""
        return jsonify({
            'count': len(app.blockchain.pending_transactions),
            'transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ]
        }), 200

    # ─── Endpoints de Rede (P2P) ───────────────────────────────────

    @app.route('/blocks/new', methods=['POST'])
    @rate_limit
    @rate_limit_peer
    @require_p2p_nonce
    @_require_p2p_auth
    def receive_block():
        """
        Recebe um bloco minerado por outro nó.

        Validações:
        1. Autenticação P2P (X-Kurama-Auth + HMAC)
        2. Nonce anti-replay (X-Kurama-Nonce)
        3. Assinatura ECDSA do payload (obrigatória)
        3. Estrutura do bloco
        4. Integridade na cadeia local

        Body (JSON): bloco em formato dict (Block.to_dict())
        """
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Dados do bloco não fornecidos'}), 400

        # ─── AEAD Decryption (AES-256-GCM) ──────────────────────
        # Descriptografa payload P2P se veio criptografado.
        # Segunda camada de segurança além do TLS.
        from config import P2P_ENCRYPTION, NETWORK_SECRET
        if P2P_ENCRYPTION and data.get('_encrypted'):
            try:
                import hashlib
                from core.crypto_utils import CryptoUtils
                enc_key = hashlib.sha256(
                    NETWORK_SECRET.encode('utf-8')
                ).digest()
                ciphertext = base64.b64decode(data['_ciphertext'])
                enc_nonce = base64.b64decode(data['_nonce'])
                # AAD = URL da requisição (mesmo usado na criptografia)
                aad = request.url.encode('utf-8')
                plaintext = CryptoUtils.aes256gcm_decrypt(
                    enc_key, enc_nonce, ciphertext, aad
                )
                data = json.loads(plaintext.decode('utf-8'))
            except Exception as e:
                return jsonify({
                    'error': 'Falha na descriptografia P2P (AES-256-GCM). '
                             'Payload adulterado ou chave incorreta.'
                }), 401

        # ─── Verificação de Assinatura ECDSA P2P (OBRIGATÓRIA) ─
        # P2P_REQUIRE_SIGNATURE=True: toda mensagem P2P DEVE ser assinada.
        # A assinatura prova que o remetente é dono da chave privada
        # correspondente à chave pública fornecida (não-repúdio).
        from config import P2P_REQUIRE_SIGNATURE as _SIG_REQUIRED
        p2p_sig = request.headers.get(P2P_SIGNATURE_HEADER)
        p2p_pubkey = request.headers.get(P2P_PUBKEY_HEADER)

        if _SIG_REQUIRED and (not p2p_sig or not p2p_pubkey):
            return jsonify({
                'error': 'Assinatura ECDSA P2P obrigatória. '
                         'Forneça X-Kurama-Signature e X-Kurama-Public-Key.'
            }), 401

        if p2p_sig and p2p_pubkey:
            if not CryptoUtils.verify_p2p_signature(data, p2p_sig, p2p_pubkey):
                peer_score_manager.record_event(
                    p2p_pubkey[:32], 'invalid_signature'
                )
                return jsonify({
                    'error': 'Assinatura ECDSA P2P inválida.'
                }), 401
            peer_score_manager.record_event(
                p2p_pubkey[:32], 'valid_block'
            )

        try:
            # O nó pode enviar {'block': {...}} ou o dict diretamente
            block_data = data.get('block', data)
            from core.block import Block
            block = Block.from_dict(block_data, Transaction)

            # Verifica se o bloco já existe
            if block.index < len(app.blockchain.chain):
                existing = app.blockchain.chain[block.index]
                if existing.hash == block.hash:
                    return jsonify({'message': 'Bloco já existe', 'status': 'duplicate'}), 200

            # Valida o bloco
            # 1. Verifica se encaixa na cadeia local
            if block.index != len(app.blockchain.chain):
                return jsonify({
                    'error': 'Bloco não encaixa na cadeia local'
                }), 409

            # 2. Verifica previous_hash
            last_block = app.blockchain.last_block
            if last_block and block.previous_hash != last_block.hash:
                return jsonify({
                    'error': 'Bloco não encaixa na cadeia local'
                }), 409

            # 3. Verifica o hash do bloco
            if block.hash != block.calculate_hash():
                return jsonify({'error': 'Hash do bloco inválido'}), 400

            # 4. Verifica Proof of Work
            block_dict = block.to_dict()
            block_hash = CryptoUtils.hash_block(block_dict)
            block_difficulty = block.difficulty or app.blockchain.difficulty
            if not CryptoUtils.is_hash_valid(block_hash, block_difficulty):
                return jsonify({'error': 'Proof of Work inválido'}), 400

            # 5. Verifica transações
            if not block.is_valid_transactions():
                return jsonify({'error': 'Transações do bloco inválidas'}), 400

            # Adiciona o bloco à cadeia
            app.blockchain.chain.append(block)

            # Remove transações do bloco da mempool local
            block_tx_ids = {tx.transaction_id for tx in block.transactions}
            app.blockchain.pending_transactions = [
                tx for tx in app.blockchain.pending_transactions
                if tx.transaction_id not in block_tx_ids
            ]

            # Ajusta dificuldade
            app.blockchain.adjust_difficulty()

            return jsonify({
                'message': 'Bloco recebido e adicionado à cadeia local',
                'block_index': block.index,
                'block_hash': block.hash,
                'chain_length': len(app.blockchain.chain)
            }), 201

        except ValueError:
            return jsonify({'error': 'Bloco inválido'}), 400
        except Exception:
            return jsonify({'error': 'Erro interno do servidor'}), 500

    # ═══════════════════════════════════════════════════════════════
    # ENDPOINTS DO EXPLORER (/api/*)
    # ═══════════════════════════════════════════════════════════════

    @app.route('/api/health', methods=['GET'])
    def api_health():
        """Health check para nós e frontend."""
        return jsonify({
            'status': 'ok',
            'node_id': app.blockchain.node_id,
            'blocks': len(app.blockchain.chain),
            'peer_count': len(app.nodes)
        }), 200

    @app.route('/api/chain/since/<int:index>', methods=['GET'])
    def api_chain_since(index: int):
        """
        Retorna blocos a partir do índice especificado.
        Útil para sincronização incremental do frontend.
        """
        blocks = []
        for block in app.blockchain.chain:
            if block.index > index:
                blocks.append(block.to_dict())
        return jsonify({
            'blocks': blocks,
            'count': len(blocks),
            'tip': len(app.blockchain.chain) - 1
        }), 200

    @app.route('/api/blocks/<identifier>', methods=['GET'])
    def api_block_by_id(identifier: str):
        """
        Retorna um bloco por índice numérico ou hash hexadecimal.
        Detecta automaticamente se é index ou hash.
        """
        # Tenta como índice numérico
        if identifier.isdigit():
            idx = int(identifier)
            if 0 <= idx < len(app.blockchain.chain):
                block = app.blockchain.chain[idx]
                return jsonify(block.to_dict()), 200
            return jsonify({'error': 'Bloco não encontrado', 'identifier': identifier}), 404

        # Tenta como hash (64 caracteres hex)
        if len(identifier) == 64:
            for block in app.blockchain.chain:
                if block.hash == identifier:
                    return jsonify(block.to_dict()), 200
            return jsonify({'error': 'Hash não encontrado', 'identifier': identifier}), 404

        return jsonify({'error': 'Identificador inválido. Use um número de índice ou hash de 64 caracteres.'}), 400

    @app.route('/api/transactions', methods=['GET'])
    def api_transactions():
        """
        Retorna todas as transações com paginação e filtros.

        Query params:
            page: Número da página (default: 1)
            per_page: Itens por página (default: 20)
            address: Filtrar por endereço
            min_amount: Valor mínimo
            max_amount: Valor máximo
        """
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        address = request.args.get('address', None, type=str)
        min_amount = request.args.get('min_amount', None, type=float)
        max_amount = request.args.get('max_amount', None, type=float)

        # Coleciona todas as transações com info do bloco
        all_txs = []
        for block in app.blockchain.chain:
            for tx in block.transactions:
                tx_dict = tx.to_dict() if hasattr(tx, 'to_dict') else tx
                tx_dict['block_index'] = block.index
                tx_dict['confirmed'] = True
                all_txs.append(tx_dict)

        # Aplica filtros
        if address:
            all_txs = [
                tx for tx in all_txs
                if tx.get('sender') == address
                or tx.get('receiver') == address
                or tx.get('sender_address') == address
            ]
        if min_amount is not None:
            all_txs = [tx for tx in all_txs if tx.get('amount', 0) >= min_amount]
        if max_amount is not None:
            all_txs = [tx for tx in all_txs if tx.get('amount', 0) <= max_amount]

        # Paginação
        total = len(all_txs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_txs = all_txs[start:end]

        return jsonify({
            'transactions': page_txs,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }), 200

    @app.route('/api/search', methods=['GET'])
    def api_search():
        """
        Busca unificada.
        Detecta se o termo é índice, hash ou endereço.

        Query params:
            q: Termo de busca
        """
        query = request.args.get('q', '').strip()

        if not query:
            return jsonify({'error': 'Forneça um termo de busca em ?q='}), 400

        # Tenta como índice de bloco
        if query.isdigit():
            idx = int(query)
            if 0 <= idx < len(app.blockchain.chain):
                return jsonify({
                    'type': 'block',
                    'data': app.blockchain.chain[idx].to_dict(),
                    'url': f'/explorer/{idx}'
                }), 200

        # Tenta como hash de bloco (64 hex chars)
        if len(query) == 64:
            for block in app.blockchain.chain:
                if block.hash == query:
                    return jsonify({
                        'type': 'block',
                        'data': block.to_dict(),
                        'url': f'/explorer/{block.index}'
                    }), 200

        # Tenta como endereço de carteira
        balance = app.blockchain.get_balance(query)
        if len(query) > 20:  # Endereços Base58 têm mais de 20 chars
            return jsonify({
                'type': 'address',
                'data': {
                    'address': query,
                    'balance': balance
                },
                'url': f'/wallet/{query}'
            }), 200

        return jsonify({'error': 'Nenhum resultado encontrado', 'query': query}), 404

    @app.route('/api/nodes', methods=['GET'])
    def api_nodes():
        """
        Lista todos os nós registrados com status de saúde.
        Pinga cada nó e retorna latência e status.
        """
        from config import NODE_HEALTH_TIMEOUT

        nodes_list = []

        # Adiciona o próprio nó
        nodes_list.append({
            'url': f'http://localhost:{port}',
            'active': True,
            'blocks': len(app.blockchain.chain),
            'node_id': app.blockchain.node_id,
            'latency_ms': 0,
            'is_self': True
        })

        # Verifica saúde dos nós vizinhos
        for node_url in _get_node_urls():
            # Anti-DNS rebinding
            if not _validate_node_dns(node_url, app.nodes.get(node_url)):
                continue
            try:
                start = time.time()
                resp = _verified_request('GET', f'{node_url}/api/health',
                                         timeout=NODE_HEALTH_TIMEOUT)
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    nodes_list.append({
                        'url': node_url,
                        'active': True,
                        'blocks': data.get('blocks', 0),
                        'node_id': data.get('node_id', 'unknown'),
                        'latency_ms': latency,
                        'is_self': False
                    })
                else:
                    nodes_list.append({
                        'url': node_url,
                        'active': False,
                        'blocks': 0,
                        'node_id': 'unknown',
                        'latency_ms': None,
                        'is_self': False
                    })
            except requests.exceptions.RequestException:
                nodes_list.append({
                    'url': node_url,
                    'active': False,
                    'blocks': 0,
                    'node_id': 'unknown',
                    'latency_ms': None,
                    'is_self': False
                })

        return jsonify({
            'nodes': nodes_list,
            'total': len(nodes_list),
            'active': sum(1 for n in nodes_list if n['active'])
        }), 200

    # ─── Peer Discovery Endpoint ───────────────────────────────────
    # Retorna lista de peers conhecidos para bootstrap na rede.
    @app.route('/api/peers', methods=['GET'])
    @rate_limit
    def api_peers():
        """Retorna lista de peers conhecidos (para descoberta de rede)."""
        from config import SEED_NODES
        peers = []
        for url in _get_node_urls():
            node_info = app.nodes.get(url, {})
            peers.append({
                'url': url,
                'node_id': node_info.get('node_id', ''),
                'hostname': node_info.get('hostname', ''),
                'registered_at': node_info.get('registered_at', 0),
                'last_seen': node_info.get('last_seen', 0)
            })
        return jsonify({
            'peers': peers,
            'total': len(peers),
            'seed_nodes': SEED_NODES
        }), 200

    @app.route('/api/nodes/sync', methods=['POST'])
    @rate_limit
    @rate_limit_peer
    @require_p2p_nonce
    @_require_p2p_auth
    def api_nodes_sync():
        """
        Executa consenso contra todos os nós vizinhos.
        Substitui a cadeia local pela mais longa e válida.

        SEGURANÇA:
        - Requer autenticação P2P (HMAC-SHA256)
        - Rate limited para prevenir SSRF amplification
        """
        other_chains = []
        results = []

        for node_url in _get_node_urls():
            # Anti-DNS rebinding
            if not _validate_node_dns(node_url, app.nodes.get(node_url)):
                results.append({
                    'node': node_url,
                    'blocks': 0,
                    'status': 'dns_rebinding_detected'
                })
                continue
            try:
                resp = _verified_request('GET', f'{node_url}/chain')
                if resp.status_code == 200:
                    chain_data = resp.json().get('chain', [])
                    other_chains.append(chain_data)
                    results.append({
                        'node': node_url,
                        'blocks': len(chain_data),
                        'status': 'ok'
                    })
                else:
                    results.append({
                        'node': node_url,
                        'blocks': 0,
                        'status': 'error'
                    })
            except requests.exceptions.RequestException as e:
                results.append({
                    'node': node_url,
                    'blocks': 0,
                    'status': f'failed: {str(e)[:50]}'
                })

        replaced = app.blockchain.resolve_conflicts(other_chains)

        return jsonify({
            'message': 'Cadeia substituída' if replaced else 'Cadeia mantida',
            'chain_length': len(app.blockchain.chain),
            'nodes_consulted': len(other_chains),
            'replaced': replaced,
            'results': results
        }), 200

    @app.route('/api/chart', methods=['GET'])
    def api_chart():
        """
        Retorna dados formatados para o gráfico do Dashboard.
        Inclui blocos recentes com contagem de transações,
        transações acumuladas e dificuldade.

        Query params:
            limit: Número de blocos a retornar (default: 50)
        """
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 200)  # Máximo 200 blocos

        chain = app.blockchain.chain
        start = max(0, len(chain) - limit)
        chart_data = []
        cum_tx = 0

        for block in chain[start:]:
            tx_count = len(block.transactions)
            cum_tx += tx_count
            chart_data.append({
                'block': block.index,
                'timestamp': block.timestamp,
                'transactions': tx_count,
                'cumulativeTx': cum_tx,
                'difficulty': block.difficulty or 0,
            })

        return jsonify(chart_data), 200

    @app.route('/api/mempool', methods=['GET'])
    def api_mempool():
        """
        Retorna estatísticas detalhadas da mempool.
        """
        stats = app.blockchain.get_mempool_stats()
        return jsonify({
            **stats,
            'transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ]
        }), 200

    # ═══════════════════════════════════════════════════════════════
    # SERVER-SENT EVENTS (tempo real sem polling)
    # ═══════════════════════════════════════════════════════════════
    # Usa SSE em vez de WebSocket para simplificar: nao requer
    # bibliotecas extras, funciona com HTTP padrao, auto-reconnect
    # nativo no navegador via EventSource API.

    # ─── SSE Connection Limit (Anti-DoS) ──────────────────────
    # Limita conexões SSE simultâneas para prevenir exaustão
    # de threads/memória (A-02 parcial).
    SSE_MAX_CONNECTIONS = 50

    @app.route('/api/events', methods=['GET'])
    def api_events():
        """
        Server-Sent Events (SSE) para atualizações em tempo real.

        O frontend se conecta a este endpoint via EventSource.
        Eventos:
        - **chain_updated**: blockchain mudou (novo bloco minerado)
        - **mempool_updated**: transação adicionada/removida da mempool
        - **ping**: keepalive a cada 30s

        Uso (frontend):
            const source = new EventSource('/api/events');
            source.addEventListener('chain_updated', (e) => {
                const data = JSON.parse(e.data);
                refreshChain();
            });
        """
        # Verifica limite de conexões SSE
        if sse_manager.subscriber_count >= SSE_MAX_CONNECTIONS:
            return jsonify({
                'error': 'Limite de conexões SSE atingido. Reconecte mais tarde.',
                'code': 'SSE_LIMIT_REACHED'
            }), 429

        def event_stream():
            q = sse_manager.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=30)
                        event_type = msg.get('event', 'message')
                        data = msg.get('data', {})
                        yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                    except queue.Empty:
                        # Keepalive a cada 30s
                        yield f": keepalive\n\n"
            except GeneratorExit:
                pass
            finally:
                sse_manager.unsubscribe(q)

        return Response(
            stream_with_context(event_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            }
        )

    # ═══════════════════════════════════════════════════════════════
    # ENDPOINTS DE AÇÃO (Frontend)
    # ═══════════════════════════════════════════════════════════════

    @app.route('/api/transactions/create-signed', methods=['POST'])
    @rate_limit
    def create_signed_transaction():
        """
        Cria uma transação ASSINADA a partir de uma chave privada.

        Este endpoint é usado pelo frontend para criar transações
        sem necessidade de bibliotecas criptográficas no navegador.
        A chave privada é enviada por HTTPS (dev) e usada apenas
        para assinar — NUNCA é armazenada no servidor.

        ATENÇÃO (Dev only):
        - Em produção, a assinatura DEVE ser feita no cliente.
        - A chave privada NUNCA deve trafegar pela rede em produção.

        Body (JSON):
        {
            "private_key_pem": "<chave privada PEM>",
            "receiver": "<endereço do destinatário>",
            "amount": 10.0,
            "fee": 0.001              # Opcional (default: 0.001)
        }

        Returns:
            Dados da transação criada ou erro
        """
        data = request.get_json()

        required = ['private_key_pem', 'receiver', 'amount']
        if not data or not all(k in data for k in required):
            missing = [k for k in required if k not in (data or {})]
            return jsonify({
                'error': 'Campos obrigatórios ausentes',
                'required': required,
                'missing': missing
            }), 400

        # ─── PROTEÇÃO: Desabilitar em produção ──────────────────
        # Em produção, a assinatura DEVE ser feita no cliente.
        # Este endpoint existe apenas para desenvolvimento/testes.
        if _is_production_mode():
            return jsonify({
                'error': 'Este endpoint está desabilitado em produção. '
                         'As transações devem ser assinadas no cliente.',
                'code': 'PROD_SIGN_DISABLED'
            }), 403
        
        try:
            # Reconstrói a wallet a partir da chave privada
            wallet = Wallet(private_key_pem=data['private_key_pem'])

            receiver = data['receiver']
            amount = float(data['amount'])
            fee = float(data.get('fee', 0.001))

            # Cria e assina a transação
            tx = Transaction(
                sender=wallet.public_key_pem,
                receiver=receiver,
                amount=amount,
                fee=fee,
                sender_address=wallet.address
            )
            tx.sign(wallet.private_key_pem)

            # Adiciona à mempool via blockchain.add_transaction
            # Passa o transaction_id pré-gerado para que a assinatura
            # (que cobre o transaction_id) seja verificada corretamente.
            index = app.blockchain.add_transaction(
                sender=tx.sender,
                receiver=tx.receiver,
                amount=tx.amount,
                signature=tx.signature,
                sender_address=tx.sender_address,
                timestamp=tx.timestamp,
                fee=tx.fee,
                transaction_id=tx.transaction_id
            )

            return jsonify({
                'message': f'Transação criada e assinada! Será minerada no bloco #{index}',
                'transaction': tx.to_dict(),
                'transaction_index': index,
                'sender_address': wallet.address,
                'sender_balance': app.blockchain.get_balance(wallet.address)
            }), 201

        except ValueError:
            return jsonify({'error': 'Transação inválida'}), 400
        except Exception:
            return jsonify({'error': 'Erro interno do servidor'}), 500

    return app
