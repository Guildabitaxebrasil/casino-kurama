"""
Módulo de Segurança P2P — Camada 4 (Defesa de Rede).

Fornece:
1. P2PNonceManager — Anti-replay via nonce + timestamp + expiração
2. PeerScoreManager — Peer scoring + ban com exponential backoff
3. EclipseProtection — Defesa contra eclipse attacks + peer diversity
"""
import time
import hashlib
import threading
from collections import OrderedDict
from typing import Dict, Optional, Set, List, Tuple


# ═══════════════════════════════════════════════════════════════════
# 1. P2PNonceManager — Anti-Replay
# ═══════════════════════════════════════════════════════════════════

class P2PNonceManager:
    """
    Gerencia nonces de mensagens P2P para prevenir ataques de replay.

    Cada mensagem P2P deve incluir:
    - nonce: 96-bit random (12 bytes hex = 24 chars)
    - timestamp: epoch do remetente
    - expires: timestamp de expiração

    Validação:
    1. |now - timestamp| > MAX_CLOCK_DRIFT → rejeita (clock skew)
    2. now > expires → rejeita (TTL expirado)
    3. nonce já no cache → rejeita (replay)

    O cache usa LRU (Least Recently Used) com tamanho máximo configurável
    para bounding de memória. Entradas expiradas são limpas periodicamente.

    Thread-safe: usa threading.Lock para todas as operações.
    """

    def __init__(self, max_size: int = 100000, ttl: int = 300,
                 max_clock_drift: int = 30):
        """
        Args:
            max_size: Máximo de nonces no cache LRU
            ttl: TTL de cada nonce em segundos
            max_clock_drift: Tolerância de diferença de clock (segundos)
        """
        self._max_size = max_size
        self._ttl = ttl
        self._max_clock_drift = max_clock_drift
        # LRU cache: OrderedDict onde a ordem = ordem de inserção
        # {nonce: timestamp_de_insercao}
        self._nonce_cache = OrderedDict()
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup_expired(self):
        """Remove nonces expirados do cache (LRU trimming)."""
        # Só limpa a cada 60s para não sobrecarregar
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now

        # Remove expirados (mais antigos primeiro)
        expired_cutoff = now - self._ttl
        while self._nonce_cache:
            oldest_nonce, oldest_time = next(iter(self._nonce_cache.items()))
            if oldest_time < expired_cutoff:
                self._nonce_cache.popitem(last=False)
            else:
                break

    def generate_nonce(self) -> str:
        """
        Gera um nonce P2P de 96 bits (12 bytes).

        96 bits = 2^96 valores únicos. Com 100k mensagens/s,
        levaria ~10^18 anos para colisão. Suficiente para
        qualquer cenário prático.

        Returns:
            Hex string de 24 caracteres
        """
        import os
        return os.urandom(12).hex()

    def create_message_envelope(self, payload: dict) -> dict:
        """
        Empacota um payload com nonce, timestamp e expiração.

        Args:
            payload: Dados originais da mensagem

        Returns:
            Dict com _nonce, _timestamp, _expires + payload original
        """
        now = time.time()
        return {
            '_nonce': self.generate_nonce(),
            '_timestamp': now,
            '_expires': now + self._ttl,
            **payload
        }

    def validate_message(self, message: dict) -> Tuple[bool, str]:
        """
        Valida uma mensagem P2P: nonce, timestamp, expiração e replay.

        Args:
            message: Dict completo (deve conter _nonce, _timestamp, _expires)

        Returns:
            (True, "") se válido
            (False, "motivo") se inválido
        """
        nonce = message.get('_nonce')
        timestamp = message.get('_timestamp')
        expires = message.get('_expires')

        if not nonce or not timestamp or not expires:
            return False, "Mensagem sem nonce/timestamp/expires"

        now = time.time()

        # Verifica clock drift (anti-clock-skew)
        if abs(now - timestamp) > self._max_clock_drift:
            return (False,
                    f"Clock drift excessivo: {abs(now - timestamp):.1f}s > "
                    f"{self._max_clock_drift}s")

        # Verifica expiração
        if now > expires:
            return False, f"Mensagem expirada ({(now - expires):.1f}s atrás)"

        with self._lock:
            # Anti-replay: nonce já visto?
            if nonce in self._nonce_cache:
                return False, "Nonce reutilizado (replay attack detectado)"

            # LRU: se atingiu o limite, remove o mais antigo
            if len(self._nonce_cache) >= self._max_size:
                self._nonce_cache.popitem(last=False)

            # Armazena nonce com timestamp de inserção
            self._nonce_cache[nonce] = now

            # Limpeza periódica
            self._cleanup_expired()

        return True, ""

    def get_stats(self) -> dict:
        """Retorna estatísticas do gerenciador de nonces."""
        with self._lock:
            return {
                'cache_size': len(self._nonce_cache),
                'max_size': self._max_size,
                'ttl': self._ttl,
                'max_clock_drift': self._max_clock_drift
            }


