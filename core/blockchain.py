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
from typing import List, Optional, Callable
from .crypto_utils import CryptoUtils
from .block import Block
from .transaction import Transaction


# Valor fixo da recompensa de mineração (coinbase)
REWARD_AMOUNT = 50.0

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
                print(f"⚠️ Erro no callback '{event}': {e}")

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
        Transações com timestamp mais antigo que TX_EXPIRY_SECONDS
        são removidas automaticamente para evitar acúmulo.
        """
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
            print(f"🧹 Mempool: {len(expired)} transações expiradas removidas")

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
            }

        now = time.time()
        values = [tx.amount for tx in self.pending_transactions]
        coinbase_count = sum(
            1 for tx in self.pending_transactions if tx.sender == '0'
        )

        return {
            'total': len(self.pending_transactions),
            'min_value': min(values),
            'max_value': max(values),
            'avg_value': sum(values) / len(values),
            'oldest_tx': int(now - min(tx.timestamp for tx in self.pending_transactions)),
            'coinbase_count': coinbase_count,
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
        A cada 10 blocos, recalcula. Este é um mecanismo simplificado
        do algoritmo do Bitcoin que ajusta a cada 2016 blocos.

        A dificuldade aumenta se os blocos estão sendo minerados
        rápido demais (>30s por bloco) e diminui se estão lentos (<5s).
        """
        if len(self.chain) % 10 == 0 and len(self.chain) > 0:
            # Pega o timestamp do bloco atual e do bloco 10 atrás
            last_block = self.chain[-1]
            ten_blocks_ago = self.chain[-10] if len(self.chain) >= 10 else None

            if ten_blocks_ago:
                time_span = last_block.timestamp - ten_blocks_ago.timestamp
                target_time = 300  # Esperado: 30s * 10 blocos = 300s

                if time_span < target_time / 2:  # Muito rápido: aumenta dificuldade
                    self.difficulty += 1
                elif time_span > target_time * 2:  # Muito lento: diminui
                    self.difficulty = max(1, self.difficulty - 1)

    # ─── Transações Pendentes ─────────────────────────────────────

    def add_transaction(self, sender: str, receiver: str, amount: float,
                        signature: str = None,
                        sender_address: str = None,
                        timestamp: float = None) -> int:
        """
        Adiciona uma nova transação à pool de transações pendentes.

        Args:
            sender: Chave pública do remetente
            receiver: Endereço do destinatário
            amount: Quantidade a transferir
            signature: Assinatura digital (hex)
            sender_address: Endereço do remetente (para cálculo de saldo)

        Returns:
            Índice do próximo bloco que incluirá esta transação

        Raises:
            ValueError: Se a transação é inválida
        """
        # Cria a transação (usa timestamp original se fornecido,
        # para preservar a validade da assinatura)
        tx = Transaction(
            sender=sender,
            receiver=receiver,
            amount=amount,
            timestamp=timestamp,
            signature=signature,
            sender_address=sender_address
        )

        # Valida a transação
        if not tx.is_valid():
            raise ValueError("Transação inválida: assinatura ou dados incorretos")

        # Verifica se o remetente tem saldo suficiente (exceto coinbase)
        if sender != '0':
            balance = self.get_balance(sender_address or sender)
            if balance < amount:
                raise ValueError(
                    f"Saldo insuficiente: {balance:.2f} < {amount:.2f}"
                )

        # Verifica duplicata na mempool
        if self.has_transaction(tx.transaction_id):
            raise ValueError(f"Transação duplicada: {tx.transaction_id[:16]}...")

        # Verifica limite máximo da mempool
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
        # Adiciona transação de recompensa (coinbase transaction)
        reward_tx = Transaction(
            sender='0',  # Sistema
            receiver=miner_address,
            amount=self.reward,
            timestamp=time.time()
        )
        self.pending_transactions.append(reward_tx)

        # Prepara o bloco
        new_index = self.last_block.index + 1 if self.last_block else 0
        previous_hash = self.last_block.hash if self.last_block else '0' * 64

        print(f"\n⛏️  Minerando bloco #{new_index}...")
        print(f"   Dificuldade: {self.difficulty}")
        print(f"   Transações: {len(self.pending_transactions)}")

        # ─── Proof of Work ──────────────────────────────────────────
        # O minerador busca um nonce (proof) tal que o hash do bloco
        # comece com 'difficulty' zeros. Isso exige força bruta e
        # consome energia computacional intencionalmente.
        timestamp = time.time()
        tx_dicts = [
            tx.to_dict() if hasattr(tx, 'to_dict') else tx
            for tx in self.pending_transactions
        ]
        merkle_root = CryptoUtils.merkle_root(tx_dicts)
        proof = self._proof_of_work(
            new_index, previous_hash, timestamp, tx_dicts, merkle_root
        )

        # Cria o bloco com o nonce encontrado
        block = Block(
            index=new_index,
            transactions=self.pending_transactions.copy(),
            proof=proof,
            previous_hash=previous_hash,
            difficulty=self.difficulty,
            timestamp=timestamp,
            merkle_root=merkle_root
        )

        # Limpa transações pendentes (as que foram mineradas)
        self.pending_transactions = []

        # Adiciona à cadeia
        self.chain.append(block)
        self.adjust_difficulty()

        print(f"✅ Bloco #{new_index} minerado!")
        print(f"   Hash: {block.hash[:32]}...")
        print(f"   Nonce: {proof}")
        print(f"   Recompensa: {self.reward} coins para {miner_address[:16]}...")

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
            print("❌ Bloco gênese inválido!")
            return False

        # Percorre todos os blocos a partir do índice 1
        for i in range(1, len(chain)):
            current = chain[i]
            previous = chain[i - 1]

            # 1. Verifica se o hash do bloco está correto
            calculated_hash = current.calculate_hash()
            if current.hash != calculated_hash:
                print(f"❌ Bloco #{current.index}: hash inválido!")
                print(f"   Esperado: {calculated_hash}")
                print(f"   Atual:    {current.hash}")
                return False

            # 2. Verifica a ligação com o bloco anterior
            if current.previous_hash != previous.hash:
                print(f"❌ Bloco #{current.index}: previous_hash incorreto!")
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
                print(f"❌ Bloco #{current.index}: Proof of Work inválido!")
                return False

            # 4. Verifica transações do bloco
            if not current.is_valid_transactions():
                print(f"❌ Bloco #{current.index}: transações inválidas!")
                return False

        print("✅ Blockchain válida e íntegra!")
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
                if (tx_dict['sender'] == address or
                        tx_dict.get('sender_address') == address):
                    balance -= tx_dict['amount']

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

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"💾 Blockchain salva em {filepath} "
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

        print(f"📂 Blockchain carregada de {filepath} "
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

    def resolve_conflicts(self, other_chains: List[List[dict]]) -> bool:
        """
        Algoritmo de consenso simplificado.

        Regra: a cadeia válida MAIS LONGA é a correta.
        Este é o princípio do "maior trabalho acumulado" do Bitcoin.

        Quando um nó recebe cadeias de outros nós:
        1. Para cada cadeia recebida, verifica se é válida
        2. Se for válida E mais longa que a local, substitui a local

        Args:
            other_chains: Lista de cadeias (listas de dicts) de outros nós

        Returns:
            True se a cadeia local foi substituída
        """
        new_chain = None
        max_length = len(self.chain)

        for chain_data in other_chains:
            # Reconstrói a cadeia recebida
            candidate_chain = []
            for block_data in chain_data:
                block = Block.from_dict(block_data, Transaction)
                candidate_chain.append(block)

            # Verifica se é mais longa e válida
            if (len(candidate_chain) > max_length and
                    self._validate_external_chain(candidate_chain)):
                new_chain = candidate_chain
                max_length = len(candidate_chain)

        if new_chain:
            old_len = len(self.chain)
            self.chain = new_chain
            print(f"🔄 Consenso: cadeia substituída "
                  f"(nova: {len(self.chain)} blocos)")
            self._emit('on_chain_replaced', old_len, len(self.chain))
            return True

        print(f"✅ Consenso: cadeia local mantida "
              f"({len(self.chain)} blocos)")
        return False

    def _validate_external_chain(self, chain: List[Block]) -> bool:
        """
        Valida uma cadeia recebida de outro nó.
        Verificação menos rigorosa que a local (não usa a dificuldade local).

        Args:
            chain: Cadeia a validar

        Returns:
            True se a cadeia é estruturalmente válida
        """
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

        return True

    def __str__(self) -> str:
        """Representação legível da blockchain."""
        return (f"Blockchain({len(self.chain)} blocos | "
                f"Dificuldade: {self.difficulty} | "
                f"Pendentes: {len(self.pending_transactions)} | "
                f"Nó: {self.node_id[:8]}...)")
