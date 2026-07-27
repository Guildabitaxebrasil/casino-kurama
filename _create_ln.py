"""Script to create Lightning Network module files."""
import os

os.makedirs('lightning', exist_ok=True)

files = {}

files['lightning/__init__.py'] = '''"""
Lightning Network — Canais de Pagamento Off-Chain para KuramaChain.

Implementa uma camada de pagamentos off-chain inspirada na Lightning Network
do Bitcoin, com canais bidirecionais, HTLCs e roteamento multi-hop.
"""

from .lightning_network import LightningNetwork
from .channel import PaymentChannel, ChannelState, CommitmentTransaction
from .htlc import HTLC
from .channel_manager import ChannelManager
from .router import PaymentRouter

__all__ = [
    'LightningNetwork', 'PaymentChannel', 'ChannelState',
    'CommitmentTransaction', 'HTLC', 'ChannelManager', 'PaymentRouter',
]
'''

files['lightning/channel.py'] = '''"""
Canal de Pagamento (Payment Channel).
Gerencia canais bidirecionais off-chain entre duas partes.
"""

import time
import json
import hashlib
from enum import Enum
from typing import Optional
from core.crypto_utils import CryptoUtils


class ChannelState(Enum):
    """Estados possíveis de um canal de pagamento."""
    PENDING = "pending"          # Funding tx enviada, aguardando confirmação
    OPEN = "open"                # Canal ativo para transações off-chain
    CLOSING_COOP = "closing_coop"  # Fechamento cooperativo em andamento
    CLOSING_FORCE = "closing_force"  # Force-close em andamento
    CLOSED = "closed"            # Canal liquidado na blockchain


class CommitmentTransaction:
    """
    Transação de compromisso off-chain.
    Representa um snapshot do estado do canal assinado por ambas as partes.
    A cada atualização de saldo, um novo commitment com sequence++ é criado.
    O commitment com maior sequence é o estado mais recente do canal.
    """

    def __init__(self, channel_id: str, sequence: int,
                 balance_a: float, balance_b: float,
                 pending_htlcs: list = None,
                 signature_a: str = None, signature_b: str = None):
        self.channel_id = channel_id
        self.sequence = sequence
        self.balance_a = balance_a
        self.balance_b = balance_b
        self.pending_htlcs = pending_htlcs or []
        self.signature_a = signature_a
        self.signature_b = signature_b
        self.timestamp = time.time()
        self.hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """Calcula o hash deste commitment (identificador único)."""
        data = {
            'channel_id': self.channel_id,
            'sequence': self.sequence,
            'balance_a': self.balance_a,
            'balance_b': self.balance_b,
            'pending_htlcs': sorted([
                h.to_dict() if hasattr(h, 'to_dict') else h
                for h in self.pending_htlcs
            ], key=lambda x: x.get('htlc_id', '')),
            'timestamp': self.timestamp,
        }
        return CryptoUtils.sha256(json.dumps(data, sort_keys=True))

    def to_dict(self) -> dict:
        return {
            'channel_id': self.channel_id,
            'sequence': self.sequence,
            'balance_a': self.balance_a,
            'balance_b': self.balance_b,
            'pending_htlcs': [
                h.to_dict() if hasattr(h, 'to_dict') else h
                for h in self.pending_htlcs
            ],
            'signature_a': self.signature_a,
            'signature_b': self.signature_b,
            'timestamp': self.timestamp,
            'hash': self.hash,
        }


class PaymentChannel:
    """
    Canal de pagamento bidirecional entre duas partes na KuramaChain.

    O canal funciona assim:
    1. FUNDING: Alice e Bob depositam KUR num funding tx on-chain
    2. OFF-CHAIN: Eles trocam commitments assinados refletindo saldos atuais
    3. UPDATE: Qualquer saldo novo requer um NOVO commitment assinado por ambos
    4. CLOSE: O commitment MAIS RECENTE é transmitido on-chain para liquidação
    """

    def __init__(self, party_a: str, party_b: str,
                 balance_a: float = 0.0, balance_b: float = 0.0,
                 channel_id: str = None, funding_tx_id: str = None,
                 created_at: float = None):
        self.channel_id = channel_id or self._generate_id(party_a, party_b)
        self.party_a = party_a
        self.party_b = party_b
        self.balance_a = balance_a
        self.balance_b = balance_b
        self.sequence = 0
        self.status = ChannelState.PENDING
        self.funding_tx_id = funding_tx_id
        self.closing_tx_id = None
        self.created_at = created_at or time.time()
        self.settled_at = None
        self.commitments = []  # Histórico de commitments (o último é o atual)

    def _generate_id(self, party_a: str, party_b: str) -> str:
        """Gera ID único do canal baseado nas partes."""
        raw = f"{party_a}{party_b}{time.time()}{CryptoUtils.generate_nonce()}"
        return CryptoUtils.sha256(raw)

    @property
    def total_balance(self) -> float:
        """Saldo total bloqueado no canal."""
        return self.balance_a + self.balance_b

    @property
    def latest_commitment(self) -> Optional[CommitmentTransaction]:
        """Retorna o commitment mais recente."""
        return self.commitments[-1] if self.commitments else None

    def create_commitment(self, new_balance_a: float, new_balance_b: float,
                          pending_htlcs: list = None) -> CommitmentTransaction:
        """
        Cria um NOVO commitment transaction com saldos atualizados.
        O sequence é incrementado para prevenir replay de estados antigos.
        """
        if abs(new_balance_a + new_balance_b - self.total_balance) > 0.0001:
            raise ValueError(
                f"Saldo total inconsistente: {new_balance_a} + {new_balance_b} "
                f"!= {self.total_balance}"
            )

        self.sequence += 1
        commitment = CommitmentTransaction(
            channel_id=self.channel_id,
            sequence=self.sequence,
            balance_a=new_balance_a,
            balance_b=new_balance_b,
            pending_htlcs=pending_htlcs or [],
        )
        self.commitments.append(commitment)
        self.balance_a = new_balance_a
        self.balance_b = new_balance_b
        return commitment

    def sign_commitment(self, commitment: CommitmentTransaction,
                        private_key_pem: str, is_party_a: bool) -> str:
        """Assina um commitment com a chave privada de uma das partes."""
        sig = CryptoUtils.sign_p2p_message(private_key_pem, commitment.to_dict())
        if is_party_a:
            commitment.signature_a = sig
        else:
            commitment.signature_b = sig
        return sig

    def is_fully_signed(self, commitment: CommitmentTransaction) -> bool:
        """Verifica se o commitment está assinado por ambas as partes."""
        return bool(commitment.signature_a and commitment.signature_b)

    def can_close(self) -> bool:
        """Verifica se o canal pode ser fechado (tem funding + commitments)."""
        return (self.status == ChannelState.OPEN and
                len(self.commitments) > 0 and
                self.is_fully_signed(self.latest_commitment))

    def settle(self, closing_tx_id: str, coop: bool = True):
        """Finaliza o canal na blockchain."""
        self.status = ChannelState.CLOSING_COOP if coop else ChannelState.CLOSING_FORCE
        self.closing_tx_id = closing_tx_id
        self.settled_at = time.time()

    def close(self):
        """Marca o canal como fechado."""
        self.status = ChannelState.CLOSED

    def to_dict(self) -> dict:
        return {
            'channel_id': self.channel_id,
            'party_a': self.party_a,
            'party_b': self.party_b,
            'balance_a': self.balance_a,
            'balance_b': self.balance_b,
            'total_balance': self.total_balance,
            'sequence': self.sequence,
            'status': self.status.value,
            'funding_tx_id': self.funding_tx_id,
            'closing_tx_id': self.closing_tx_id,
            'created_at': self.created_at,
            'settled_at': self.settled_at,
            'commitments_count': len(self.commitments),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PaymentChannel':
        ch = cls(
            party_a=data['party_a'],
            party_b=data['party_b'],
            balance_a=data.get('balance_a', 0),
            balance_b=data.get('balance_b', 0),
            channel_id=data.get('channel_id'),
            funding_tx_id=data.get('funding_tx_id'),
            created_at=data.get('created_at'),
        )
        ch.sequence = data.get('sequence', 0)
        status_str = data.get('status', 'pending')
        for s in ChannelState:
            if s.value == status_str:
                ch.status = s
                break
        ch.closing_tx_id = data.get('closing_tx_id')
        ch.settled_at = data.get('settled_at')
        return ch

    def __str__(self) -> str:
        return (f"Channel({self.channel_id[:12]}... | "
                f"{self.party_a[:10]}... ⇄ {self.party_b[:10]}... | "
                f"Bal: {self.balance_a:.2f}/{self.balance_b:.2f} | "
                f"Seq: {self.sequence} | {self.status.value})")
'''

