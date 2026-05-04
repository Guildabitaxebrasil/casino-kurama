"""
API REST da Blockchain.
Fornece endpoints HTTP para interagir com a blockchain.

Endpoints:
  GET  /chain              - Visualizar blockchain completa
  GET  /mine               - Minerar um novo bloco
  POST /transactions/new   - Criar nova transação
  GET  /wallet/new         - Criar nova carteira
  GET  /balance/<address>  - Consultar saldo
  GET  /nodes/register     - Registrar nós vizinhos
  GET  /nodes/resolve      - Executar consenso
  GET  /validate           - Validar blockchain
  GET  /stats              - Estatísticas da blockchain

Endpoints Explorer (/api/*):
  GET  /api/health              - Health check
  GET  /api/chain/since/<index> - Blocos a partir do índice
  GET  /api/blocks/<identifier> - Bloco por index ou hash
  GET  /api/transactions        - Transações (paginação/filtros)
  GET  /api/search?q=<term>     - Busca unificada
  GET  /api/nodes               - Lista nós com status
  POST /api/nodes/sync          - Trigger de consenso
  GET  /api/chart               - Dados para gráfico do Dashboard
  GET  /api/mempool             - Estatísticas da mempool

Endpoints de Rede (P2P):
  POST /blocks/new              - Receber novo bloco de outro nó
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from core.wallet import Wallet
from core.blockchain import Blockchain
from config import CORS_ORIGINS


def create_app(blockchain: Blockchain = None, node_address: str = None,
               port: int = 5000) -> Flask:
    """
    Cria e configura a aplicação Flask.

    Args:
        blockchain: Instância da blockchain (criada se None)
        node_address: Endereço do nó (carteira do minerador)
        port: Porta do servidor

    Returns:
        Aplicação Flask configurada
    """
    app = Flask(__name__)
    CORS(app, origins=CORS_ORIGINS)

    # Estado da aplicação
    app.blockchain = blockchain or Blockchain(difficulty=4)

    # Nós vizinhos na rede (URLs base)
    app.nodes = set()

    # Carteira do nó (para receber recompensas de mineração)
    if node_address:
        app.node_wallet_address = node_address
    else:
        wallet = Wallet()
        app.node_wallet_address = wallet.address
        # Salva chave privada no app para este nó
        app.node_private_key = wallet.private_key_pem
        app.node_public_key = wallet.public_key_pem

    # ─── Rotas da API ────────────────────────────────────────────

    @app.route('/chain', methods=['GET'])
    def get_chain():
        """
        Retorna a blockchain completa.
        Endpoint principal para visualizar todos os blocos e transações.
        """
        response = {
            'chain': [block.to_dict() for block in app.blockchain.chain],
            'length': len(app.blockchain.chain),
            'pending_transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ],
            'node_id': app.blockchain.node_id,
            'difficulty': app.blockchain.difficulty
        }
        return jsonify(response), 200

    @app.route('/mine', methods=['GET'])
    def mine():
        """
        Minera um novo bloco.
        Executa o Proof of Work e recompensa o minerador com coins.

        A transação coinbase (recompensa) é adicionada automaticamente
        ao bloco durante a mineração.
        """
        # Verifica se há transações para minerar
        if not app.blockchain.pending_transactions:
            return jsonify({
                'message': 'Nenhuma transação pendente para minerar. '
                           'Crie uma transação primeiro.',
                'pending': 0
            }), 400

        # Executa a mineração
        block = app.blockchain.mine_block(app.node_wallet_address)

        if not block:
            return jsonify({'message': 'Falha ao minerar bloco'}), 500

        response = {
            'message': 'Novo bloco minerado!',
            'block': block.to_dict(),
            'reward': app.blockchain.reward,
            'miner_address': app.node_wallet_address,
            'difficulty': app.blockchain.difficulty
        }
        return jsonify(response), 200

    @app.route('/transactions/new', methods=['POST'])
    def new_transaction():
        """
        Cria uma nova transação.

        Body (JSON):
        {
            "sender": "<chave pública do remetente>",
            "receiver": "<endereço do destinatário>",
            "amount": 10.0,
            "signature": "<assinatura hex>"   # Opcional
        }

        Se a transação não tem assinatura, ela é rejeitada.
        """
        data = request.get_json()

        # Valida campos obrigatórios
        required = ['sender', 'receiver', 'amount']
        if not data or not all(k in data for k in required):
            missing = [k for k in required if k not in (data or {})]
            return jsonify({
                'error': 'Campos obrigatórios ausentes',
                'required': required,
                'missing': missing
            }), 400

        try:
            # Adiciona a transação à pool de pendentes
            index = app.blockchain.add_transaction(
                sender=data['sender'],
                receiver=data['receiver'],
                amount=float(data['amount']),
                signature=data.get('signature'),
                sender_address=data.get('sender_address'),
                timestamp=data.get('timestamp')
            )

            return jsonify({
                'message': f'Transação adicionada. Será minerada no bloco #{index}',
                'transaction_index': index,
                'transaction_id': None  # Será definido pelo bloco
            }), 201

        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    @app.route('/wallet/new', methods=['GET'])
    def new_wallet():
        """
        Gera uma nova carteira (par de chaves).
        ATENÇÃO: A chave privada é mostrada uma única vez!
        """
        wallet = Wallet()
        return jsonify({
            'address': wallet.address,
            'public_key': wallet.public_key_pem,
            'private_key': wallet.private_key_pem,
            'warning': 'GUARDE SUA CHAVE PRIVADA EM SEGURANÇA! '
                       'Ela não pode ser recuperada.'
        }), 200

    @app.route('/balance/<address>', methods=['GET'])
    def get_balance(address: str):
        """
        Retorna o saldo de um endereço.

        O saldo é calculado varrendo toda a blockchain e somando
        todas as transações de entrada e saída.
        """
        balance = app.blockchain.get_balance(address)
        transactions = app.blockchain.get_transaction_history(address)

        return jsonify({
            'address': address,
            'balance': balance,
            'transactions_count': len(transactions),
            'transactions': transactions[-20:]  # Últimas 20 transações
        }), 200

    @app.route('/nodes/register', methods=['POST'])
    def register_nodes():
        """
        Registra nós vizinhos na rede.

        Body (JSON):
        {
            "nodes": ["http://localhost:5001", "http://localhost:5002"]
        }
        """
        data = request.get_json()

        if not data or 'nodes' not in data:
            return jsonify({
                'error': 'Forneça uma lista de "nodes" no body'
            }), 400

        nodes = data['nodes']
        registered = []
        duplicates = []
        invalid = []

        for node_url in nodes:
            # Valida URL
            if not node_url.startswith('http'):
                invalid.append(node_url)
                continue

            # Verifica duplicata
            if node_url in app.nodes:
                duplicates.append(node_url)
                continue

            app.nodes.add(node_url)
            registered.append(node_url)

        return jsonify({
            'message': f'{len(registered)} nó(s) registrado(s)',
            'total_nodes': len(app.nodes),
            'registered': registered,
            'duplicates': duplicates,
            'invalid': invalid
        }), 201

    @app.route('/nodes/resolve', methods=['GET'])
    def consensus():
        """
        Executa o algoritmo de consenso.
        Consulta todos os nós vizinhos e substitui a cadeia local
        pela mais longa e válida.

        Este é o mecanismo que mantém todos os nós sincronizados.
        """
        replaced = False
        other_chains = []

        # Coleta as cadeias de todos os nós vizinhos
        for node in app.nodes:
            try:
                response = requests.get(f'{node}/chain', timeout=2)
                if response.status_code == 200:
                    chain_data = response.json().get('chain', [])
                    other_chains.append(chain_data)
                    print(f"   Nó {node}: {len(chain_data)} blocos")
            except requests.exceptions.RequestException as e:
                print(f"   ⚠️  Nó {node} não respondeu: {e}")

        # Executa o consenso
        replaced = app.blockchain.resolve_conflicts(other_chains)

        return jsonify({
            'message': 'Cadeia substituída' if replaced else 'Cadeia mantida',
            'chain_length': len(app.blockchain.chain),
            'nodes_consulted': len(other_chains),
            'total_nodes': len(app.nodes),
            'replaced': replaced
        }), 200

    @app.route('/validate', methods=['GET'])
    def validate():
        """
        Valida a integridade de toda a blockchain.
        Verifica hashes, ligações e transações de todos os blocos.
        """
        is_valid = app.blockchain.is_chain_valid()

        # Informações detalhadas
        issues = []
        if not is_valid:
            for i, block in enumerate(app.blockchain.chain):
                if block.hash != block.calculate_hash():
                    issues.append({
                        'block': i,
                        'issue': 'hash_mismatch',
                        'expected': block.calculate_hash(),
                        'actual': block.hash
                    })

        return jsonify({
            'valid': is_valid,
            'blocks': len(app.blockchain.chain),
            'issues': issues if issues else None
        }), 200

    @app.route('/stats', methods=['GET'])
    def stats():
        """
        Retorna estatísticas da blockchain.
        Útil para monitoramento e debug.
        """
        return jsonify({
            'blocks': len(app.blockchain.chain),
            'pending_transactions': len(app.blockchain.pending_transactions),
            'difficulty': app.blockchain.difficulty,
            'reward': app.blockchain.reward,
            'node_id': app.blockchain.node_id,
            'miner_address': app.node_wallet_address,
            'peer_nodes': list(app.nodes),
            'genesis_hash': app.blockchain.chain[0].hash if app.blockchain.chain else None,
            'last_block_hash': app.blockchain.last_block.hash if app.blockchain.last_block else None,
            'chain_valid': app.blockchain.is_chain_valid()
        }), 200

    @app.route('/transactions/pending', methods=['GET'])
    def pending_transactions():
        """Retorna as transações pendentes (mempool)."""
        return jsonify({
            'count': len(app.blockchain.pending_transactions),
            'transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ]
        }), 200

    # ─── Endpoints de Rede (P2P) ───────────────────────────────────

    @app.route('/blocks/new', methods=['POST'])
    def receive_block():
        """
        Recebe um bloco minerado por outro nó.

        Body (JSON): bloco em formato dict (Block.to_dict())

        Valida o bloco e adiciona à cadeia local se for válido.
        Usado pelo NodeManager para broadcast entre nós.
        """
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Dados do bloco não fornecidos'}), 400

        try:
            # O nó pode enviar {'block': {...}} ou o dict diretamente
            block_data = data.get('block', data)
            from core.block import Block
            block = Block.from_dict(block_data, Transaction)

            # Verifica se o bloco já existe
            if block.index < len(app.blockchain.chain):
                existing = app.blockchain.chain[block.index]
                if existing.hash == block.hash:
                    return jsonify({'message': 'Bloco já existe', 'status': 'duplicate'}), 200

            # Valida o bloco
            # 1. Verifica se encaixa na cadeia local
            if block.index != len(app.blockchain.chain):
                return jsonify({
                    'error': f'Índice incorreto. Esperado {len(app.blockchain.chain)}, recebido {block.index}',
                    'local_length': len(app.blockchain.chain),
                    'block_index': block.index
                }), 409

            # 2. Verifica previous_hash
            last_block = app.blockchain.last_block
            if last_block and block.previous_hash != last_block.hash:
                return jsonify({
                    'error': 'Previous hash não corresponde ao último bloco local',
                    'expected': last_block.hash,
                    'received': block.previous_hash
                }), 409

            # 3. Verifica o hash do bloco
            if block.hash != block.calculate_hash():
                return jsonify({'error': 'Hash do bloco inválido'}), 400

            # 4. Verifica Proof of Work
            block_dict = block.to_dict()
            block_hash = CryptoUtils.hash_block(block_dict)
            block_difficulty = block.difficulty or app.blockchain.difficulty
            if not CryptoUtils.is_hash_valid(block_hash, block_difficulty):
                return jsonify({'error': 'Proof of Work inválido'}), 400

            # 5. Verifica transações
            if not block.is_valid_transactions():
                return jsonify({'error': 'Transações do bloco inválidas'}), 400

            # Adiciona o bloco à cadeia
            app.blockchain.chain.append(block)

            # Remove transações do bloco da mempool local
            block_tx_ids = {tx.transaction_id for tx in block.transactions}
            app.blockchain.pending_transactions = [
                tx for tx in app.blockchain.pending_transactions
                if tx.transaction_id not in block_tx_ids
            ]

            # Ajusta dificuldade
            app.blockchain.adjust_difficulty()

            return jsonify({
                'message': 'Bloco recebido e adicionado à cadeia local',
                'block_index': block.index,
                'block_hash': block.hash,
                'chain_length': len(app.blockchain.chain)
            }), 201

        except ValueError as e:
            return jsonify({'error': f'Erro ao processar bloco: {str(e)}'}), 400
        except Exception as e:
            return jsonify({'error': f'Erro interno: {str(e)}'}), 500

    # ═══════════════════════════════════════════════════════════════
    # ENDPOINTS DO EXPLORER (/api/*)
    # ═══════════════════════════════════════════════════════════════

    @app.route('/api/health', methods=['GET'])
    def api_health():
        """Health check para nós e frontend."""
        return jsonify({
            'status': 'ok',
            'node_id': app.blockchain.node_id,
            'blocks': len(app.blockchain.chain),
            'peer_count': len(app.nodes)
        }), 200

    @app.route('/api/chain/since/<int:index>', methods=['GET'])
    def api_chain_since(index: int):
        """
        Retorna blocos a partir do índice especificado.
        Útil para sincronização incremental do frontend.
        """
        blocks = []
        for block in app.blockchain.chain:
            if block.index > index:
                blocks.append(block.to_dict())
        return jsonify({
            'blocks': blocks,
            'count': len(blocks),
            'tip': len(app.blockchain.chain) - 1
        }), 200

    @app.route('/api/blocks/<identifier>', methods=['GET'])
    def api_block_by_id(identifier: str):
        """
        Retorna um bloco por índice numérico ou hash hexadecimal.
        Detecta automaticamente se é index ou hash.
        """
        # Tenta como índice numérico
        if identifier.isdigit():
            idx = int(identifier)
            if 0 <= idx < len(app.blockchain.chain):
                block = app.blockchain.chain[idx]
                return jsonify(block.to_dict()), 200
            return jsonify({'error': 'Bloco não encontrado', 'identifier': identifier}), 404

        # Tenta como hash (64 caracteres hex)
        if len(identifier) == 64:
            for block in app.blockchain.chain:
                if block.hash == identifier:
                    return jsonify(block.to_dict()), 200
            return jsonify({'error': 'Hash não encontrado', 'identifier': identifier}), 404

        return jsonify({'error': 'Identificador inválido. Use um número de índice ou hash de 64 caracteres.'}), 400

    @app.route('/api/transactions', methods=['GET'])
    def api_transactions():
        """
        Retorna todas as transações com paginação e filtros.

        Query params:
            page: Número da página (default: 1)
            per_page: Itens por página (default: 20)
            address: Filtrar por endereço
            min_amount: Valor mínimo
            max_amount: Valor máximo
        """
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        address = request.args.get('address', None, type=str)
        min_amount = request.args.get('min_amount', None, type=float)
        max_amount = request.args.get('max_amount', None, type=float)

        # Coleciona todas as transações com info do bloco
        all_txs = []
        for block in app.blockchain.chain:
            for tx in block.transactions:
                tx_dict = tx.to_dict() if hasattr(tx, 'to_dict') else tx
                tx_dict['block_index'] = block.index
                tx_dict['confirmed'] = True
                all_txs.append(tx_dict)

        # Aplica filtros
        if address:
            all_txs = [
                tx for tx in all_txs
                if tx.get('sender') == address
                or tx.get('receiver') == address
                or tx.get('sender_address') == address
            ]
        if min_amount is not None:
            all_txs = [tx for tx in all_txs if tx.get('amount', 0) >= min_amount]
        if max_amount is not None:
            all_txs = [tx for tx in all_txs if tx.get('amount', 0) <= max_amount]

        # Paginação
        total = len(all_txs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_txs = all_txs[start:end]

        return jsonify({
            'transactions': page_txs,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }), 200

    @app.route('/api/search', methods=['GET'])
    def api_search():
        """
        Busca unificada.
        Detecta se o termo é índice, hash ou endereço.

        Query params:
            q: Termo de busca
        """
        query = request.args.get('q', '').strip()

        if not query:
            return jsonify({'error': 'Forneça um termo de busca em ?q='}), 400

        # Tenta como índice de bloco
        if query.isdigit():
            idx = int(query)
            if 0 <= idx < len(app.blockchain.chain):
                return jsonify({
                    'type': 'block',
                    'data': app.blockchain.chain[idx].to_dict(),
                    'url': f'/explorer/{idx}'
                }), 200

        # Tenta como hash de bloco (64 hex chars)
        if len(query) == 64:
            for block in app.blockchain.chain:
                if block.hash == query:
                    return jsonify({
                        'type': 'block',
                        'data': block.to_dict(),
                        'url': f'/explorer/{block.index}'
                    }), 200

        # Tenta como endereço de carteira
        balance = app.blockchain.get_balance(query)
        if len(query) > 20:  # Endereços Base58 têm mais de 20 chars
            return jsonify({
                'type': 'address',
                'data': {
                    'address': query,
                    'balance': balance
                },
                'url': f'/wallet/{query}'
            }), 200

        return jsonify({'error': 'Nenhum resultado encontrado', 'query': query}), 404

    @app.route('/api/nodes', methods=['GET'])
    def api_nodes():
        """
        Lista todos os nós registrados com status de saúde.
        Pinga cada nó e retorna latência e status.
        """
        from config import NODE_HEALTH_TIMEOUT
        import time

        nodes_list = []

        # Adiciona o próprio nó
        nodes_list.append({
            'url': f'http://localhost:{port}',
            'active': True,
            'blocks': len(app.blockchain.chain),
            'node_id': app.blockchain.node_id,
            'latency_ms': 0,
            'is_self': True
        })

        # Verifica saúde dos nós vizinhos
        for node_url in app.nodes:
            try:
                start = time.time()
                resp = requests.get(f'{node_url}/api/health',
                                     timeout=NODE_HEALTH_TIMEOUT)
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    nodes_list.append({
                        'url': node_url,
                        'active': True,
                        'blocks': data.get('blocks', 0),
                        'node_id': data.get('node_id', 'unknown'),
                        'latency_ms': latency,
                        'is_self': False
                    })
                else:
                    nodes_list.append({
                        'url': node_url,
                        'active': False,
                        'blocks': 0,
                        'node_id': 'unknown',
                        'latency_ms': None,
                        'is_self': False
                    })
            except requests.exceptions.RequestException:
                nodes_list.append({
                    'url': node_url,
                    'active': False,
                    'blocks': 0,
                    'node_id': 'unknown',
                    'latency_ms': None,
                    'is_self': False
                })

        return jsonify({
            'nodes': nodes_list,
            'total': len(nodes_list),
            'active': sum(1 for n in nodes_list if n['active'])
        }), 200

    @app.route('/api/nodes/sync', methods=['POST'])
    def api_nodes_sync():
        """
        Executa consenso contra todos os nós vizinhos.
        Substitui a cadeia local pela mais longa e válida.
        """
        other_chains = []
        results = []

        for node_url in app.nodes:
            try:
                resp = requests.get(f'{node_url}/chain', timeout=2)
                if resp.status_code == 200:
                    chain_data = resp.json().get('chain', [])
                    other_chains.append(chain_data)
                    results.append({
                        'node': node_url,
                        'blocks': len(chain_data),
                        'status': 'ok'
                    })
                else:
                    results.append({
                        'node': node_url,
                        'blocks': 0,
                        'status': 'error'
                    })
            except requests.exceptions.RequestException as e:
                results.append({
                    'node': node_url,
                    'blocks': 0,
                    'status': f'failed: {str(e)[:50]}'
                })

        replaced = app.blockchain.resolve_conflicts(other_chains)

        return jsonify({
            'message': 'Cadeia substituída' if replaced else 'Cadeia mantida',
            'chain_length': len(app.blockchain.chain),
            'nodes_consulted': len(other_chains),
            'replaced': replaced,
            'results': results
        }), 200

    @app.route('/api/chart', methods=['GET'])
    def api_chart():
        """
        Retorna dados formatados para o gráfico do Dashboard.
        Inclui blocos recentes com contagem de transações,
        transações acumuladas e dificuldade.

        Query params:
            limit: Número de blocos a retornar (default: 50)
        """
        limit = request.args.get('limit', 50, type=int)
        limit = min(limit, 200)  # Máximo 200 blocos

        chain = app.blockchain.chain
        start = max(0, len(chain) - limit)
        chart_data = []
        cum_tx = 0

        for block in chain[start:]:
            tx_count = len(block.transactions)
            cum_tx += tx_count
            chart_data.append({
                'block': block.index,
                'timestamp': block.timestamp,
                'transactions': tx_count,
                'cumulativeTx': cum_tx,
                'difficulty': block.difficulty or 0,
            })

        return jsonify(chart_data), 200

    @app.route('/api/mempool', methods=['GET'])
    def api_mempool():
        """
        Retorna estatísticas detalhadas da mempool.
        """
        stats = app.blockchain.get_mempool_stats()
        return jsonify({
            **stats,
            'transactions': [
                tx.to_dict() for tx in app.blockchain.pending_transactions
            ]
        }), 200

    return app