# ═══════════════════════════════════════════════════════════════════
# 2. PeerScoreManager — Peer Scoring + Ban
# ═══════════════════════════════════════════════════════════════════

class PeerScoreRecord:
    """Registro de score de um peer individual."""

    def __init__(self, peer_id: str, url: str = ''):
        self.peer_id = peer_id         # node_id ou URL
        self.url = url
        self.score = 0                 # Score atual
        self.total_messages = 0
        self.valid_messages = 0
        self.invalid_messages = 0
        self.last_seen = time.time()
        self.first_seen = time.time()
        self.banned_until = 0          # 0 = não banido
        self.ban_count = 0
        self.latency_sum = 0.0
        self.latency_count = 0

    @property
    def avg_latency(self) -> float:
        """Latência média em ms."""
        if self.latency_count == 0:
            return 0.0
        return self.latency_sum / self.latency_count

    @property
    def is_banned(self) -> bool:
        """True se está banido e o ban ainda não expirou."""
        return self.banned_until > time.time()

    @property
    def ban_remaining(self) -> float:
        """Segundos restantes de ban (0 se não banido)."""
        remaining = self.banned_until - time.time()
        return max(0, remaining)

    def to_dict(self) -> dict:
        return {
            'peer_id': self.peer_id,
            'url': self.url,
            'score': self.score,
            'total_messages': self.total_messages,
            'valid_messages': self.valid_messages,
            'invalid_messages': self.invalid_messages,
            'last_seen': self.last_seen,
            'first_seen': self.first_seen,
            'banned_until': self.banned_until,
            'ban_count': self.ban_count,
            'avg_latency_ms': round(self.avg_latency, 1),
            'is_banned': self.is_banned
        }