files['lightning/htlc.py'] = '''"""
HTLC — Hashed TimeLock Contract.
Permite pagamentos condicionais com hash lock + time lock.
"""

import time
import json
from typing import Optional
from core.crypto_utils import CryptoUtils


class HTLCStatus:
    """Estados possíveis de um HTLC."""
    PENDING = "pending"
    CLAIMED = "claimed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class HTLC:
    """
    Hashed TimeLock Contract.

    Um HTLC permite que o remetente bloqueie fundos condicionados a:
    1. O destinatário revelar o PREIMAGE (hash lock) dentro do prazo, OU
    2. O remetente recuperar os fundos após o timelock expirar

    Isso permite roteamento confiável: Alice→Bob→Carol
    Alice promete pagar Bob se ele provar que pagou Carol (revelando o segredo).
    """

    def __init__(self, channel_id: str, sender: str, receiver: str,
                 amount: float, hash_lock: str, timelock: int,
                 htlc_id: str = None, preimage: str = None,
                 status: str = None, created_at: float = None):
        self.channel_id = channel_id
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.hash_lock = hash_lock     # SHA-256(preimage)
        self.timelock = timelock       # Block height para expirar
        self.htlc_id = htlc_id or self._generate_id()
        self.preimage = preimage       # Revelado quando o HTLC é claimed
        self.status = status or HTLCStatus.PENDING
        self.created_at = created_at or time.time()

    def _generate_id(self) -> str:
        """Gera ID único para este HTLC."""
        raw = f"{self.channel_id}{self.hash_lock}{self.amount}{time.time()}"
        return CryptoUtils.sha256(raw)

    def claim(self, preimage: str) -> bool:
        """
        Tenta reivindicar o HTLC revelando o preimage.
        O preimage deve corresponder ao hash_lock (SHA-256).
        """
        if self.status != HTLCStatus.PENDING:
            return False
        if CryptoUtils.sha256(preimage) != self.hash_lock:
            return False
        self.preimage = preimage
        self.status = HTLCStatus.CLAIMED
        return True

    def refund(self) -> bool:
        """Recupera os fundos do HTLC (após timelock expirar)."""
        if self.status != HTLCStatus.PENDING:
            return False
        self.status = HTLCStatus.REFUNDED
        return True

    def is_expired(self, current_height: int) -> bool:
        """Verifica se o timelock expirou (não pode mais ser claimed)."""
        return current_height >= self.timelock

    def to_dict(self) -> dict:
        return {
            'htlc_id': self.htlc_id,
            'channel_id': self.channel_id,
            'sender': self.sender,
            'receiver': self.receiver,
            'amount': self.amount,
            'hash_lock': self.hash_lock,
            'timelock': self.timelock,
            'preimage': self.preimage,
            'status': self.status,
            'created_at': self.created_at,
        }

    @classmethod
    def create(cls, channel_id: str, sender: str, receiver: str,
               amount: float, secret: str, timelock: int) -> 'HTLC':
        """
        Cria um novo HTLC a partir de um SEGREDO (não do hash).
        Automaticamente calcula o hash_lock = SHA-256(secret).
        O secret deve ser guardado em sigilo pelo receiver.
        """
        hash_lock = CryptoUtils.sha256(secret)
        return cls(
            channel_id=channel_id,
            sender=sender,
            receiver=receiver,
            amount=amount,
            hash_lock=hash_lock,
            timelock=timelock,
        )

    def __str__(self) -> str:
        return (f"HTLC({self.htlc_id[:12]}... | "
                f"{self.amount:.2f} KUR | {self.hash_lock[:12]}... | "
                f"TL: {self.timelock} | {self.status})")
'''

