"""
Módulo principal da Blockchain.
Gerencia a cadeia de blocos, transações pendentes, mineração,
validação de integridade e persistência em arquivo.

A blockchain é um livro-razão (ledger) distribuído e imutável
onde cada bloco é ligado criptograficamente ao anterior.
"""
import json
import time
import os
import threading
import statistics
from typing import List, Optional, Callable
from .crypto_utils import CryptoUtils
from .block import Block
from .transaction import Transaction
from config import (
    INITIAL_BLOCK_REWARD, HALVING_INTERVAL, TOTAL_SUPPLY_CAP,
    MIN_TRANSACTION_AMOUNT, MIN_TRANSACTION_FEE, COINBASE_SENDER,
    TOKEN_NAME, TOKEN_SYMBOL,
    DIFFICULTY_ADJUST_INTERVAL, TARGET_BLOCK_TIME
)


# Recompensa de mineração (coinbase) — valor inicial
# O valor efetivo segue halving a cada HALVING_INTERVAL blocos
REWARD_AMOUNT = INITIAL_BLOCK_REWARD

# Limites da mempool
MAX_PENDING_TX = 100           # Máximo de transações pendentes
TX_EXPIRY_SECONDS = 3600       # Transações expiram após 1 hora
CLEANUP_INTERVAL = 300         # Limpeza automática a cada 5 minutos


