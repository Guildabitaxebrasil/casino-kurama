"""
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