files['lightning/channel_manager.py'] = '''"""
Gerenciador de Canais de Pagamento.
Gerencia o ciclo de vida completo: abertura, atualização, fechamento.
"""

import time
import json
from typing import Dict, List, Optional, Tuple
from core.crypto_utils import CryptoUtils
from .channel import PaymentChannel, ChannelState, CommitmentTransaction
from .htlc import HTLC, HTLCStatus


class ChannelManager:
    """
    Gerencia todos os canais de pagamento da rede Lightning.

    Responsabilidades:
    - Criar canais (funding on-chain)
    - Atualizar saldos (commitments off-chain)
    - Gerenciar HTLCs intra-canal
    - Fechar canais (cooperativo ou force-close)
    """

    def __init__(self):
        self.channels: Dict[str, PaymentChannel] = {}
        self._pending_htlcs: Dict[str, List[HTLC]] = {}  # channel_id -> HTLCs

    # ─── Criação de Canais ───────────────────────────────────────

    def create_channel(self, party_a: str, party_b: str,
                       amount_a: float, amount_b: float,
                       funding_tx_id: str = None) -> PaymentChannel:
        """
        Cria um novo canal de pagamento entre duas partes.

        Args:
            party_a: Endereço da parte A
            party_b: Endereço da parte B
            amount_a: Valor depositado pela parte A
            amount_b: Valor depositado pela parte B
            funding_tx_id: ID da transação de funding on-chain

        Returns:
            PaymentChannel criado
        """
        if party_a == party_b:
            raise ValueError("Não é possível criar canal consigo mesmo")

        channel = PaymentChannel(
            party_a=party_a,
            party_b=party_b,
            balance_a=amount_a,
            balance_b=amount_b,
            funding_tx_id=funding_tx_id,
        )
        channel.status = ChannelState.OPEN

        # Cria o commitment inicial (gênese do canal)
        channel.create_commitment(amount_a, amount_b)
        self._pending_htlcs[channel.channel_id] = []
        self.channels[channel.channel_id] = channel
        return channel

    # ─── Atualização de Saldos ───────────────────────────────────

    def update_balance(self, channel_id: str,
                       new_balance_a: float, new_balance_b: float,
                       sign_a: str = None, sign_b: str = None) -> CommitmentTransaction:
        """
        Atualiza os saldos do canal com um novo commitment.

        O canal é atualizado criando um NOVO commitment com saldos
        alterados. Ambas as partes precisam assinar o novo estado.
        O sequence number previne replay de estados antigos.
        """
        channel = self._get_channel(channel_id)
        if channel.status != ChannelState.OPEN:
            raise ValueError(f"Canal {channel_id[:12]}... não está aberto")

        # Cria novo commitment
        pending = self._pending_htlcs.get(channel_id, [])
        commitment = channel.create_commitment(new_balance_a, new_balance_b, pending)

        # Aplica assinaturas se fornecidas
        if sign_a:
            commitment.signature_a = sign_a
        if sign_b:
            commitment.signature_b = sign_b

        return commitment

    def sign_commitment(self, channel_id: str, commitment_hash: str,
                        private_key_pem: str, is_party_a: bool) -> str:
        """Assina um commitment específico do canal."""
        channel = self._get_channel(channel_id)
        for c in channel.commitments:
            if c.hash == commitment_hash:
                return channel.sign_commitment(c, private_key_pem, is_party_a)
        raise ValueError(f"Commitment {commitment_hash[:12]}... não encontrado")

    # ─── Gerenciamento de HTLCs ──────────────────────────────────

    def add_htlc(self, channel_id: str, htlc: HTLC):
        """Adiciona um HTLC pendente a um canal."""
        channel = self._get_channel(channel_id)
        if channel.status != ChannelState.OPEN:
            raise ValueError("Canal não está aberto para HTLCs")

        # Verifica se o remetente é uma das partes do canal
        if htlc.sender not in (channel.party_a, channel.party_b):
            raise ValueError("Remetente do HTLC não é parte do canal")
        if htlc.receiver not in (channel.party_a, channel.party_b):
            raise ValueError("Destinatário do HTLC não é parte do canal")

        # Verifica saldo disponível
        sender_balance = (channel.balance_a if htlc.sender == channel.party_a
                          else channel.balance_b)
        if sender_balance < htlc.amount:
            raise ValueError(
                f"Saldo insuficiente: {sender_balance:.2f} < {htlc.amount:.2f}"
            )

        self._pending_htlcs.setdefault(channel_id, []).append(htlc)

    def claim_htlc(self, channel_id: str, htlc_id: str,
                   preimage: str) -> bool:
        """
        Reivindica um HTLC revelando o preimage.
        O preimage deve corresponder ao hash_lock do HTLC.
        """
        htlc = self._find_htlc(channel_id, htlc_id)
        if not htlc:
            return False
        if not htlc.claim(preimage):
            return False

        # Transfere os fundos: do sender para o receiver
        channel = self._get_channel(channel_id)
        if htlc.sender == channel.party_a:
            channel.balance_a -= htlc.amount
            channel.balance_b += htlc.amount
        else:
            channel.balance_b -= htlc.amount
            channel.balance_a += htlc.amount

        return True

    def refund_htlc(self, channel_id: str, htlc_id: str) -> bool:
        """Reembolsa um HTLC expirado (sender recupera os fundos)."""
        htlc = self._find_htlc(channel_id, htlc_id)
        if not htlc:
            return False
        return htlc.refund()

    def get_channel_htlcs(self, channel_id: str) -> List[HTLC]:
        """Retorna todos os HTLCs de um canal."""
        return list(self._pending_htlcs.get(channel_id, []))

    # ─── Fechamento de Canais ────────────────────────────────────

    def close_channel_coop(self, channel_id: str, settlement_tx_id: str):
        """
        Fechamento cooperativo: ambas as partes concordam com o saldo final.
        O commitment MAIS RECENTE (maior sequence) é o estado válido.
        """
        channel = self._get_channel(channel_id)
        if not channel.can_close():
            raise ValueError("Canal não pode ser fechado (sem commitments assinados)")

        channel.settle(settlement_tx_id, coop=True)

    def close_channel_force(self, channel_id: str, settlement_tx_id: str):
        """
        Force-close: uma parte transmite o último commitment on-chain.
        A outra parte tem uma janela de disputa para enviar um commitment
        mais recente (com maior sequence).
        """
        channel = self._get_channel(channel_id)
        if channel.status != ChannelState.OPEN:
            raise ValueError(f"Canal {channel_id[:12]}... não está aberto")

        channel.settle(settlement_tx_id, coop=False)

    def settle_channel(self, channel_id: str):
        """Marca o canal como liquidado na blockchain."""
        channel = self._get_channel(channel_id)
        channel.close()

    def dispute_channel(self, channel_id: str,
                        commitment: CommitmentTransaction) -> bool:
        """
        Resolve disputa: se um commitment com sequence MAIOR que o atual
        for apresentado, ele substitui. Isso previne que uma parte
        transmita um estado desatualizado.
        """
        channel = self._get_channel(channel_id)
        if commitment.sequence > channel.sequence:
            channel.balance_a = commitment.balance_a
            channel.balance_b = commitment.balance_b
            channel.sequence = commitment.sequence
            channel.commitments.append(commitment)
            return True
        return False

    # ─── Consultas ───────────────────────────────────────────────

    def _get_channel(self, channel_id: str) -> PaymentChannel:
        """Busca canal por ID."""
        channel = self.channels.get(channel_id)
        if not channel:
            raise ValueError(f"Canal {channel_id[:12]}... não encontrado")
        return channel

    def _find_htlc(self, channel_id: str, htlc_id: str) -> Optional[HTLC]:
        """Busca HTLC por ID no canal."""
        for htlc in self._pending_htlcs.get(channel_id, []):
            if htlc.htlc_id == htlc_id:
                return htlc
        return None

    def get_channel(self, channel_id: str) -> Optional[PaymentChannel]:
        return self.channels.get(channel_id)

    def list_channels(self, status: str = None) -> List[PaymentChannel]:
        """Lista canais, opcionalmente filtrados por status."""
        channels = list(self.channels.values())
        if status:
            channels = [c for c in channels if c.status.value == status]
        return channels

    def get_channels_for_address(self, address: str) -> List[PaymentChannel]:
        """Retorna todos os canais que envolvem um endereço."""
        return [
            c for c in self.channels.values()
            if c.party_a == address or c.party_b == address
        ]

    def get_balance(self, address: str) -> Tuple[float, float]:
        """
        Retorna o saldo on-chain + off-chain de um endereço.

        Returns:
            Tuple (on_chain_balance, off_chain_locked)
        """
        on_chain = 0.0
        off_chain = 0.0
        for channel in self.channels.values():
            if channel.party_a == address:
                off_chain += channel.balance_a
            if channel.party_b == address:
                off_chain += channel.balance_b
        return on_chain, off_chain

    def to_dict(self) -> dict:
        return {
            'channels': [c.to_dict() for c in self.channels.values()],
            'total_channels': len(self.channels),
            'open_channels': sum(
                1 for c in self.channels.values()
                if c.status == ChannelState.OPEN
            ),
            'total_volume': sum(
                c.total_balance for c in self.channels.values()
            ),
        }
'''

