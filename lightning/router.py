"""
Roteador de Pagamentos — Pathfinding para Lightning Network.
Encontra caminhos através da rede de canais para pagamentos multi-hop.

Algoritmo: Bellman-Ford modificado (encontra caminho com capacidade suficiente).
"""

import json
from collections import deque
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

        # BFS com deque (O(1) popleft vs O(n) pop(0))
        queue = deque([(sender, [])])
        visited = {sender}

        while queue:
            current, path = queue.popleft()

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