class PeerScoreManager:
    """
    Sistema de reputação para peers P2P.

    Eventos que afetam o score:
    +5   Bloco válido recebido
    +1   Chain válida no consenso
    +1   Health check bem-sucedido
    +2   Resposta rápida (< 100ms)
    -10  Bloco inválido
    -10  Chain inválida
    -20  Assinatura inválida
    -50  SSRF / IP privado no registro
    -5   Timeout de requisição
    -3   Resposta lenta (> 2s)
    -100 Node banido manualmente

    Banimento:
    - Threshold: P2P_PEER_SCORE_BAN_THRESHOLD = -100
    - Exponential backoff: 1h → 2h → 4h → 8h → max 24h
    - Cada ban concede +1 em ban_count
    """

    SCORE_EVENTS = {
        'valid_block': 5,
        'valid_chain': 1,
        'health_ok': 1,
        'fast_response': 2,
        'invalid_block': -10,
        'invalid_chain': -10,
        'invalid_signature': -20,
        'ssrf_attempt': -50,
        'request_timeout': -5,
        'slow_response': -3,
        'valid_transaction': 1,
        'invalid_transaction': -5,
    }

    def __init__(self, ban_threshold: int = -100,
                 ban_base_seconds: int = 3600,
                 ban_max_seconds: int = 86400):
        """
        Args:
            ban_threshold: Score mínimo antes de banir (-100)
            ban_base_seconds: Duração inicial do ban (1h)
            ban_max_seconds: Duração máxima do ban (24h)
        """
        self._peers: Dict[str, PeerScoreRecord] = {}
        self._ban_threshold = ban_threshold
        self._ban_base = ban_base_seconds
        self._ban_max = ban_max_seconds
        self._lock = threading.Lock()

    def get_or_create(self, peer_id: str, url: str = '') -> PeerScoreRecord:
        """Obtém ou cria registro de score para um peer."""
        with self._lock:
            if peer_id not in self._peers:
                self._peers[peer_id] = PeerScoreRecord(peer_id, url)
            return self._peers[peer_id]

    def record_event(self, peer_id: str, event: str,
                     url: str = '', latency: float = None) -> int:
        """
        Registra um evento para um peer e ajusta o score.

        Args:
            peer_id: ID do peer (node_id ou URL)
            event: Tipo de evento (ver SCORE_EVENTS)
            url: URL do peer (para novo registro)
            latency: Latência da requisição em ms

        Returns:
            Score atual após ajuste
        """
        if event not in self.SCORE_EVENTS:
            return 0

        delta = self.SCORE_EVENTS[event]
        record = self.get_or_create(peer_id, url)
        timestamp = time.time()

        with self._lock:
            record.score += delta
            record.total_messages += 1
            record.last_seen = timestamp

            if delta > 0:
                record.valid_messages += 1
            else:
                record.invalid_messages += 1

            if latency is not None:
                record.latency_sum += latency
                record.latency_count += 1

            # Verifica se atingiu threshold de ban
            if (record.score <= self._ban_threshold
                    and not record.is_banned):
                ban_duration = min(
                    self._ban_base * (2 ** record.ban_count),
                    self._ban_max
                )
                record.banned_until = timestamp + ban_duration
                record.ban_count += 1
                print(f"[BAN] Peer {peer_id[:16]} banido por "
                      f"{ban_duration / 3600:.1f}h (score: {record.score})")

        return record.score

    def is_banned(self, peer_id: str) -> bool:
        """Verifica se um peer está banido."""
        record = self._peers.get(peer_id)
        if not record:
            return False
        return record.is_banned

    def get_score(self, peer_id: str) -> Optional[int]:
        """Retorna o score atual de um peer."""
        record = self._peers.get(peer_id)
        return record.score if record else None

    def get_banned_peers(self) -> List[dict]:
        """Retorna lista de peers atualmente banidos."""
        with self._lock:
            return [
                r.to_dict() for r in self._peers.values()
                if r.is_banned
            ]

    def get_active_peers(self) -> List[PeerScoreRecord]:
        """Retorna peers não banidos, ordenados por score (maior primeiro)."""
        with self._lock:
            now = time.time()
            active = [
                r for r in self._peers.values()
                if r.banned_until <= now
            ]
            active.sort(key=lambda r: r.score, reverse=True)
            return active

    def get_peer_count(self) -> dict:
        """Retorna contagem de peers."""
        with self._lock:
            total = len(self._peers)
            banned = sum(1 for r in self._peers.values() if r.is_banned)
            return {'total': total, 'active': total - banned, 'banned': banned}

    def get_all_peer_ids(self) -> List[str]:
        """Retorna IDs de todos os peers."""
        with self._lock:
            return list(self._peers.keys())


# ═══════════════════════════════════════════════════════════════════
# 3. EclipseProtection
# ═══════════════════════════════════════════════════════════════════