files['lightning/router.py'] = '''"""
Roteador de Pagamentos — Pathfinding para Lightning Network.
Encontra caminhos através da rede de canais para pagamentos multi-hop.

Algoritmo: Bellman-Ford modificado (encontra caminho com capacidade suficiente).
"""

import json
from typing import Dict, List, Optional, Tuple
from core.crypto_utils import CryptoUtils
from .channel import PaymentChannel, ChannelState
from .channel_manager import ChannelManager
from .htlc import HTLC, HTLCStatus


class PaymentRouter:
    """
    Roteador de pagamentos na Lightning Network.

    Mantém um grafo da rede de canais e encontra caminhos
    para pagamentos multi-hop. Usa busca em largura (BFS)
    para encontrar o caminho mais curto com capacidade suficiente.
    """

    def __init__(self, channel_manager: ChannelManager):
        self.channel_manager = channel_manager
        self._graph = {}  # adjacency: address -> [(neighbor, channel_id, capacity)]

    def _build_graph(self):
        """Reconstrói o grafo a partir dos canais ativos."""
        self._graph = {}
        for channel in self.channel_manager.list_channels():
            if channel.status != ChannelState.OPEN:
                continue

            # A → B: capacidade = saldo de A
            self._graph.setdefault(channel.party_a, []).append((
                channel.party_b,
                channel.channel_id,
                channel.balance_a,
            ))
            # B → A: capacidade = saldo de B
            self._graph.setdefault(channel.party_b, []).append((
                channel.party_a,
                channel.channel_id,
                channel.balance_b,
            ))

    def find_path(self, sender: str, receiver: str,
                  amount: float, max_hops: int = 5) -> List[Tuple[str, str, float]]:
        """
        Encontra um caminho do sender ao receiver com capacidade suficiente.

        Usa BFS ponderado — busca o caminho mais curto (menos hops)
        onde cada canal tem saldo >= amount no sentido da transação.

        Args:
            sender: Endereço de origem
            receiver: Endereço de destino
            amount: Quantidade a pagar
            max_hops: Número máximo de hops (incluindo destino)

        Returns:
            Lista de (from_address, channel_id, capacity) representando o caminho,
            ou lista vazia se não encontrar caminho.
        """
        if sender == receiver:
            raise ValueError("Pagamento para si mesmo não faz sentido via LN")

        self._build_graph()

        if sender not in self._graph:
            return []
        if receiver not in self._graph:
            return []

        # BFS: (current_node, path)
        queue = [(sender, [])]
        visited = {sender}

        while queue:
            current, path = queue.pop(0)

            for neighbor, channel_id, capacity in self._graph.get(current, []):
                if capacity < amount:
                    continue  # Canal sem saldo suficiente

                new_path = path + [(current, channel_id, neighbor)]

                if neighbor == receiver:
                    return new_path

                if neighbor not in visited and len(new_path) < max_hops:
                    visited.add(neighbor)
                    queue.append((neighbor, new_path))

        return []  # Caminho não encontrado

    def get_network_graph(self) -> dict:
        """
        Retorna o grafo completo da rede para visualização/API.

        Returns:
            Dict com nós e arestas
        """
        self._build_graph()
        nodes = set()
        edges = []

        for addr, neighbors in self._graph.items():
            nodes.add(addr)
            for neighbor, channel_id, capacity in neighbors:
                channel = self.channel_manager.get_channel(channel_id)
                if channel:
                    edges.append({
                        'source': addr,
                        'target': neighbor,
                        'channel_id': channel_id,
                        'capacity': capacity,
                        'balance_a': channel.balance_a,
                        'balance_b': channel.balance_b,
                    })

        return {
            'nodes': list(nodes),
            'edges': edges,
            'channel_count': len(edges),
            'node_count': len(nodes),
        }

    def get_route_summary(self, path: List[Tuple[str, str, float]]) -> dict:
        """Gera um resumo legível do caminho encontrado."""
        if not path:
            return {'hops': [], 'total_hops': 0}

        hops = []
        for i, (from_addr, channel_id, to_addr) in enumerate(path):
            channel = self.channel_manager.get_channel(channel_id)
            hops.append({
                'hop': i + 1,
                'from': from_addr[:16] + '...',
                'to': to_addr[:16] + '...',
                'channel': channel_id[:12] + '...',
                'capacity': channel.balance_a if channel and channel.party_a == from_addr else (channel.balance_b if channel else 0),
            })

        return {
            'hops': hops,
            'total_hops': len(hops),
            'path': [(f, c, t) for f, c, t in path],
        }
'''

