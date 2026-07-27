"""
Endpoints da API para rede Polygon (ERC-20 USDT).
Fornece saldo, transações e informações da rede Polygon.

Endpoints:
  GET  /api/polygon/info        - Informações da rede Polygon
  GET  /api/polygon/balance     - Saldo MATIC + USDT de um endereço
  GET  /api/polygon/transactions - Transações USDT recebidas
  GET  /api/polygon/tx/<tx_id>  - Detalhes de uma transação
"""
import os
import sys
import json
import time
from flask import Blueprint, jsonify, request

# Adiciona o path do casino ao sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'casino', 'backend'))

polygon_bp = Blueprint('polygon', __name__)

# Lazy-loaded PolygonClient
_polygon_client = None


def _get_polygon():
    """Retorna instância do PolygonClient (lazy init)."""
    global _polygon_client
    if _polygon_client is None:
        try:
            from infrastructure.polygon_client import PolygonClient
            _polygon_client = PolygonClient()
        except ImportError as e:
            raise RuntimeError(
                "PolygonClient não disponível. "
                "Instale web3: pip install web3"
            ) from e
    return _polygon_client


@polygon_bp.route('/api/polygon/info', methods=['GET'])
def polygon_info():
    """
    Retorna informações da rede Polygon configurada.

    Response:
    {
        "network": "amoy" | "mainnet",
        "chain_id": 80002 | 137,
        "rpc_url": "...",
        "usdt_contract": "0x...",
        "explorer_url": "https://amoy.polygonscan.com" | "https://polygonscan.com",
        "connected": true/false
    }
    """
    try:
        polygon = _get_polygon()
        w3 = polygon._get_web3()
        connected = w3.is_connected() if w3 else False
        chain_id = w3.eth.chain_id if connected else None

        network = polygon.network
        explorer = (
            'https://polygonscan.com' if network == 'mainnet'
            else 'https://amoy.polygonscan.com'
        )

        return jsonify({
            'network': network,
            'chain_id': chain_id,
            'rpc_url': polygon.rpc_url[:50] + '...' if polygon.rpc_url and len(polygon.rpc_url) > 50 else polygon.rpc_url,
            'usdt_contract': polygon.usdt_contract_addr,
            'explorer_url': explorer,
            'connected': connected,
            'block_number': w3.eth.block_number if connected else None,
        }), 200
    except Exception as e:
        return jsonify({
            'error': 'Erro ao obter informações da rede Polygon',
            'connected': False,
        }), 500


@polygon_bp.route('/api/polygon/balance', methods=['GET'])
def polygon_balance():
    """
    Retorna saldo MATIC + USDT de um endereço Polygon.

    Query params:
        address: Endereço EVM (0x...)

    Response:
    {
        "address": "0x...",
        "matic": 1.234,
        "usdt": 100.50,
        "network": "amoy"
    }
    """
    address = request.args.get('address', '').strip()
    if not address:
        return jsonify({'error': 'Parâmetro "address" é obrigatório'}), 400
    if not address.startswith('0x') or len(address) != 42:
        return jsonify({'error': 'Endereço EVM inválido (deve começar com 0x e ter 42 caracteres)'}), 400

    try:
        polygon = _get_polygon()
        matic = polygon.get_matic_balance(address)
        usdt = polygon.get_usdt_balance(address)

        return jsonify({
            'address': address,
            'matic': round(matic, 6),
            'usdt': round(usdt, 2),
            'network': polygon.network,
        }), 200
    except Exception as e:
        return jsonify({
            'address': address,
            'matic': 0,
            'usdt': 0,
            'network': 'unknown',
            'error': 'Erro ao consultar saldo Polygon',
        }), 500


@polygon_bp.route('/api/polygon/transactions', methods=['GET'])
def polygon_transactions():
    """
    Retorna transações USDT recebidas por um endereço.

    Query params:
        address: Endereço EVM (0x...)
        min_confirmations: Mínimo de confirmações (default: 1)
        limit: Máximo de transações (default: 50)

    Response:
    {
        "address": "0x...",
        "network": "amoy",
        "transactions": [
            {
                "tx_id": "0x...",
                "from": "0x...",
                "to": "0x...",
                "amount": 100.0,
                "block": 12345,
                "confirmations": 30,
                "timestamp": 1234567890
            }
        ],
        "total": 5
    }
    """
    address = request.args.get('address', '').strip()
    min_confs = request.args.get('min_confirmations', 1, type=int)
    limit = min(request.args.get('limit', 50, type=int), 200)

    if not address:
        return jsonify({'error': 'Parâmetro "address" é obrigatório'}), 400
    if not address.startswith('0x') or len(address) != 42:
        return jsonify({'error': 'Endereço EVM inválido'}), 400

    try:
        polygon = _get_polygon()
        txs = polygon.get_incoming_transactions(address, min_confirmations=min_confs)

        # Limita resultado
        txs = txs[:limit]

        return jsonify({
            'address': address,
            'network': polygon.network,
            'transactions': txs,
            'total': len(txs),
        }), 200
    except Exception as e:
        return jsonify({
            'address': address,
            'network': 'unknown',
            'transactions': [],
            'total': 0,
            'error': 'Erro ao consultar transações Polygon',
        }), 500


@polygon_bp.route('/api/polygon/tx/<tx_id>', methods=['GET'])
def polygon_tx_info(tx_id: str):
    """
    Retorna detalhes de uma transação Polygon.

    Path params:
        tx_id: Hash da transação (0x...)

    Response:
    {
        "tx_id": "0x...",
        "block": 12345,
        "timestamp": 1234567890,
        "from": "0x...",
        "to": "0x..."
    }
    """
    if not tx_id.startswith('0x'):
        return jsonify({'error': 'Hash de transação inválido'}), 400

    try:
        polygon = _get_polygon()
        info = polygon.get_transaction_info(tx_id)

        if info is None:
            return jsonify({'error': 'Transação não encontrada'}), 404

        return jsonify(info), 200
    except Exception as e:
        return jsonify({'error': 'Erro ao consultar transação'}), 500
