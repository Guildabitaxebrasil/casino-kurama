"""
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
        self._locked_htlc_total = 0.0  # Soma dos HTLCs pendentes no commitment atual

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

        O total do commitment inclui saldos disponíveis + HTLCs pendentes:
            available_a + available_b + sum(htlc_amounts) == total_balance

        Isso permite que fundos bloqueados em HTLCs sejam rastreados
        separadamente dos saldos disponíveis.
        """
        htlcs = pending_htlcs or []
        htlc_total = sum(h.amount for h in htlcs)
        expected_total = new_balance_a + new_balance_b + htlc_total

        # O total verdadeiro INCLUI HTLCs pendentes do commitment anterior.
        # self.total_balance (balance_a + balance_b) só reflete o disponível,
        # então somamos _locked_htlc_total para obter o total real.
        old_true_total = self.balance_a + self.balance_b + self._locked_htlc_total
        if abs(expected_total - old_true_total) > 0.0001:
            raise ValueError(
                f"Saldo total inconsistente: {new_balance_a} (A) + {new_balance_b} (B) "
                f"+ {htlc_total} (HTLCs pendentes) = {expected_total} "
                f"!= {old_true_total} (total real do canal = disponível + HTLCs antigos)"
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
        self._locked_htlc_total = htlc_total
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