files['lightning/lightning_network.py'] = '''"""
LightningNetwork — Camada principal da Lightning Network.
Integra canais, HTLCs e roteamento com a blockchain on-chain.
"""

import time
import json
import threading
from typing import Dict, List, Optional, Tuple, Callable
from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from .channel import PaymentChannel, ChannelState, CommitmentTransaction
from .htlc import HTLC, HTLCStatus
from .channel_manager import ChannelManager
from .router import PaymentRouter


class LightningNetwork:
    """
    Camada principal da Lightning Network.

    Integra:
    - ChannelManager: ciclo de vida dos canais
    - PaymentRouter: pathfinding para pagamentos
    - Blockchain: funding/settlement on-chain
    - Sistema de eventos: notificações em tempo real

    Esta classe é o ponto de entrada para toda a funcionalidade LN.
    """

    # Prefixo especial para transações de funding LN
    FUNDING_PREFIX = "ln_funding:"
    SETTLEMENT_PREFIX = "ln_settlement:"

    def __init__(self, blockchain=None, node_address: str = None,
                 private_key_pem: str = None):
        """
        Args:
            blockchain: Instância da Blockchain KuramaChain
            node_address: Endereço do nó local
            private_key_pem: Chave privada do nó local (para assinar)
        """
        self.blockchain = blockchain
        self.node_address = node_address
        self.private_key_pem = private_key_pem

        self.channel_manager = ChannelManager()
        self.router = PaymentRouter(self.channel_manager)

        # Callbacks de eventos
        self._callbacks: Dict[str, List[Callable]] = {
            'channel_opened': [],
            'channel_closed': [],
            'payment_sent': [],
            'payment_received': [],
            'htlc_claimed': [],
        }
        self._lock = threading.Lock()

    # ─── Eventos ─────────────────────────────────────────────────

    def on(self, event: str, callback: Callable):
        """Registra callback para um evento LN."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
        return self

    def _emit(self, event: str, **kwargs):
        """Dispara evento."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception as e:
                print(f"[LN] Erro no callback '{event}': {e}")

    # ─── Abertura de Canal ───────────────────────────────────────

    def open_channel(self, party_a: str, party_b: str,
                     amount_a: float, amount_b: float,
                     sign_a: str = None, sign_b: str = None) -> dict:
        """
        Abre um canal de pagamento entre duas partes.

        O funding é feito criando uma transação especial na blockchain
        que bloqueia os KUR das duas partes no canal.

        Args:
            party_a: Endereço da parte A
            party_b: Endereço da parte B
            amount_a: Valor aportado pela parte A
            amount_b: Valor aportado pela parte B
            sign_a: Assinatura da parte A (para o commitment inicial)
            sign_b: Assinatura da parte B

        Returns:
            Dict com channel_id, funding_tx_id e detalhes do canal

        Raises:
            ValueError: Se saldo insuficiente ou parâmetros inválidos
        """
        with self._lock:
            # Verifica se não existe canal duplicado
            existing = self.channel_manager.get_channels_for_address(party_a)
            for ch in existing:
                if (ch.party_b == party_b and ch.status == ChannelState.OPEN):
                    raise ValueError(
                        f"Canal já existe entre {party_a[:12]}... e {party_b[:12]}..."
                    )

            # Verifica saldos na blockchain
            if self.blockchain:
                bal_a = self.blockchain.get_balance(party_a)
                if bal_a < amount_a:
                    raise ValueError(
                        f"Saldo insuficiente de A: {bal_a:.2f} < {amount_a:.2f}"
                    )
                bal_b = self.blockchain.get_balance(party_b)
                if bal_b < amount_b:
                    raise ValueError(
                        f"Saldo insuficiente de B: {bal_b:.2f} < {amount_b:.2f}"
                    )

            # Cria o canal off-chain
            channel = self.channel_manager.create_channel(
                party_a, party_b, amount_a, amount_b
            )

            # Cria funding transaction on-chain (marcada como LN)
            funding_tx_id = f"{self.FUNDING_PREFIX}{channel.channel_id}"

            # Se temos blockchain, cria transação de funding real
            if self.blockchain:
                self._create_funding_tx(channel, amount_a, amount_b)

            channel.funding_tx_id = funding_tx_id

            # Assina commitment inicial se chaves fornecidas
            commitment = channel.latest_commitment
            if sign_a:
                commitment.signature_a = sign_a
            if sign_b:
                commitment.signature_b = sign_b

            self._emit('channel_opened', channel=channel)
            return {
                'channel_id': channel.channel_id,
                'funding_tx_id': funding_tx_id,
                'party_a': party_a,
                'party_b': party_b,
                'balance_a': amount_a,
                'balance_b': amount_b,
                'total_balance': amount_a + amount_b,
                'commitment_hash': commitment.hash,
            }

    def _create_funding_tx(self, channel: PaymentChannel,
                           amount_a: float, amount_b: float):
        """Cria a transação de funding na blockchain."""
        if not self.blockchain:
            return

        # Cria transação que "trava" os fundos no canal
        # O receiver é marcado como ln_funding:<channel_id>
        # para identificar que são fundos bloqueados
        funding_receiver = f"{self.FUNDING_PREFIX}{channel.channel_id}"

        # Parte A deposita
        if amount_a > 0:
            self.blockchain.add_transaction(
                sender='SYSTEM_LN',
                receiver=funding_receiver,
                amount=amount_a,
                signature='LN_FUNDING',
                sender_address=channel.party_a,
                fee=0.001,
            )

        # Parte B deposita
        if amount_b > 0:
            self.blockchain.add_transaction(
                sender='SYSTEM_LN',
                receiver=funding_receiver,
                amount=amount_b,
                signature='LN_FUNDING',
                sender_address=channel.party_b,
                fee=0.001,
            )

    # ─── Atualização de Canal ────────────────────────────────────

    def update_channel_balance(self, channel_id: str,
                                new_balance_a: float, new_balance_b: float,
                                sign_a: str = None,
                                sign_b: str = None) -> dict:
        """
        Atualiza os saldos off-chain de um canal.

        Args:
            channel_id: ID do canal
            new_balance_a: Novo saldo da parte A
            new_balance_b: Novo saldo da parte B
            sign_a: Assinatura de A para o novo commitment
            sign_b: Assinatura de B para o novo commitment

        Returns:
            Dict com o novo commitment
        """
        commitment = self.channel_manager.update_balance(
            channel_id, new_balance_a, new_balance_b, sign_a, sign_b
        )
        return {
            'channel_id': channel_id,
            'sequence': commitment.sequence,
            'balance_a': commitment.balance_a,
            'balance_b': commitment.balance_b,
            'commitment_hash': commitment.hash,
        }

    # ─── Pagamentos via HTLC ─────────────────────────────────────

    def send_payment(self, sender: str, receiver: str, amount: float,
                     max_hops: int = 5) -> dict:
        """
        Envia um pagamento através da rede de canais.

        Fluxo:
        1. Encontra caminho do sender ao receiver
        2. Gera um segredo (preimage) que o receiver pode revelar
        3. Propaga HTLCs por todo o caminho
        4. Receiver reclama o HTLC final revelando o preimage
        5. HTLCs intermediários são liquidados em cascata

        Args:
            sender: Endereço de origem
            receiver: Endereço de destino
            amount: Quantidade a pagar
            max_hops: Número máximo de hops permitidos

        Returns:
            Dict com status do pagamento
        """
        # Gera segredo e hash
        secret = CryptoUtils.generate_nonce()
        hash_lock = CryptoUtils.sha256(secret)

        # Encontra caminho
        path = self.router.find_path(sender, receiver, amount, max_hops)
        if not path:
            return {
                'success': False,
                'error': 'Caminho não encontrado entre sender e receiver',
                'sender': sender[:16] + '...',
                'receiver': receiver[:16] + '...',
                'amount': amount,
            }

        # Define timelocks decrescentes (mais folgado no receiver)
        # Cada hop adiciona 10 blocos de buffer
        current_height = self._get_current_height()
        timelocks = [current_height + len(path) * 10]
        for i in range(len(path) - 1):
            timelocks.append(timelocks[0] - (i + 1) * 10)

        # Propaga HTLCs do receiver para o sender (construção reversa)
        # Na prática: sender -> hop1, hop1 -> hop2, ..., hopN -> receiver
        for i, (from_addr, channel_id, to_addr) in enumerate(path):
            htlc_timelock = current_height + (len(path) - i) * 10
            htlc = HTLC.create(
                channel_id=channel_id,
                sender=from_addr,
                receiver=to_addr,
                amount=amount,
                secret=secret if i == len(path) - 1 else CryptoUtils.generate_nonce(),
                timelock=htlc_timelock,
            )
            self.channel_manager.add_htlc(channel_id, htlc)

            # Atualiza saldo do canal para refletir o HTLC
            channel = self.channel_manager.get_channel(channel_id)
            if channel:
                if from_addr == channel.party_a:
                    new_a = channel.balance_a - amount
                    new_b = channel.balance_b
                else:
                    new_a = channel.balance_a
                    new_b = channel.balance_b - amount
                self.channel_manager.update_balance(channel_id, new_a, new_b)

        # Receiver reclama o último HTLC revelando o preimage
        if path:
            last_channel_id = path[-1][1]
            last_htlcs = self.channel_manager.get_channel_htlcs(last_channel_id)
            for htlc in last_htlcs:
                if (htlc.receiver == receiver and
                        htlc.hash_lock == hash_lock and
                        htlc.status == HTLCStatus.PENDING):
                    self.channel_manager.claim_htlc(
                        last_channel_id, htlc.htlc_id, secret
                    )
                    break

        self._emit('payment_sent', sender=sender, receiver=receiver,
                   amount=amount, path=path)
        return {
            'success': True,
            'payment_hash': hash_lock,
            'secret': secret,
            'sender': sender[:16] + '...',
            'receiver': receiver[:16] + '...',
            'amount': amount,
            'hops': len(path),
            'path_summary': self.router.get_route_summary(path),
        }

    def claim_payment(self, htlc_id: str, preimage: str,
                      channel_id: str = None) -> bool:
        """
        Reclama um pagamento recebido revelando o preimage.

        Args:
            htlc_id: ID do HTLC
            preimage: Segredo que prova o direito aos fundos
            channel_id: Canal específico (opcional)

        Returns:
            True se o HTLC foi reivindicado com sucesso
        """
        if channel_id:
            result = self.channel_manager.claim_htlc(channel_id, htlc_id, preimage)
            if result:
                self._emit('htlc_claimed', htlc_id=htlc_id)
                self._emit('payment_received', htlc_id=htlc_id)
            return result

        # Busca em todos os canais
        for cid in self.channel_manager.channels:
            if self.channel_manager.claim_htlc(cid, htlc_id, preimage):
                self._emit('htlc_claimed', htlc_id=htlc_id)
                self._emit('payment_received', htlc_id=htlc_id)
                return True
        return False

    # ─── Fechamento de Canal ─────────────────────────────────────

    def close_channel(self, channel_id: str, cooperative: bool = True) -> dict:
        """
        Fecha um canal de pagamento.

        Args:
            channel_id: ID do canal
            cooperative: Se True, fechamento cooperativo (ambos assinam)
                        Se False, force-close (unilateral)

        Returns:
            Dict com status do fechamento
        """
        channel = self.channel_manager.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Canal não encontrado'}

        # Cria settlement tx on-chain
        settlement_tx_id = f"{self.SETTLEMENT_PREFIX}{channel_id}"

        if cooperative:
            self.channel_manager.close_channel_coop(channel_id, settlement_tx_id)
        else:
            self.channel_manager.close_channel_force(channel_id, settlement_tx_id)

        self._emit('channel_closed', channel=channel, cooperative=cooperative)
        return {
            'success': True,
            'channel_id': channel_id,
            'settlement_tx_id': settlement_tx_id,
            'cooperative': cooperative,
            'balance_a': channel.balance_a,
            'balance_b': channel.balance_b,
            'total_balance': channel.total_balance,
        }

    def settle_channel(self, channel_id: str):
        """Finaliza a liquidação on-chain do canal."""
        self.channel_manager.settle_channel(channel_id)

    # ─── Consultas ───────────────────────────────────────────────

    def _get_current_height(self) -> int:
        """Retorna a altura atual da blockchain."""
        if self.blockchain:
            return len(self.blockchain.chain)
        return 0

    def get_channel(self, channel_id: str) -> Optional[dict]:
        """Retorna detalhes de um canal."""
        channel = self.channel_manager.get_channel(channel_id)
        return channel.to_dict() if channel else None

    def list_channels(self, status: str = None) -> List[dict]:
        """Lista canais."""
        return [
            c.to_dict() for c in self.channel_manager.list_channels(status)
        ]

    def get_channels_for(self, address: str) -> List[dict]:
        """Retorna canais de um endereço."""
        return [
            c.to_dict()
            for c in self.channel_manager.get_channels_for_address(address)
        ]

    def get_lightning_balance(self, address: str) -> dict:
        """Retorna saldo on-chain + off-chain de um endereço."""
        on_chain, off_chain = self.channel_manager.get_balance(address)
        total_on = self.blockchain.get_balance(address) if self.blockchain else 0
        return {
            'address': address[:16] + '...',
            'on_chain_available': total_on,
            'locked_in_channels': off_chain,
            'total_effective': total_on + off_chain,
        }

    def get_network_stats(self) -> dict:
        """Estatísticas da rede Lightning."""
        channels = self.channel_manager.list_channels()
        open_channels = [c for c in channels if c.status == ChannelState.OPEN]

        return {
            'total_channels': len(channels),
            'open_channels': len(open_channels),
            'total_volume': sum(c.total_balance for c in open_channels),
            'avg_channel_balance': (
                sum(c.total_balance for c in open_channels) / len(open_channels)
                if open_channels else 0
            ),
            'graph': self.router.get_network_graph(),
        }

    def to_dict(self) -> dict:
        return {
            'channel_manager': self.channel_manager.to_dict(),
            'network_graph': self.router.get_network_graph(),
            'node_address': self.node_address[:16] + '...' if self.node_address else None,
        }
'''

