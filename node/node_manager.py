"""
Gerenciador de Nós (Node Manager).
Simula múltiplos nós rodando em paralelo, cada um com sua própria
blockchain e carteira. Permite testar o mecanismo de consenso.

Cada nó tem:
- Instância própria da blockchain
- Endereço na rede (URL)
- Carteira para receber recompensas
- Lista de nós vizinhos
"""
import json
import os
import threading
import time
import requests
from typing import Dict, List, Optional

from core.blockchain import Blockchain
from core.wallet import Wallet
from core.crypto_utils import CryptoUtils
from config import NODE_HEALTH_TIMEOUT, SYNC_INTERVAL


class NodeInfo:
    """
    Representa um nó na rede simulada.
    Armazena estado, configuração e carteira do nó.
    """

    def __init__(self, node_id: str, host: str = 'localhost', port: int = 5000):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.url = f'http://{host}:{port}'
        self.blockchain = Blockchain(difficulty=4)
        self.wallet = Wallet()
        self.active = False


class NodeManager:
    """
    Gerencia múltiplos nós para simular uma rede blockchain.

    Facilita:
    - Criação de múltiplos nós
    - Registro de nós vizinhos
    - Mineração distribuída
    - Testes de consenso
    """

    def __init__(self, base_port: int = 5000):
        """
        Inicializa o gerenciador de nós.

        Args:
            base_port: Porta base para o primeiro nó
        """
        self.base_port = base_port
        self.nodes: Dict[str, NodeInfo] = {}
        self.threads: Dict[str, threading.Thread] = {}

    def create_node(self, node_id: str = None, port: int = None,
                    difficulty: int = 4) -> NodeInfo:
        """
        Cria um novo nó na rede.

        Args:
            node_id: Identificador único (auto-gerado se None)
            port: Porta do servidor (auto-atribuída se None)

        Returns:
            Informações do nó criado
        """
        node_id = node_id or CryptoUtils.generate_node_id()[:8]
        port = port or (self.base_port + len(self.nodes))

        node = NodeInfo(node_id=node_id, port=port)
        node.blockchain = Blockchain(difficulty=difficulty)
        node.wallet = Wallet()

        self.nodes[node_id] = node
        print(f"🔧 Nó '{node_id}' criado em {node.url}")
        print(f"   Carteira: {node.wallet.address[:20]}...")

        return node

    def start_node(self, node_id: str) -> bool:
        """
        Inicia o servidor Flask de um nó em uma thread separada.

        Args:
            node_id: Identificador do nó

        Returns:
            True se iniciou com sucesso
        """
        if node_id not in self.nodes:
            print(f"❌ Nó '{node_id}' não encontrado")
            return False

        node = self.nodes[node_id]
        if node.active:
            print(f"⚠️  Nó '{node_id}' já está ativo")
            return False

        # Importa aqui para evitar circular imports
        from api.routes import create_app
        app = create_app(
            blockchain=node.blockchain,
            node_address=node.wallet.address,
            port=node.port
        )

        # Registra os vizinhos no app
        for other_id, other_node in self.nodes.items():
            if other_id != node_id and other_node.active:
                app.nodes.add(other_node.url)

        # Inicia em thread separada
        def run():
            print(f"🚀 Nó '{node_id}' rodando em {node.url}")
            print(f"   Endereço do minerador: {node.wallet.address[:20]}...")
            app.run(
                host=node.host,
                port=node.port,
                debug=False,
                use_reloader=False
            )

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.threads[node_id] = thread
        node.active = True

        # Pequena pausa para o servidor iniciar
        time.sleep(1)
        return True

    def stop_node(self, node_id: str) -> bool:
        """
        Para um nó (marca como inativo).
        Nota: Flask não tem shutdown programático fácil,
        então marcamos como inativo.

        Args:
            node_id: Identificador do nó
        """
        if node_id not in self.nodes:
            return False

        self.nodes[node_id].active = False
        print(f"🛑 Nó '{node_id}' parado")
        return True

    def register_neighbors(self):
        """
        Registra todos os nós ativos como vizinhos entre si.
        Cria uma rede completamente conectada via chamadas HTTP reais.
        """
        active_nodes = {
            nid: n for nid, n in self.nodes.items()
            if n.active
        }

        if len(active_nodes) < 2:
            print("⚠️  São necessários pelo menos 2 nós ativos")
            return

        print(f"🔗 Registrando {len(active_nodes)} nós como vizinhos via HTTP...")

        for nid, node in active_nodes.items():
            others = [
                other.url
                for other_id, other in active_nodes.items()
                if other_id != nid
            ]

            try:
                resp = requests.post(
                    f'{node.url}/nodes/register',
                    json={'nodes': others},
                    timeout=2
                )
                if resp.status_code == 201:
                    data = resp.json()
                    print(f"   ✅ {nid} → {data.get('total_nodes', 0)} vizinhos")
                else:
                    print(f"   ⚠️  {nid} → erro: {resp.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"   ❌ {nid} → falha: {e}")

        print("✅ Rede configurada com sucesso!")

    # ─── Health Check ────────────────────────────────────────────

    def check_node_health(self, node_url: str) -> dict:
        """
        Verifica a saúde de um nó via /api/health.

        Args:
            node_url: URL base do nó

        Returns:
            Dict com status, latência e informações
        """
        try:
            start = time.time()
            resp = requests.get(
                f'{node_url}/api/health',
                timeout=NODE_HEALTH_TIMEOUT
            )
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'url': node_url,
                    'active': True,
                    'blocks': data.get('blocks', 0),
                    'node_id': data.get('node_id', 'unknown'),
                    'latency_ms': latency
                }
        except requests.exceptions.RequestException:
            pass

        return {
            'url': node_url,
            'active': False,
            'blocks': 0,
            'node_id': 'unknown',
            'latency_ms': None
        }

    # ─── Broadcast ──────────────────────────────────────────────

    def broadcast_block(self, block_dict: dict):
        """
        Transmite um novo bloco para todos os nós ativos via POST.

        Args:
            block_dict: Dicionário do bloco a ser transmitido
        """
        for nid, node in self.nodes.items():
            if not node.active:
                continue
            try:
                requests.post(
                    f'{node.url}/blocks/new',
                    json={'block': block_dict},
                    timeout=1
                )
            except requests.exceptions.RequestException:
                pass

    def broadcast_transaction(self, tx_dict: dict):
        """
        Transmite uma nova transação para todos os nós ativos.

        Args:
            tx_dict: Dicionário da transação a ser transmitida
        """
        for nid, node in self.nodes.items():
            if not node.active:
                continue
            try:
                requests.post(
                    f'{node.url}/transactions/new',
                    json=tx_dict,
                    timeout=1
                )
            except requests.exceptions.RequestException:
                pass

    # ─── Sincronização em Background ────────────────────────────

    def _sync_loop(self, node_id: str):
        """
        Loop de sincronização em background.
        Periodicamente executa o consenso com os vizinhos.

        Args:
            node_id: ID do nó que deve executar o sync
        """
        node = self.nodes.get(node_id)
        if not node:
            return

        while node.active:
            try:
                # Busca cadeias dos vizinhos
                other_chains = []
                for other_id, other_node in self.nodes.items():
                    if other_id == node_id or not other_node.active:
                        continue
                    try:
                        resp = requests.get(
                            f'{other_node.url}/chain',
                            timeout=2
                        )
                        if resp.status_code == 200:
                            chain_data = resp.json().get('chain', [])
                            other_chains.append(chain_data)
                    except requests.exceptions.RequestException:
                        pass

                # Executa consenso
                if other_chains:
                    node.blockchain.resolve_conflicts(other_chains)

                time.sleep(SYNC_INTERVAL)
            except Exception:
                time.sleep(SYNC_INTERVAL)

    def start_background_sync(self, node_id: str):
        """
        Inicia a sincronização em background para um nó.

        Args:
            node_id: ID do nó
        """
        thread = threading.Thread(
            target=self._sync_loop,
            args=(node_id,),
            daemon=True
        )
        thread.start()
        print(f"🔄 Sincronização em background iniciada para {node_id}")

    def start_all_background_syncs(self):
        """Inicia sincronização em background para todos os nós ativos."""
        for nid, node in self.nodes.items():
            if node.active:
                self.start_background_sync(nid)

    def start_network(self, num_nodes: int = 3):
        """
        Cria e inicia uma rede completa de nós.

        Args:
            num_nodes: Número de nós na rede
        """
        print(f"\n{'='*60}")
        print(f"🌐 INICIANDO REDE BLOCKCHAIN COM {num_nodes} NÓS")
        print(f"{'='*60}\n")

        # Cria todos os nós
        for i in range(num_nodes):
            node_id = f"node_{i}"
            port = self.base_port + i
            self.create_node(node_id=node_id, port=port)

        # Inicia todos os nós
        for nid in self.nodes:
            self.start_node(nid)

        # Registra vizinhos
        self.register_neighbors()

        # Inicia sincronização em background
        self.start_all_background_syncs()

        print(f"\n{'='*60}")
        print("✅ REDE INICIADA COM SUCESSO!")
        print(f"{'='*60}")
        print(f"\n📋 Nós disponíveis:")
        for nid, node in self.nodes.items():
            print(f"   {nid}: {node.url}")
        print(f"\n💡 Dica: Use curl ou Postman para interagir com os nós.")
        print(f"   Exemplo: curl {self.nodes[list(self.nodes.keys())[0]].url}/chain")

    def get_network_stats(self) -> dict:
        """
        Retorna estatísticas de toda a rede.

        Returns:
            Dicionário com estatísticas de cada nó
        """
        stats = {}
        for nid, node in self.nodes.items():
            stats[nid] = {
                'url': node.url,
                'active': node.active,
                'blocks': len(node.blockchain.chain),
                'pending_tx': len(node.blockchain.pending_transactions),
                'difficulty': node.blockchain.difficulty,
                'balance': node.blockchain.get_balance(node.wallet.address),
                'wallet': node.wallet.address[:20] + '...'
            }
        return stats

    def print_network_status(self):
        """Imprime o status de todos os nós da rede."""
        print(f"\n{'='*60}")
        print("📊 STATUS DA REDE")
        print(f"{'='*60}")

        for nid, node in self.nodes.items():
            status = '🟢' if node.active else '🔴'
            balance = node.blockchain.get_balance(node.wallet.address)
            print(f"\n{status} {nid} ({node.url})")
            print(f"   Blocos: {len(node.blockchain.chain)} | "
                  f"Dificuldade: {node.blockchain.difficulty} | "
                  f"Pendentes: {len(node.blockchain.pending_transactions)}")
            print(f"   Saldo: {balance:.2f} coins")
            print(f"   Carteira: {node.wallet.address}")
