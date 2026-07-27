"""
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

        CORREÇÃO DUPLA CONTAGEM CASCADE:
        Quando um HTLC é criado via update_balance(), o saldo do sender
        JÁ foi reduzido (locked). Ao reivindicar, NÃO podemos reduzir
        novamente — apenas aumentar o saldo do receiver.

        Fluxo correto:
        1. update_balance(90, 50, [HTLC(10)]) → Alice=90, Bob=50
        2. claim_htlc(secret)                 → Alice=90, Bob=60 (só receiver aumenta!)

        Antes (bug): Alice=80, Bob=60 → Alice perdia 2× o valor!

        Após reivindicar, CRIA um NOVO commitment para capturar
        os saldos atualizados. Isso impede que uma parte maliciosa
        transmita um commitment pré-HTLC (mais vantajoso).
        """
        htlc = self._find_htlc(channel_id, htlc_id)
        if not htlc:
            return False
        if not htlc.claim(preimage):
            return False

        # Transfere os fundos: só o receiver ganha, sender não perde
        # pois o saldo do sender já foi reduzido quando o HTLC foi
        # criado e travado via update_balance() → create_commitment().
        channel = self._get_channel(channel_id)
        if htlc.sender == channel.party_a:
            new_a = channel.balance_a       # JÁ travado, não reduz de novo!
            new_b = channel.balance_b + htlc.amount
        else:
            new_a = channel.balance_a + htlc.amount
            new_b = channel.balance_b       # JÁ travado, não reduz de novo!

        # Remove HTLC da lista de pendentes e cria novo commitment
        pending = [h for h in self._pending_htlcs.get(channel_id, []) if h.htlc_id != htlc_id]
        self._pending_htlcs[channel_id] = pending
        channel.create_commitment(new_a, new_b, pending)

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