class Blockchain:
    """
    Implementação principal da blockchain.

    Gerencia:
    - Cadeia de blocos encadeada
    - Pool de transações pendentes (mempool)
    - Mineração (Proof of Work)
    - Persistência em JSON
    - Validação de integridade
    - Substituição por consenso
    - Sistema de eventos para notificações em tempo real
    """

    def __init__(self, difficulty: int = 4, reward: float = REWARD_AMOUNT,
                 chain: List[Block] = None, node_id: str = None):
        """
        Inicializa a blockchain.

        Args:
            difficulty: Número de zeros necessários no hash (PoW)
            reward: Recompensa de mineração por bloco
            chain: Cadeia pré-existente (para carregar de arquivo)
            node_id: Identificador do nó
        """
        self.difficulty = difficulty      # Dificuldade do Proof of Work
        self.reward = reward              # Recompensa de mineração
        self.node_id = node_id or CryptoUtils.generate_node_id()

        # Pool de transações ainda não mineradas (mempool)
        self.pending_transactions: List[Transaction] = []

        # A cadeia de blocos propriamente dita
        self.chain: List[Block] = chain if chain else []

        # ─── Lock da Dificuldade ─────────────────────────────────
        # DEVE ser definido ANTES de adjust_difficulty(), que o adquire.
        # Protege self.difficulty contra race conditions durante
        # mineração concorrente e recebimento de blocos via P2P.
        self._difficulty_lock = threading.Lock()

        self.adjust_difficulty()

        # Se a cadeia está vazia, cria o bloco gênese
        if not self.chain:
            self._create_genesis_block()

        # ─── Sistema de Eventos ───────────────────────────────────
        # Callbacks registrados para notificar eventos em tempo real
        self._callbacks: dict = {
            'on_block_mined': [],        # Callbacks: (block) -> None
            'on_transaction_added': [],  # Callbacks: (transaction) -> None
            'on_chain_replaced': [],     # Callbacks: (old_len, new_len) -> None
            'on_transaction_expired': [],# Callbacks: (transaction) -> None
        }
        self._callback_lock = threading.Lock()

        # ─── Lock de Mineração ───────────────────────────────────
        # Previne race conditions que poderiam criar múltiplas
        # coinbases ou corromper a cadeia durante mineração concorrente.
        self._mining_lock = threading.Lock()

        # ─── Lock da Mempool ─────────────────────────────────────
        # Protege pending_transactions contra race conditions entre
        # add_transaction(), mine_block() e _cleanup_pending().
        # Sem este lock, threads concorrentes podem causar:
        # - Double-spend parcial (tx adicionada após verificação de saldo)
        # - Transações perdidas (append após clear do mine_block)
        # - Estado inconsistente entre verificação e escrita
        self._mempool_lock = threading.Lock()

        # ─── Peers URLs (para tempo de rede) ─────────────────────
        self._peer_urls: List[str] = []

        # ─── Timer de Limpeza da Mempool ──────────────────────────
        self._cleanup_timer = None
        self._start_cleanup_timer()

    # ─── Bloco Gênese ─────────────────────────────────────────────

    def _create_genesis_block(self):
        """
        Cria o bloco gênese (bloco #0).
        O bloco gênese é o primeiro bloco da blockchain, criado
        manualmente com valores específicos. Ele não tem bloco anterior,
        então seu previous_hash é uma string de zeros.

        No Bitcoin, o bloco gênese foi minerado por Satoshi Nakamoto
        em 3 de janeiro de 2009 e contém a famosa manchete do jornal
        The Times como dados.
        """
        genesis_tx = Transaction(
            sender='0',  # Coinbase
            receiver='genesis',
            amount=0,
            timestamp=0
        )
        genesis = Block(
            index=0,
            transactions=[genesis_tx],
            proof=100,  # Nonce escolhido arbitrariamente
            previous_hash='0' * 64,  # Sem bloco anterior
            timestamp=0
        )
        self.chain.append(genesis)

    # ─── Tempo de Rede ────────────────────────────────────────────

    def set_peer_urls(self, urls: List[str]):
        """Define as URLs dos peers para sincronização de tempo."""
        self._peer_urls = list(urls)

    def _get_network_time(self) -> Optional[float]:
        """
        Obtém o tempo de rede usando mediana dos timestamps dos peers.

        Estratégia:
        1. Tenta NTP primeiro (preciso, mas pode falhar sem internet)
        2. Fallback: mediana dos timestamps /health dos peers
        3. Fallback final: time.time() local

        A mediana é resistente a outliers — um nó malicioso com
        relógio adulterado não desvia a mediana sozinho.

        Returns:
            Timestamp Unix ou None se indisponível
        """
        from config import USE_NETWORK_TIME
        if not USE_NETWORK_TIME:
            return None

        # Tenta NTP
        try:
            import ntplib
            client = ntplib.NTPClient()
            response = client.request('pool.ntp.org', version=3, timeout=2)
            return response.tx_time
        except ImportError:
            pass  # ntplib não instalado
        except Exception as e:
            print(f"[WARN] NTP falhou: {e}")

        # Fallback: mediana dos peers
        if self._peer_urls:
            times = [time.time()]
            for url in self._peer_urls:
                try:
                    import requests
                    resp = requests.get(f'{url}/api/health', timeout=1)
                    if resp.status_code == 200:
                        data = resp.json()
                        if 'timestamp' in data:
                            times.append(data['timestamp'])
                except requests.exceptions.RequestException as e:
                    pass  # Peer offline, ignorar
                except Exception as e:
                    print(f"[WARN] Erro ao consultar peer {url}: {e}")
                    pass
            if times:
                return statistics.median(times)

        return None

    def _validate_timestamp(self, block_timestamp: float) -> bool:
        """
        Valida timestamp contra tempo de rede.

        Rejeita blocos com:
        - Timestamp muito no futuro (> MAX_TIMESTAMP_DRIFT segundos)
        - Timestamp muito no passado (> MIN_TIMESTAMP_AGE segundos)

        Args:
            block_timestamp: Timestamp do bloco a validar

        Returns:
            True se o timestamp está dentro da janela aceitável
        """
        from config import MAX_TIMESTAMP_DRIFT, MIN_TIMESTAMP_AGE

        network_time = self._get_network_time()
        now = network_time or time.time()

        # Não pode estar no futuro além da tolerância
        if block_timestamp > now + MAX_TIMESTAMP_DRIFT:
            print(f"[ERR] Timestamp {block_timestamp} muito no futuro "
                  f"(tolerância: {MAX_TIMESTAMP_DRIFT}s)")
            return False

        # Não pode estar muito no passado
        if now - block_timestamp > MIN_TIMESTAMP_AGE:
            print(f"[ERR] Timestamp {block_timestamp} muito no passado")
            return False

        return True

    # ─── Sistema de Eventos ────────────────────────────────────────

    def on(self, event: str, callback: Callable):
        """
        Registra um callback para um evento da blockchain.

        Eventos disponíveis:
        - 'on_block_mined':        Chamado quando um bloco é minerado
        - 'on_transaction_added':  Chamado quando uma transação é adicionada
        - 'on_chain_replaced':     Chamado quando a cadeia é substituída (consenso)
        - 'on_transaction_expired': Chamado quando uma transação expira

        Args:
            event: Nome do evento
            callback: Função a ser chamada

        Returns:
            self, para encadeamento de chamadas
        """
        if event in self._callbacks:
            with self._callback_lock:
                self._callbacks[event].append(callback)
        return self

    def off(self, event: str, callback: Callable):
        """
        Remove um callback registrado.

        Args:
            event: Nome do evento
            callback: Callback a remover
        """
        if event in self._callbacks:
            with self._callback_lock:
                self._callbacks[event] = [
                    cb for cb in self._callbacks[event] if cb is not callback
                ]

    def _emit(self, event: str, *args, **kwargs):
        """
        Dispara um evento, chamando todos os callbacks registrados.

        Args:
            event: Nome do evento
            args, kwargs: Argumentos passados aos callbacks
        """
        with self._callback_lock:
            callbacks = list(self._callbacks.get(event, []))
        for cb in callbacks:
            try:
                cb(*args, **kwargs)
            except Exception as e:
                print(f"[WARN] Erro no callback '{event}': {e}")

    # ─── Gerenciamento da Mempool ──────────────────────────────────

    def _start_cleanup_timer(self):
        """Inicia o timer de limpeza automática da mempool."""
        if self._cleanup_timer is not None:
            self._cleanup_timer.cancel()

        self._cleanup_timer = threading.Timer(CLEANUP_INTERVAL, self._cleanup_pending)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup_pending(self):
        """
        Remove transações expiradas da mempool.
        Thread-safe via _mempool_lock.
        """
        with self._mempool_lock:
            if not self.pending_transactions:
                self._start_cleanup_timer()
                return

            now = time.time()
            valid = []
            expired = []

            for tx in self.pending_transactions:
                tx_time = tx.timestamp
                if now - tx_time > TX_EXPIRY_SECONDS:
                    expired.append(tx)
                else:
                    valid.append(tx)

            if expired:
                self.pending_transactions = valid
                for tx in expired:
                    self._emit('on_transaction_expired', tx)
                print(f"[CLEAN] Mempool: {len(expired)} transações expiradas removidas")

        self._start_cleanup_timer()

    def get_mempool_stats(self) -> dict:
        """
        Retorna estatísticas da mempool.

        Returns:
            Dict com: total, faixa de valores, idade média, etc.
        """
        if not self.pending_transactions:
            return {
                'total': 0,
                'min_value': 0,
                'max_value': 0,
                'avg_value': 0,
                'oldest_tx': 0,
                'coinbase_count': 0,
                'total_fees': 0.0,
            }

        now = time.time()
        values = [tx.amount for tx in self.pending_transactions]
        coinbase_count = sum(
            1 for tx in self.pending_transactions if tx.sender == '0'
        )
        total_fees = sum(
            getattr(tx, 'fee', 0.0) for tx in self.pending_transactions
        )

        return {
            'total': len(self.pending_transactions),
            'min_value': min(values),
            'max_value': max(values),
            'avg_value': sum(values) / len(values),
            'oldest_tx': int(now - min(tx.timestamp for tx in self.pending_transactions)),
            'coinbase_count': coinbase_count,
            'total_fees': total_fees,
        }

    def has_transaction(self, tx_id: str) -> bool:
        """
        Verifica se uma transação já existe na mempool.
        Previne transações duplicadas.

        Args:
            tx_id: ID da transação a verificar

        Returns:
            True se a transação já está na mempool
        """
        return any(tx.transaction_id == tx_id for tx in self.pending_transactions)

    def adjust_difficulty(self):
        """
        Ajusta a dificuldade dinamicamente baseado no tempo de mineração.
        A cada `DIFFICULTY_ADJUST_INTERVAL` blocos (10), recalcula. Este é
        um mecanismo simplificado do algoritmo do Bitcoin que ajusta a
        cada 2016 blocos.

        THREAD-SAFE: protegido por _difficulty_lock para prevenir
        race conditions com recebimento de blocos via P2P.

        O alvo é `TARGET_BLOCK_TIME` por bloco (600s = um bloco a cada
        10 minutos), então a janela de retarget deve levar
        `TARGET_BLOCK_TIME * DIFFICULTY_ADJUST_INTERVAL` segundos.
        A dificuldade aumenta se a janela foi rápida demais (menos da
        metade do alvo) e diminui se foi lenta demais (mais do dobro).
        """
        with self._difficulty_lock:
            if len(self.chain) % DIFFICULTY_ADJUST_INTERVAL == 0 and len(self.chain) > 0:
                # Pega o timestamp do bloco atual e do início da janela
                last_block = self.chain[-1]
                window_start = (self.chain[-DIFFICULTY_ADJUST_INTERVAL]
                                if len(self.chain) >= DIFFICULTY_ADJUST_INTERVAL
                                else None)

                # O gênese tem timestamp 0; usá-lo como início da janela
                # faria o primeiro retarget parecer "lento demais".
                if window_start and window_start.index > 0:
                    time_span = last_block.timestamp - window_start.timestamp
                    target_time = TARGET_BLOCK_TIME * DIFFICULTY_ADJUST_INTERVAL

                    if time_span < target_time / 2:  # Muito rápido: aumenta dificuldade
                        self.difficulty += 1
                    elif time_span > target_time * 2:  # Muito lento: diminui
                        self.difficulty = max(1, self.difficulty - 1)

    # ─── Recompensa e Halving ──────────────────────────────────────

    def get_block_reward(self, block_index: int) -> float:
        """
        Calcula a recompensa de bloco considerando o halving.

        A cada HALVING_INTERVAL blocos, a recompensa é reduzida pela
        metade. Bloco 1 (primeiro após gênese) recebe reward inicial.
        Gênese (índice 0) não recebe recompensa.

        Ex: 2500 → 1250 → 625 → 312.5 → ...

        Args:
            block_index: Índice do bloco (0 = gênese)

        Returns:
            Recompensa do bloco em KUR
        """
        if block_index <= 0:
            return 0.0
        halvings = (block_index - 1) // HALVING_INTERVAL
        reward = INITIAL_BLOCK_REWARD / (2 ** halvings)
        # Se o valor for insignificante (< 0.0001 KUR), considera zero
        if reward < 0.0001:
            return 0.0
        return reward

    def get_total_supply(self) -> float:
        """
        Calcula o supply total minerado até agora.
        Soma todas as transações coinbase (sender='0') em todos os blocos.

        Returns:
            Total de KUR já minerados
        """
        total = 0.0
        for block in self.chain:
            for tx in block.transactions:
                if hasattr(tx, 'sender') and tx.sender == COINBASE_SENDER:
                    total += tx.amount
        return total

    def get_supply_info(self) -> dict:
        """
        Retorna informações completas sobre o supply do token.

        Returns:
            Dict com total_supply, remaining, supply_cap, percent_mined, etc.
        """
        total = self.get_total_supply()
        remaining = max(0.0, TOTAL_SUPPLY_CAP - total)
        percent = (total / TOTAL_SUPPLY_CAP) * 100.0 if TOTAL_SUPPLY_CAP > 0 else 0.0
        return {
            'token_name': TOKEN_NAME,
            'token_symbol': TOKEN_SYMBOL,
            'total_supply': total,
            'supply_cap': TOTAL_SUPPLY_CAP,
            'remaining_supply': remaining,
            'percent_mined': round(percent, 4),
            'blocks_mined': len(self.chain) - 1  # exclui gênese
        }

    # ─── Transações Pendentes ─────────────────────────────────────

    def add_transaction(self, sender: str, receiver: str, amount: float,
                        signature: str = None,
                        sender_address: str = None,
                        timestamp: float = None,
                        fee: float = 0.0,
                        transaction_id: str = None) -> int:
        """
        Adiciona uma nova transação à pool de transações pendentes.

        Args:
            sender: Chave pública do remetente
            receiver: Endereço do destinatário
            amount: Quantidade a transferir (KUR)
            signature: Assinatura digital (hex)
            sender_address: Endereço do remetente (para cálculo de saldo)
            fee: Taxa da transação (KUR) — paga ao minerador
            transaction_id: ID pré-definido (ex: para transações pré-assinadas)

        Returns:
            Índice do próximo bloco que incluirá esta transação

        Raises:
            ValueError: Se a transação é inválida
        """
        # ─── Lock da mempool para atomicidade ──────────────────
        # Protege contra race conditions: verificação de saldo,
        # anti-replay na cadeia e append devem ser atômicos.
        # Sem o lock, entre a verificação e o append outro
        # mine_block pode consumir transações ou outro
        # add_transaction pode criar double-spend.
        with self._mempool_lock:

            # ─── Bloqueia coinbase falsa ───────────────────────
            if sender == '0':
                raise ValueError(
                    "Transações coinbase (sender='0') são exclusivas do "
                    "sistema de mineração e não podem ser criadas via API"
                )

            # ─── Valida valor mínimo da transação ──────────────
            if amount < MIN_TRANSACTION_AMOUNT:
                raise ValueError(
                    f"Valor mínimo por transação: {MIN_TRANSACTION_AMOUNT} KUR"
                )

            # ─── Valida taxa mínima ────────────────────────────
            if fee < MIN_TRANSACTION_FEE:
                raise ValueError(
                    f"Taxa mínima por transação: {MIN_TRANSACTION_FEE} KUR"
                )

            # ─── Valida endereço do destinatário ───────────────
            if not CryptoUtils.is_valid_address(receiver):
                raise ValueError(
                    f"Endereço inválido: {receiver[:20]}..."
                )

            tx = Transaction(
                sender=sender, receiver=receiver, amount=amount,
                timestamp=timestamp, signature=signature,
                sender_address=sender_address, fee=fee,
                transaction_id=transaction_id
            )

            if not tx.is_valid():
                raise ValueError("Transação inválida: assinatura ou dados incorretos")

            if sender_address is not None:
                derived = CryptoUtils.public_key_to_address(sender)
                if sender_address != derived:
                    raise ValueError("sender_address não corresponde à chave pública.")

            if sender != '0':
                balance = self.get_balance(sender_address or sender)
                pending_spent = sum(
                    tx.amount + getattr(tx, 'fee', 0.0)
                    for tx in self.pending_transactions
                    if (tx.sender == sender or
                        tx.sender_address == sender_address)
                )
                available = balance - pending_spent
                if available < amount + fee:
                    raise ValueError(
                        f"Saldo insuficiente: {available:.2f} disponível "
                        f"(saldo: {balance:.2f}, pendente: {pending_spent:.2f}, "
                        f"necessário: {amount + fee:.2f})"
                    )

            if self.has_transaction(tx.transaction_id):
                raise ValueError(
                    f"Transação duplicada na mempool: {tx.transaction_id[:16]}..."
                )

            for block in self.chain:
                for existing_tx in block.transactions:
                    if existing_tx.transaction_id == tx.transaction_id:
                        raise ValueError(
                            f"Transação {tx.transaction_id[:16]}... já minerada "
                            f"no bloco #{block.index}. Replay bloqueado."
                        )

            if len(self.pending_transactions) >= MAX_PENDING_TX:
                raise ValueError(
                    f"Mempool cheia ({MAX_PENDING_TX} transações). "
                    "Aguarde a mineração de um novo bloco."
                )

            self.pending_transactions.append(tx)
            self._emit('on_transaction_added', tx)
            return self.last_block.index + 1

    @property
    def last_block(self) -> Optional[Block]:
        """Retorna o último bloco da cadeia."""
        return self.chain[-1] if self.chain else None

    # ─── Mineração (Proof of Work) ────────────────────────────────

    def mine_block(self, miner_address: str) -> Optional[Block]:
        """
        Minera um novo bloco com Proof of Work.

        O processo de mineração:
        1. Adiciona transação coinbase (recompensa do minerador)
        2. Encontra um nonce válido via Proof of Work
        3. Cria o bloco com as transações pendentes
        4. Adiciona à cadeia
        5. Ajusta dificuldade se necessário

        Args:
            miner_address: Endereço do minerador para receber a recompensa

        Returns:
            O bloco minerado ou None se não há transações
        """
        # ─── Lock de mineração para prevenir race conditions ────
        # Garante que apenas um processo minera por vez, evitando
        # múltiplas coinbases no mesmo bloco ou cadeias corrompidas.
        with self._mining_lock:
            return self._mine_block_unsafe(miner_address)

    def _mine_block_unsafe(self, miner_address: str) -> Optional[Block]:
        """
        Execução interna da mineração (sem lock, chamada pelo
        método público que adquire o lock).

        Args:
            miner_address: Endereço do minerador

        Returns:
            O bloco minerado
        """
        # ─── Snapshot da mempool sob lock ──────────────────────
        # Garante atomicidade: snapshots de pending_transactions
        # prevenindo race conditions com add_transaction().
        # Libera o lock ANTES do PoW (operação longa).
        with self._mempool_lock:
            if len(self.pending_transactions) >= MAX_PENDING_TX:
                print("[WARN] Mempool cheia, não é possível minerar")
                return None

            # ─── Calcula recompensa com halving + fees ────────────
            new_index = self.last_block.index + 1 if self.last_block else 1
            base_reward = self.get_block_reward(new_index)
            total_fees = sum(
                getattr(tx, 'fee', 0.0) for tx in self.pending_transactions
            )
            total_reward = base_reward + total_fees

            # ─── Verifica supply cap ────────────────────────────
            current_supply = self.get_total_supply()
            if current_supply + total_reward > TOTAL_SUPPLY_CAP:
                # Capa o reward para não ultrapassar 1 bilhão
                total_reward = max(total_fees, TOTAL_SUPPLY_CAP - current_supply)

            reward_tx = Transaction(
                sender='0', receiver=miner_address,
                amount=total_reward, timestamp=time.time()
            )

            # Coinbase inserida no índice 0
            self.pending_transactions.insert(0, reward_tx)

            # Snapshot atômico para mineração
            tx_list = list(self.pending_transactions)
            tx_count = len(self.pending_transactions)
            self.pending_transactions = []  # Limpa sob lock

        # ─── Mineração (fora do lock) ──────────────────────────
        # O PoW é computacionalmente intenso e não deve travar
        # outras operações (add_transaction, validação).
        # A coinbase já está incluída no snapshot tx_list (linha 535-538)
        # e NÃO deve ser reinserida fora do lock (anti-race condition).
        # add_transaction() bloqueia sender='0', impedindo coinbase externa.

        # Prepara o bloco
        new_index = self.last_block.index + 1 if self.last_block else 0
        previous_hash = self.last_block.hash if self.last_block else '0' * 64

        print(f"\n[MINE] Minerando bloco #{new_index}...")
        print(f"   Dificuldade: {self.difficulty}")
        print(f"   Transações: {tx_count}")
        print(f"   Recompensa base: {base_reward} KUR (halving #{new_index // HALVING_INTERVAL})")
        if total_fees > 0:
            print(f"   Taxas coletadas: {total_fees} KUR")

        # ─── Proof of Work ──────────────────────────────────────────
        timestamp = time.time()
        tx_dicts = [
            tx.to_dict() if hasattr(tx, 'to_dict') else tx
            for tx in tx_list
        ]
        merkle_root = CryptoUtils.merkle_root(tx_dicts)
        proof = self._proof_of_work(
            new_index, previous_hash, timestamp, tx_dicts, merkle_root
        )

        # Cria o bloco com o nonce encontrado
        block = Block(
            index=new_index,
            transactions=tx_list,
            proof=proof,
            previous_hash=previous_hash,
            difficulty=self.difficulty,
            timestamp=timestamp,
            merkle_root=merkle_root
        )

        # ─── Merge Atômico da Mempool ────────────────────────────
        # Em vez de limpar cegamente self.pending_transactions (que
        # descartaria TXs adicionadas durante o PoW — N-C01), fazemos
        # merge atômico sob lock: removemos apenas TXs mineradas.
        with self._mempool_lock:
            mined_ids = {tx.transaction_id for tx in tx_list}
            self.pending_transactions = [
                tx for tx in self.pending_transactions
                if tx.transaction_id not in mined_ids
            ]

        # Adiciona à cadeia
        self.chain.append(block)
        self.adjust_difficulty()

        print(f"[OK] Bloco #{new_index} minerado!")
        print(f"   Hash: {block.hash[:32]}...")
        print(f"   Nonce: {proof}")
        print(f"   Recompensa: {total_reward:.2f} KUR para {miner_address[:16]}...")

        # Notifica listeners
        self._emit('on_block_mined', block)

        return block

    def _proof_of_work(self, index: int, previous_hash: str,
                       timestamp: float, tx_dicts: list,
                       merkle_root: str) -> int:
        """
        Algoritmo de Proof of Work (Mineração).

        Encontra um número (nonce) tal que o hash do bloco
        comece com 'difficulty' zeros. Este é o "trabalho" que
        prova que esforço computacional foi gasto.

        O processo:
        1. Começa com nonce = 0
        2. Calcula o hash do bloco candidato (mesmos campos de Block.calculate_hash)
        3. Se o hash não começa com zeros suficientes, incrementa nonce
        4. Repete até encontrar um hash válido

        Args:
            index: Índice do bloco sendo minerado
            previous_hash: Hash do bloco anterior
            timestamp: Timestamp do bloco
            tx_dicts: Transações já serializadas
            merkle_root: Raiz de Merkle pré-calculada

        Returns:
            Nonce que satisfaz o requisito de dificuldade
        """
        proof = 0

        while True:
            # Constrói dados candidatos para hashing
            # Usa os MESMOS campos que Block.calculate_hash()
            # para que o hash válido também seja válido para o bloco final
            candidate = {
                'index': index,
                'timestamp': timestamp,
                'transactions': tx_dicts,
                'proof': proof,
                'previous_hash': previous_hash,
                'merkle_root': merkle_root
            }
            hash_value = CryptoUtils.hash_block(candidate)

            # Verifica se o hash atende à dificuldade
            if CryptoUtils.is_hash_valid(hash_value, self.difficulty):
                return proof

            proof += 1

            # Feedback a cada 100.000 tentativas
            if proof % 100000 == 0:
                print(f"   Tentativas: {proof} (último hash: {hash_value[:16]}...)")

    # ─── Validação da Cadeia ──────────────────────────────────────

    def is_chain_valid(self, chain: List[Block] = None) -> bool:
        """
        Valida a integridade completa da blockchain.

        Verifica:
        1. O bloco gênese está correto
        2. Cada bloco tem um hash que satisfaz a dificuldade do PoW
        3. Cada bloco aponta corretamente para o hash do anterior
        4. As transações em cada bloco são válidas

        Esta validação é usada tanto localmente quanto no consenso
        para rejeitar cadeias corrompidas ou maliciosas.

        Args:
            chain: Cadeia a validar (usa a local se None)

        Returns:
            True se a cadeia é completamente válida
        """
        chain = chain or self.chain

        if not chain:
            return False

        # Verifica o bloco gênese
        genesis = chain[0]
        if genesis.index != 0 or genesis.previous_hash != '0' * 64:
            print("[ERR] Bloco gênese inválido!")
            return False

        # Percorre todos os blocos a partir do índice 1
        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # 1. Verifica se o hash do bloco está correto
            calculated_hash = current.calculate_hash()
            if current.hash != calculated_hash:
                print(f"[ERR] Bloco #{current.index}: hash inválido!")
                print(f"   Esperado: {calculated_hash}")
                print(f"   Atual:    {current.hash}")
                return False

            # 2. Verifica a ligação com o bloco anterior
            if current.previous_hash != previous.hash:
                print(f"[ERR] Bloco #{current.index}: previous_hash incorreto!")
                print(f"   Esperado: {previous.hash}")
                print(f"   Atual:    {current.previous_hash}")
                return False

            # 3. Verifica o Proof of Work (hash começa com zeros)
            # Usa a dificuldade armazenada no bloco (pode variar)
            block_difficulty = current.difficulty or self.difficulty
            block_dict = {
                'index': current.index,
                'timestamp': current.timestamp,
                'transactions': [
                    tx.to_dict() if hasattr(tx, 'to_dict') else tx
                    for tx in current.transactions
                ],
                'proof': current.proof,
                'previous_hash': current.previous_hash,
                'merkle_root': current.merkle_root
            }
            block_hash = CryptoUtils.hash_block(block_dict)
            if not CryptoUtils.is_hash_valid(block_hash, block_difficulty):
                print(f"[ERR] Bloco #{current.index}: Proof of Work inválido!")
                return False

            # 4. Verifica transações do bloco
            if not current.is_valid_transactions():
                print(f"[ERR] Bloco #{current.index}: transações inválidas!")
                return False

        # 5. Verifica supply cap (cumulativo)
        total_supply = self.get_total_supply()
        if total_supply > TOTAL_SUPPLY_CAP + 0.01:  # tolerância de float
            print(f"[ERR] Supply cap excedido: {total_supply:.2f} > {TOTAL_SUPPLY_CAP:.0f}")
            return False

        print("[OK] Blockchain válida e íntegra!")
        return True

    # ─── Consultas ────────────────────────────────────────────────

    def get_balance(self, address: str) -> float:
        """
        Calcula o saldo de um endereço varrendo toda a blockchain.
        Não existe saldo armazenado - ele é calculado a cada consulta.

        O saldo é a soma de todas as entradas (recebimentos) menos
        todas as saídas (envios) associadas ao endereço.

        Args:
            address: Endereço da carteira (ou chave pública)

        Returns:
            Saldo total em coins
        """
        balance = 0.0

        for block in self.chain:
            for tx in block.transactions:
                tx_dict = tx.to_dict() if hasattr(tx, 'to_dict') else tx

                # Recebeu coins (entrada)
                if tx_dict['receiver'] == address:
                    balance += tx_dict['amount']

                # Enviou coins (saída) - verifica sender_address também
                # Subtrai amount + fee (custo total para o sender)
                if (tx_dict['sender'] == address or
                        tx_dict.get('sender_address') == address):
                    balance -= tx_dict['amount']
                    balance -= tx_dict.get('fee', 0.0)

        return balance

    def get_transaction_history(self, address: str) -> List[dict]:
        """
        Retorna o histórico completo de transações de um endereço.

        Args:
            address: Endereço da carteira

        Returns:
            Lista de transações envolvendo este endereço
        """
        history = []
        for block in self.chain:
            for tx in block.transactions:
                tx_dict = tx.to_dict() if hasattr(tx, 'to_dict') else tx
                if (tx_dict['sender'] == address or
                        tx_dict['receiver'] == address or
                        tx_dict.get('sender_address') == address):
                    history.append({
                        **tx_dict,
                        'block_index': block.index,
                        'confirmed': True
                    })
        return history

    # ─── Persistência (JSON) ──────────────────────────────────────

    def save_to_file(self, filepath: str = 'data/blockchain.json'):
        """
        Salva a blockchain em um arquivo JSON.

        Formato:
        {
            "chain": [...],        # Lista de blocos serializados
            "pending_transactions": [...],  # Transações não mineradas
            "difficulty": 4,
            "node_id": "..."
        }

        Args:
            filepath: Caminho do arquivo para salvar
        """
        # Garante que o diretório existe
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        data = {
            'chain': [block.to_dict() for block in self.chain],
            'pending_transactions': [
                tx.to_dict() if hasattr(tx, 'to_dict') else tx
                for tx in self.pending_transactions
            ],
            'difficulty': self.difficulty,
            'reward': self.reward,
            'node_id': self.node_id
        }

        # Escrita atômica: grava em um temporário e renomeia. Com autosave a
        # cada bloco, um crash no meio do dump não pode corromper a cadeia.
        tmp_path = f'{filepath}.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)

        print(f"[SAVE] Blockchain salva em {filepath} "
              f"({len(self.chain)} blocos, "
              f"{len(self.pending_transactions)} transações pendentes)")

    @classmethod
    def load_from_file(cls, filepath: str = 'data/blockchain.json',
                       difficulty: int = 4) -> 'Blockchain':
        """
        Carrega a blockchain de um arquivo JSON.

        Args:
            filepath: Caminho do arquivo
            difficulty: Dificuldade padrão (usada se não salva)

        Returns:
            Instância de Blockchain restaurada

        Raises:
            FileNotFoundError: Se o arquivo não existe
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

        with open(filepath, 'r') as f:
            data = json.load(f)

        # Reconstrói blocos a partir dos dicionários
        chain = []
        for block_data in data['chain']:
            block = Block.from_dict(block_data, Transaction)
            chain.append(block)

        # Reconstrói transações pendentes
        pending_txs = []
        for tx_data in data.get('pending_transactions', []):
            pending_txs.append(Transaction.from_dict(tx_data))

        # Cria instância
        blockchain = cls(
            difficulty=data.get('difficulty', difficulty),
            reward=data.get('reward', REWARD_AMOUNT),
            chain=chain,
            node_id=data.get('node_id')
        )

        # Restaura transações pendentes
        blockchain.pending_transactions = pending_txs

        print(f"[LOAD] Blockchain carregada de {filepath} "
              f"({len(chain)} blocos, "
              f"{len(pending_txs)} transações pendentes)")

        return blockchain

    # ─── Serialização para API ────────────────────────────────────

    def to_dict(self) -> dict:
        """Converte toda a blockchain para dicionário (para API)."""
        return {
            'chain': [block.to_dict() for block in self.chain],
            'pending_transactions': [
                tx.to_dict() if hasattr(tx, 'to_dict') else tx
                for tx in self.pending_transactions
            ],
            'difficulty': self.difficulty,
            'length': len(self.chain),
            'node_id': self.node_id
        }

    # ─── Consenso ──────────────────────────────────────────────────

    def _calculate_cumulative_work(self, chain: List[Block]) -> float:
        """
        Calcula o trabalho acumulado de uma cadeia (cumulative work).

        Diferente do consenso ingênuo de "cadeia mais longa", o trabalho
        acumulado considera a DIFICULDADE de cada bloco. Um bloco com
        difficulty=4 requer 2^4 = 16 hashes esperados, enquanto
        difficulty=1 requer apenas 2^1 = 2 hashes.

        Isso impede que um atacante mine blocos com dificuldade baixa
        e apresente uma cadeia mais "longa" que a legítima.

        Returns:
            Float representando o trabalho total acumulado
        """
        total_work = 0.0
        for block in chain:
            block_diff = block.difficulty if block.difficulty is not None else self.difficulty
            total_work += 2 ** block_diff
        return total_work

    def resolve_conflicts(self, other_chains: List[List[dict]]) -> bool:
        """
        Algoritmo de consenso baseado em CUMULATIVE WORK.

        Regra: a cadeia válida com MAIOR TRABALHO ACUMULADO é a correta.
        Este é o princípio do "maior trabalho" do Bitcoin (e não
        simplesmente "cadeia mais longa").

        O uso de cumulative work impede que um atacante crie uma cadeia
        longa com dificuldade baixa e a apresente como legítima.

        Args:
            other_chains: Lista de cadeias (listas de dicts) de outros nós

        Returns:
            True se a cadeia local foi substituída
        """
        new_chain = None
        best_work = self._calculate_cumulative_work(self.chain)

        for chain_data in other_chains:
            # Reconstrói a cadeia recebida
            candidate_chain = []
            for block_data in chain_data:
                block = Block.from_dict(block_data, Transaction)
                candidate_chain.append(block)

            # Verifica cumulative work e validade
            candidate_work = self._calculate_cumulative_work(candidate_chain)
            if (candidate_work > best_work and
                    self._validate_external_chain(candidate_chain)):
                new_chain = candidate_chain
                best_work = candidate_work

        if new_chain:
            old_len = len(self.chain)

            # ─── REORG Limit ─────────────────────────────────────
            # Anti-deep reorg: verifica se a nova cadeia compartilha
            # os primeiros REORG_LIMIT blocos com a local. Impede que
            # um atacante substitua blocos muito antigos.
            from config import REORG_LIMIT
            if REORG_LIMIT > 0:
                common_blocks = 0
                for i in range(min(old_len, len(new_chain))):
                    if (self.chain[i].hash == new_chain[i].hash and
                            self.chain[i].index == new_chain[i].index):
                        common_blocks += 1
                    else:
                        break
                if old_len - common_blocks > REORG_LIMIT:
                    print(f"[ERR] Consenso: reorganização de "
                          f"{old_len - common_blocks} blocos > "
                          f"limite de {REORG_LIMIT}. Rejeitada.")
                    return False

            self.chain = new_chain

            # ─── Merge da Mempool Pós-Consenso ───────────────────
            # Re-valida transações pendentes contra a nova cadeia.
            # Remove TXs já mineradas e re-verifica saldos.
            with self._mempool_lock:
                valid_txs = []
                for tx in self.pending_transactions:
                    # Pula coinbase remanescente, se houver
                    if tx.sender == '0':
                        continue
                    # TX já minerada na nova cadeia?
                    already_mined = any(
                        bt.transaction_id == tx.transaction_id
                        for block in self.chain
                        for bt in block.transactions
                    )
                    if already_mined:
                        continue
                    # Re-valida assinatura
                    if not tx.is_valid():
                        continue
                    # Re-verifica saldo contra nova cadeia
                    sender_addr = tx.sender_address or tx.sender
                    balance = self.get_balance(sender_addr)
                    tx_fee = getattr(tx, 'fee', 0.0)
                    if balance >= tx.amount + tx_fee:
                        valid_txs.append(tx)
                self.pending_transactions = valid_txs
                print(f"[SYNC] Mempool mesclada: {len(valid_txs)} TXs mantidas "
                      f"após consenso")

            print(f"[SYNC] Consenso: cadeia substituída "
                  f"(trabalho acumulado: {best_work:.0f})")
            self._emit('on_chain_replaced', old_len, len(self.chain))
            return True

        print(f"[OK] Consenso: cadeia local mantida "
              f"(trabalho acumulado: {best_work:.0f})")
        return False

    def _validate_external_chain(self, chain: List[Block]) -> bool:
        """
        Valida uma cadeia recebida de outro nó.

        Validações de PRODUÇÃO:
        1. Estrutura básica (hash, previous_hash, PoW)
        2. Dificuldade mínima aceitável (anti-51% attack)
        3. Salto de dificuldade controlado (anti-manipulação)
        4. Timestamp dentro da janela de rede

        Args:
            chain: Cadeia a validar

        Returns:
            True se a cadeia é válida para consenso
        """
        from config import MIN_ACCEPTABLE_DIFFICULTY, MAX_DIFFICULTY_JUMP

        if not chain:
            return False

        # Verifica bloco gênese
        if chain[0].index != 0 or chain[0].previous_hash != '0' * 64:
            return False

        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # Hash correto
            if current.hash != current.calculate_hash():
                return False

            # Ligação correta
            if current.previous_hash != previous.hash:
                return False

            # ─── Validação de Dificuldade ──────────────────────
            # Anti-51%: bloco com difficulty abaixo do mínimo
            # indica ataque de cadeia barata.
            block_difficulty = current.difficulty
            if block_difficulty is not None:
                if block_difficulty < MIN_ACCEPTABLE_DIFFICULTY:
                    print(f"[ERR] Consenso: bloco #{current.index} difficulty "
                          f"{block_difficulty} < mínimo {MIN_ACCEPTABLE_DIFFICULTY}")
                    return False

                # Anti-manipulação: salto de difficulty muito grande
                # entre blocos consecutivos indica adulteração.
                # Leitura thread-safe via _difficulty_lock
                with self._difficulty_lock:
                    local_difficulty = self.difficulty
                prev_difficulty = (chain[i-1].difficulty or
                                   local_difficulty)
                if abs(block_difficulty - prev_difficulty) > MAX_DIFFICULTY_JUMP:
                    print(f"[ERR] Consenso: salto de difficulty de "
                          f"{prev_difficulty} para {block_difficulty}")
                    return False

            # ─── Validação de Timestamp ────────────────────────
            if not self._validate_timestamp(current.timestamp):
                print(f"[ERR] Consenso: timestamp inválido no bloco "
                      f"#{current.index}")
                return False

            # ─── Verificação do Proof of Work ──────────────────
            block_difficulty = current.difficulty or self.difficulty
            block_dict = {
                'index': current.index,
                'timestamp': current.timestamp,
                'transactions': [
                    tx.to_dict() if hasattr(tx, 'to_dict') else tx
                    for tx in current.transactions
                ],
                'proof': current.proof,
                'previous_hash': current.previous_hash,
                'merkle_root': current.merkle_root
            }
            block_hash = CryptoUtils.hash_block(block_dict)
            if not CryptoUtils.is_hash_valid(block_hash, block_difficulty):
                print(f"[ERR] Consenso: bloco #{current.index} da cadeia externa "
                      f"não atende ao PoW (difficulty={block_difficulty})")
                return False

        return True

    def __str__(self) -> str:
        """Representação legível da blockchain."""
        return (f"Blockchain({len(self.chain)} blocos | "
                f"Dificuldade: {self.difficulty} | "
                f"Pendentes: {len(self.pending_transactions)} | "
                f"Nó: {self.node_id[:8]}...)")
