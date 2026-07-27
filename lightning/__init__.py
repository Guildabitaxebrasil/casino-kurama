"""
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