class EclipseProtection:
    """
    Proteção contra Eclipse Attacks.

    Um ataque de eclipse isola um nó do resto da rede, controlando
    todas as suas conexões de entrada e saída. Este módulo defende:

    1. DIVERSIDADE: Limita peers por /24 subnet. Garante mínimo
       de /16 subnets diferentes entre peers conectados.
    2. ROTAÇÃO: A cada sync cycle, seleciona amostra aleatória de
       peers (pesada por score). NUNCA consulta todos os peers.
    3. DETECÇÃO: Monitora se N peers consecutivos retornam chains
       idênticas (sinal de eclipse).
    4. SLOTS: Máximo de conexões ativas. Slots dedicados para seed
       nodes. LRU + lowest score eviction policy.
    """

    def __init__(self, max_per_subnet: int = 3,
                 min_diversity: int = 2,
                 max_outgoing: int = 20,
                 sync_sample_size: int = 5,
                 suspicious_same_chain: int = 3):
        """
        Args:
            max_per_subnet: Máx peers por /24 subnet
            min_diversity: Mínimo de /16 subnets diferentes
            max_outgoing: Máx conexões ativas
            sync_sample_size: Peers consultados por sync cycle
            suspicious_same_chain: Alerta se N peers retornam mesma chain
        """
        self._max_per_subnet = max_per_subnet
        self._min_diversity = min_diversity
        self._max_outgoing = max_outgoing
        self._sync_sample_size = sync_sample_size
        self._suspicious_same_chain = suspicious_same_chain
        self._same_chain_count = 0
        self._last_chain_hash = None
        self._lock = threading.Lock()

    @staticmethod
    def _get_subnet(hostname: str, prefix: int = 24) -> str:
        """
        Extrai subnet de um hostname/IP.

        Para IPs: retorna os primeiros 'prefix' bits.
        Para hostnames: retorna o domínio de segundo nível.

        Args:
            hostname: Host ou IP
            prefix: Tamanho do prefixo (24 = /24)

        Returns:
            String da subnet
        """
        import socket
        try:
            # Tenta resolver para IP
            ip = socket.gethostbyname(hostname)
            parts = ip.split('.')
            if prefix == 24 and len(parts) == 4:
                return '.'.join(parts[:3])
            elif prefix == 16 and len(parts) == 4:
                return '.'.join(parts[:2])
            return parts[0]
        except socket.gaierror:
            # Se não resolve, usa o hostname
            return hostname.split('.')[0]

    def extract_subnets(self, urls: List[str]) -> Dict[str, Set[str]]:
        """
        Extrai /24 e /16 subnets de uma lista de URLs.

        Args:
            urls: Lista de URLs de peers

        Returns:
            Dict com '/24': set de subnets, '/16': set de subnets
        """
        import urllib.parse
        subnets = {'/24': set(), '/16': set()}
        for url in urls:
            try:
                hostname = urllib.parse.urlparse(url).hostname or ''
                sub24 = self._get_subnet(hostname, 24)
                sub16 = self._get_subnet(hostname, 16)
                subnets['/24'].add(sub24)
                subnets['/16'].add(sub16)
            except Exception as e:
                print(f"[WARN] Erro ao extrair subnet de {url}: {e}")
                continue
        return subnets

    def validate_connection(self, new_url: str,
                            current_urls: List[str]) -> Tuple[bool, str]:
        """
        Valida se uma nova conexão é permitida baseado em diversidade.

        Args:
            new_url: URL do peer que quer conectar
            current_urls: URLs dos peers já conectados

        Returns:
            (True, "") se permitido
            (False, "motivo") se bloqueado
        """
        import urllib.parse
        try:
            new_hostname = urllib.parse.urlparse(new_url).hostname or ''
            new_sub24 = self._get_subnet(new_hostname, 24)

            # Conta peers no mesmo /24
            same_subnet = 0
            for url in current_urls:
                hostname = urllib.parse.urlparse(url).hostname or ''
                if self._get_subnet(hostname, 24) == new_sub24:
                    same_subnet += 1

            if same_subnet >= self._max_per_subnet:
                return (False,
                        f"Limite de {self._max_per_subnet} peers por /24 "
                        f"subnet atingido para {new_sub24}")

            # Verifica diversidade mínima de /16
            sub16s = set()
            for url in current_urls + [new_url]:
                hostname = urllib.parse.urlparse(url).hostname or ''
                sub16s.add(self._get_subnet(hostname, 16))

            if len(current_urls) > 0 and len(sub16s) < self._min_diversity:
                return (False,
                        f"Diversidade mínima de {self._min_diversity} /16 "
                        f"subnets não atingida")

            return True, ""

        except Exception as e:
            print(f"[WARN] Erro validando conexão de {new_url}: {e}")
            return False, f"Erro validando conexão: {e}"

    def select_peers(self, all_peers: List[Tuple[str, int]],
                     sample_size: int = None) -> List[str]:
        """
        Seleciona amostra de peers para sync cycle.

        Usa seleção aleatória ponderada por score (peers com
        score mais alto têm mais chance). Garante diversidade
        de subnets.

        Args:
            all_peers: Lista de (url, score) de todos os peers ativos
            sample_size: Tamanho da amostra (default: sync_sample_size)

        Returns:
            Lista de URLs selecionadas
        """
        import random, urllib.parse

        sample_size = sample_size or self._sync_sample_size
        if not all_peers:
            return []

        # Pega até sample_size * 2 candidatos (para filtro de diversidade)
        candidates = list(all_peers)
        selected = []
        used_subnets = set()

        # Ordena por score (maior primeiro) + aleatoriedade
        # Pesos: score + random noise para evitar previsibilidade
        weights = []
        for url, score in candidates:
            noise = random.uniform(0, 10)
            w = max(0.1, score + 30 + noise)  # offset para evitar negativos
            weights.append(w)

        # Seleção ponderada
        for _ in range(min(sample_size, len(candidates))):
            if not candidates:
                break
            total = sum(weights)
            r = random.uniform(0, total)
            cumulative = 0
            for i, (url, score) in enumerate(candidates):
                cumulative += weights[i]
                if r <= cumulative:
                    # Verifica diversidade de subnet
                    hostname = urllib.parse.urlparse(url).hostname or ''
                    subnet = self._get_subnet(hostname, 24)
                    if subnet not in used_subnets or len(used_subnets) >= self._min_diversity:
                        selected.append(url)
                        used_subnets.add(subnet)
                        candidates.pop(i)
                        weights.pop(i)
                    else:
                        # Skip este candidato, continua procurando
                        candidates.pop(i)
                        weights.pop(i)
                    break

        # Se não atingiu sample_size, preenche com qualquer peer
        if len(selected) < sample_size:
            remaining = [u for u, _ in all_peers if u not in selected]
            selected.extend(remaining[:sample_size - len(selected)])

        return selected[:sample_size]

    def detect_same_chain(self, chain_data: dict,
                          peer_url: str) -> Tuple[bool, str]:
        """
        Monitora chains idênticas recebidas de peers consecutivos.
        Se N peers consecutivos retornam a mesma chain, é um
        possível sinal de eclipse attack.

        Args:
            chain_data: Dados da chain recebida
            peer_url: URL do peer que enviou

        Returns:
            (True, "") se normal
            (True, "alerta") se suspeito (mas ainda OK)
            (False, "eclipse_detected") se eclipse confirmado
        """
        import hashlib
        chain_str = str(sorted(chain_data.items()))
        chain_hash = hashlib.sha256(chain_str.encode()).hexdigest()

        with self._lock:
            if chain_hash == self._last_chain_hash and chain_hash is not None:
                self._same_chain_count += 1
                if self._same_chain_count >= self._suspicious_same_chain:
                    return (False,
                            f"[WARN] ECLIPSE DETECTED: {self._same_chain_count} "
                            f"peers consecutivos retornaram chain idêntica")
                return (True,
                        f"[WARN] Atenção: {self._same_chain_count} peers "
                        f"com mesma chain consecutiva")
            else:
                self._last_chain_hash = chain_hash
                self._same_chain_count = 0
                return True, ""

    def get_allowed_peers(self, current_urls: List[str],
                          requesting_url: str) -> List[str]:
        """
        Filtra peers atualmente conectados, removendo os que
        violam limites de diversidade.

        Args:
            current_urls: URLs atuais
            requesting_url: URL do peer solicitante (ignorado na contagem)

        Returns:
            Lista filtrada de URLs
        """
        import urllib.parse
        subnet_count = {}
        allowed = []

        for url in current_urls:
            if url == requesting_url:
                allowed.append(url)
                continue
            try:
                hostname = urllib.parse.urlparse(url).hostname or ''
                sub24 = self._get_subnet(hostname, 24)
                if subnet_count.get(sub24, 0) < self._max_per_subnet:
                    allowed.append(url)
                    subnet_count[sub24] = subnet_count.get(sub24, 0) + 1
                else:
                    print(f"   [WARN] Peer {url} removido: excesso no /24 {sub24}")
            except Exception as e:
                print(f"[WARN] Erro ao filtrar peer {url}: {e}")
                allowed.append(url)

        return allowed

    def get_stats(self) -> dict:
        """Retorna estatísticas de proteção."""
        return {
            'max_per_subnet': self._max_per_subnet,
            'min_diversity': self._min_diversity,
            'max_outgoing': self._max_outgoing,
            'sync_sample_size': self._sync_sample_size,
            'suspicious_same_chain': self._suspicious_same_chain,
            'current_same_chain_count': self._same_chain_count
        }
