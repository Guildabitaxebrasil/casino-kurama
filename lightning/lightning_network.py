"""
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
        """
        Registra o funding do canal (off-chain por enquanto).

        NOTA: O funding on-chain completo (com transações reais assinadas
        pelas duas partes) será implementado em versão futura.
        Atualmente o LN opera 100% off-chain, com os saldos
        registrados apenas nos commitments assinados.

        O funding_tx_id é usado como referência para identificar
        o canal na blockchain quando o settlement on-chain for ativado.
        """
        if self.blockchain:
            print(f"[LN] Funding registrado: {amount_a:.2f} + {amount_b:.2f} "
                  f"KUR bloqueados no canal {channel.channel_id[:12]}..."
                  f" (off-chain, aguardando settlement on-chain)")

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

        Fluxo (CASCADE HTLC correto):
        1. Encontra caminho: sender -> hop1 -> hop2 -> ... -> receiver
        2. Gera um SEGREDO ÚNICO para todo o caminho
        3. Cria HTLCs com o MESMO hash_lock em cada hop:
           - sender -> hop1: HTLC(hash_lock, amount, timelock=50)
           - hop1 -> hop2: HTLC(hash_lock, amount, timelock=40)
           - ...
           - hopN -> receiver: HTLC(hash_lock, amount, timelock=10)
        4. Receiver reclama revelando o preimage (libera o último HTLC)
        5. HTLCs intermediários são liquidados em cascata reversa

        Args:
            sender: Endereço de origem
            receiver: Endereço de destino
            amount: Quantidade a pagar
            max_hops: Número máximo de hops permitidos

        Returns:
            Dict com status do pagamento
        """
        # Gera UM segredo e hash ÚNICO para TODO o caminho
        # O cascade HTLC exige que todos os hops usem o MESMO hash_lock.
        # Quando o receiver revela o preimage, todos os HTLCs
        # intermediários podem ser liquidados em sequência.
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

        current_height = self._get_current_height()

        # ─── Passo 1: Cria HTLCs em cada hop com o MESMO segredo ──
        # Timelocks decrescentes: o último hop (receiver) tem o
        # menor timelock, dando mais tempo para o receiver revelar
        # o preimage antes que os HTLCs expirem.
        created_htlcs = []  # Guarda HTLCs para cascade reverso
        for i, (from_addr, channel_id, to_addr) in enumerate(path):
            htlc_timelock = current_height + (len(path) - i) * 10

            # TODOS os HTLCs usam o MESMO secret/hash_lock!
            # O cascade funciona assim:
            #   Alice -> Bob: HTLC(hash_lock_X, timelock=30)
            #   Bob -> Carol: HTLC(hash_lock_X, timelock=20)
            # Quando Carol revela preimage_X, Bob descobre o segredo
            # e pode reivindicar o HTLC de Alice.
            htlc = HTLC.create(
                channel_id=channel_id,
                sender=from_addr,
                receiver=to_addr,
                amount=amount,
                secret=secret,  # MESMO secret para todos!
                timelock=htlc_timelock,
            )
            self.channel_manager.add_htlc(channel_id, htlc)
            created_htlcs.append(htlc)

            # Atualiza saldo disponível (fundo bloqueado pelo HTLC)
            # O saldo total do canal permanece o mesmo, mas a
            # parte disponível do sender diminui.
            channel = self.channel_manager.get_channel(channel_id)
            if channel:
                pending_htlcs = self.channel_manager.get_channel_htlcs(channel_id)
                if from_addr == channel.party_a:
                    new_a = channel.balance_a - amount
                    new_b = channel.balance_b
                else:
                    new_a = channel.balance_a
                    new_b = channel.balance_b - amount
                self.channel_manager.update_balance(
                    channel_id, new_a, new_b,
                )

        # ─── Passo 2: CASCADE REVERSO — Receiver reclama, depois
        #               cada hop intermediário reclama do anterior ─
        #
        # O cascade propaga o preimage em REVERSA:
        #   1. Receiver (Carol) reclama do último hop (Bob):
        #      'Aqui está o preimage! Me pague.'
        #      → Bob perde 10, Carol ganha 10
        #      → Bob AGORA CONHECE o preimage!
        #
        #   2. Bob (hop intermediário) reclama do anterior (Alice):
        #      'Eu também tenho o preimage! Me pague.'
        #      → Alice perde 10, Bob ganha 10
        #      → Bob fica com saldo inalterado (perdeu 10, ganhou 10)
        #
        #   3. Se houver mais hops, continua em REVERSA até o sender
        #
        # Efeito final:
        #   - Alice: -10 (pagou para Carol via Bob)
        #   - Bob:   0 (intermediário, recebeu de Alice e pagou Carol)
        #   - Carol: +10 (recebeu o pagamento)
        if path:
            # ─── Último hop: receiver reclama ────────────────────
            last_htlc = created_htlcs[-1]
            last_channel_id = path[-1][1]
            self.channel_manager.claim_htlc(
                last_channel_id, last_htlc.htlc_id, secret
            )

            # ─── Cascade reverso: hops intermediários ────────────
            # Cada hop que RECEBEU o pagamento do próximo agora tem
            # o preimage e pode reivindicar do hop anterior.
            # Caminhamos de trás para frente: penúltimo → primeiro.
            for i in range(len(path) - 2, -1, -1):
                channel_id = path[i][1]
                htlc_id = created_htlcs[i].htlc_id
                self.channel_manager.claim_htlc(
                    channel_id, htlc_id, secret
                )

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