files['lightning/api.py'] = '''"""
API REST da Lightning Network.
Endpoints para gerenciar canais, pagamentos e consultar a rede.
"""

import json
from flask import Blueprint, jsonify, request
from functools import wraps
from core.crypto_utils import CryptoUtils


def create_lightning_blueprint(lightning_network=None):
    """
    Cria o blueprint Flask para a Lightning Network.

    Args:
        lightning_network: Instância de LightningNetwork

    Returns:
        Blueprint Flask com endpoints LN
    """
    bp = Blueprint('lightning', __name__, url_prefix='/api/lightning')

    def _get_ln():
        """Obtém a instância da Lightning Network."""
        if lightning_network is None:
            # Tenta obter do app
            try:
                from flask import current_app
                return current_app.lightning_network
            except (AttributeError, RuntimeError):
                return None
        return lightning_network

    # ─── Canais ───────────────────────────────────────────────────

    @bp.route('/channels', methods=['GET'])
    def list_channels():
        """Lista todos os canais de pagamento."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        status = request.args.get('status')
        channels = ln.list_channels(status)
        return jsonify({
            'channels': channels,
            'total': len(channels),
        }), 200

    @bp.route('/channels/<channel_id>', methods=['GET'])
    def get_channel(channel_id: str):
        """Obtém detalhes de um canal."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        channel = ln.get_channel(channel_id)
        if not channel:
            return jsonify({'error': 'Canal não encontrado'}), 404
        return jsonify(channel), 200

    @bp.route('/channels/open', methods=['POST'])
    def open_channel():
        """
        Abre um novo canal de pagamento.

        Body:
            party_a: Endereço da parte A
            party_b: Endereço da parte B
            amount_a: Valor aportado por A
            amount_b: Valor aportado por B
            sign_a: Assinatura de A (opcional)
            sign_b: Assinatura de B (opcional)
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        required = ['party_a', 'party_b']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({
                'error': f'Campos obrigatórios ausentes: {", ".join(missing)}'
            }), 400

        try:
            result = ln.open_channel(
                party_a=data['party_a'],
                party_b=data['party_b'],
                amount_a=float(data.get('amount_a', 0)),
                amount_b=float(data.get('amount_b', 0)),
                sign_a=data.get('sign_a'),
                sign_b=data.get('sign_b'),
            )
            return jsonify(result), 201
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    @bp.route('/channels/<channel_id>/update', methods=['POST'])
    def update_channel(channel_id: str):
        """
        Atualiza saldos de um canal (novo commitment).

        Body:
            balance_a: Novo saldo de A
            balance_b: Novo saldo de B
            sign_a: Assinatura de A
            sign_b: Assinatura de B
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        try:
            result = ln.update_channel_balance(
                channel_id=channel_id,
                new_balance_a=float(data.get('balance_a', 0)),
                new_balance_b=float(data.get('balance_b', 0)),
                sign_a=data.get('sign_a'),
                sign_b=data.get('sign_b'),
            )
            return jsonify(result), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    @bp.route('/channels/<channel_id>/close', methods=['POST'])
    def close_channel(channel_id: str):
        """
        Fecha um canal (cooperativo ou force-close).

        Body (opcional):
            cooperative: bool (default True)
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        cooperative = data.get('cooperative', True)

        try:
            result = ln.close_channel(channel_id, cooperative=cooperative)
            return jsonify(result), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    @bp.route('/channels/<channel_id>/settle', methods=['POST'])
    def settle_channel(channel_id: str):
        """Finaliza a liquidação de um canal na blockchain."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        try:
            ln.settle_channel(channel_id)
            return jsonify({
                'success': True,
                'channel_id': channel_id,
                'message': 'Canal liquidado na blockchain',
            }), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    # ─── Pagamentos ───────────────────────────────────────────────

    @bp.route('/payments/send', methods=['POST'])
    def send_payment():
        """
        Envia um pagamento via rede de canais.

        Body:
            sender: Endereço de origem
            receiver: Endereço de destino
            amount: Quantidade a pagar
            max_hops: Máximo de hops (opcional, default 5)
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        required = ['sender', 'receiver', 'amount']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({
                'error': f'Campos obrigatórios ausentes: {", ".join(missing)}'
            }), 400

        try:
            result = ln.send_payment(
                sender=data['sender'],
                receiver=data['receiver'],
                amount=float(data['amount']),
                max_hops=int(data.get('max_hops', 5)),
            )
            status = 200 if result.get('success') else 400
            return jsonify(result), status
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    @bp.route('/payments/claim', methods=['POST'])
    def claim_payment():
        """
        Reivindica um pagamento recebido revelando o preimage.

        Body:
            htlc_id: ID do HTLC
            preimage: Segredo para reivindicar
            channel_id: Canal específico (opcional)
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        if not data.get('htlc_id') or not data.get('preimage'):
            return jsonify({'error': 'htlc_id e preimage são obrigatórios'}), 400

        try:
            result = ln.claim_payment(
                htlc_id=data['htlc_id'],
                preimage=data['preimage'],
                channel_id=data.get('channel_id'),
            )
            return jsonify({
                'success': result,
                'message': 'Pagamento reivindicado!' if result else 'Falha ao reivindicar',
            }), 200
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    # ─── Consultas ────────────────────────────────────────────────

    @bp.route('/balance/<address>', methods=['GET'])
    def get_lightning_balance(address: str):
        """Saldo total (on-chain + off-chain) de um endereço."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        balance = ln.get_lightning_balance(address)
        return jsonify(balance), 200

    @bp.route('/channels/for/<address>', methods=['GET'])
    def get_channels_for(address: str):
        """Canais que envolvem um endereço."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        channels = ln.get_channels_for(address)
        return jsonify({
            'address': address[:16] + '...',
            'channels': channels,
            'total': len(channels),
        }), 200

    @bp.route('/graph', methods=['GET'])
    def network_graph():
        """Grafo da rede de canais para visualização."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        return jsonify(ln.get_network_stats().get('graph', {})), 200

    @bp.route('/stats', methods=['GET'])
    def network_stats():
        """Estatísticas da Lightning Network."""
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        return jsonify(ln.get_network_stats()), 200

    @bp.route('/route', methods=['POST'])
    def find_route():
        """
        Encontra um caminho entre dois endereços.

        Body:
            sender: Endereço de origem
            receiver: Endereço de destino
            amount: Quantidade a pagar
            max_hops: Máximo de hops (opcional)
        """
        ln = _get_ln()
        if not ln:
            return jsonify({'error': 'Lightning Network não disponível'}), 503

        data = request.get_json(silent=True) or {}
        if not data.get('sender') or not data.get('receiver'):
            return jsonify({'error': 'sender e receiver são obrigatórios'}), 400

        try:
            path = ln.router.find_path(
                sender=data['sender'],
                receiver=data['receiver'],
                amount=float(data.get('amount', 1)),
                max_hops=int(data.get('max_hops', 5)),
            )
            summary = ln.router.get_route_summary(path)
            return jsonify(summary), 200
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    return bp
'''

for path, content in files.items():
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Created: {path}")

import sys
sys.stdout.reconfigure(encoding='utf-8')
print("\nAll Lightning Network files created successfully!")
