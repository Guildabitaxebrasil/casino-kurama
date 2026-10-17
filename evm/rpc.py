"""
JSON-RPC `eth_*` da EVM da KuramaChain.

É a interface que MetaMask / ethers.js / web3.js usam para falar com a
cadeia: consultar saldo, código de contrato, executar `eth_call`, enviar
transações assinadas, ler recibos, etc.

Expõe um único endpoint ``POST /rpc`` (JSON-RPC 2.0).
"""
import logging
from flask import Blueprint, jsonify, request

from config import EVM_RPC_CORS_ORIGIN

logger = logging.getLogger(__name__)


def _hex_to_int(value, default=0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith('0x') else int(value)
    return default


def _qty(value: int) -> str:
    """Formata um inteiro como quantidade hex (0x...)."""
    return hex(int(value))


def _data(value) -> str:
    """Formata bytes como dado hex (0x...)."""
    if value is None:
        return '0x'
    if isinstance(value, str):
        return value if value.startswith('0x') else '0x' + value
    return '0x' + bytes(value).hex()


# Teto de gas por seletor, usado só quando a requisição não traz `from` (sem
# sender não dá para simular allowance/saldo). Valores medidos na EVM local:
# approve ~46k, swapExactTokensForTokens ~134k.
_SELECTOR_GAS_CEILING = {
    '0x095ea7b3': 60_000,      # approve(address,uint256)
    '0x472b43f3': 250_000,     # swapExactTokensForTokens(uint256,uint256,address[],address)
    '0xa9059cbb': 60_000,      # transfer(address,uint256)
}


def _gas_ceiling(data: bytes) -> int:
    """Teto de gas para uma chamada sem `from` (fallback do eth_estimateGas)."""
    from config import EVM_DEFAULT_GAS, EVM_GAS_LIMIT

    if not data:
        return 21_000
    ceiling = _SELECTOR_GAS_CEILING.get('0x' + bytes(data[:4]).hex(), EVM_DEFAULT_GAS)
    return min(ceiling, EVM_GAS_LIMIT)


def create_evm_blueprint(engine) -> Blueprint:
    """
    Cria o Blueprint Flask do JSON-RPC EVM.

    Args:
        engine: instância de ``EVMEngine``.

    Returns:
        Blueprint com o endpoint ``POST /rpc``.
    """
    bp = Blueprint('evm_rpc', __name__)

    def _estimate_gas(tx: dict) -> str:
        """
        ``eth_estimateGas`` usado pela wallet antes de cada transação.

        Com ``from``, simula a mensagem com o **sender real** (allowance/saldo
        valem) e devolve intrínseco + execução. Sem ``from`` não há como simular
        corretamente, então devolve um teto conservador por seletor — a wallet
        cobra só o gas usado e o teto evita mandar tx sem gás (um swap do DEX
        gasta ~134k).
        """
        data = bytes.fromhex(_data(tx.get('data') or tx.get('input') or '0x')[2:])
        to = tx.get('to')
        sender = tx.get('from')
        value = _hex_to_int(tx.get('value'))
        if to and sender:
            return _qty(engine.estimate_gas(to, data, value=value, sender=sender))
        return _qty(_gas_ceiling(data))

    def _dispatch(method: str, params: list):
        if method == 'web3_clientVersion':
            return 'KuramaChain-EVM/v1.0 (py-evm, london)'
        if method == 'net_version':
            return str(engine.chain_id)
        if method == 'net_listening':
            return True
        if method == 'eth_chainId':
            return _qty(engine.chain_id)
        if method == 'eth_blockNumber':
            return _qty(engine.block_number)
        if method == 'eth_gasPrice':
            from config import EVM_DEFAULT_GAS_PRICE
            return _qty(EVM_DEFAULT_GAS_PRICE)
        if method == 'eth_maxPriorityFeePerGas':
            return _qty(0)
        if method == 'eth_accounts':
            return []
        if method == 'eth_syncing':
            return False
        if method == 'eth_getBalance':
            return _qty(engine.get_balance(params[0]))
        if method == 'eth_getTransactionCount':
            return _qty(engine.get_nonce(params[0]))
        if method == 'eth_getCode':
            return _data(engine.get_code(params[0]))
        if method == 'eth_call':
            tx = params[0] if params else {}
            out = engine.call(
                tx.get('to'), bytes.fromhex(_data(tx.get('data'))[2:] or ''),
                value=_hex_to_int(tx.get('value')),
            )
            return _data(out)
        if method == 'eth_estimateGas':
            return _estimate_gas(params[0] if params else {})
        if method == 'eth_sendRawTransaction':
            return engine.send_raw_transaction(params[0])
        if method == 'eth_getTransactionReceipt':
            receipt = engine.get_transaction_receipt(params[0])
            return receipt if receipt else None
        if method == 'eth_getTransactionByHash':
            return engine.get_transaction(params[0])
        if method == 'eth_getBlockByNumber':
            full = bool(params[1]) if len(params) > 1 else False
            return engine.get_block(params[0] if params else 'latest', full)
        if method == 'eth_getBlockByHash':
            full = bool(params[1]) if len(params) > 1 else False
            return engine.get_block(params[0], full)
        if method == 'eth_getBlockTransactionCountByNumber':
            return _qty(engine.get_block_transaction_count(params[0] if params else 'latest'))
        if method == 'eth_getBlockTransactionCountByHash':
            return _qty(engine.get_block_transaction_count(params[0]))
        if method == 'eth_getStorageAt':
            slot = params[1] if len(params) > 1 else '0x0'
            return _data(engine.get_storage_at(params[0], slot))
        if method == 'eth_getLogs':
            return engine.get_logs(params[0] if params else {})
        if method == 'eth_feeHistory':
            count = max(1, min(int(params[0], 16) if isinstance(params[0], str) else int(params[0]), 1024))
            newest = params[1] if len(params) > 1 else 'latest'
            head = engine.block_number
            newest_number = engine._block_number(newest, head, head)
            oldest = max(0, newest_number - count + 1)
            base = 10**9
            return {
                'oldestBlock': _qty(oldest),
                'baseFeePerGas': [_qty(base)] * (count + 1),
                'gasUsedRatio': [0.0] * count,
                'reward': [[_qty(0)] for _ in range(count)],
            }
        raise NotImplementedError(f'Método não suportado: {method}')

    @bp.after_request
    def _cors(response):
        # dApps no browser (ethers.js/web3.js) chamam /rpc de outra origem.
        response.headers['Access-Control-Allow-Origin'] = EVM_RPC_CORS_ORIGIN
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response

    @bp.route('/rpc', methods=['POST', 'OPTIONS'])
    def rpc():
        if request.method == 'OPTIONS':
            return ('', 204)
        payload = request.get_json(silent=True) or {}
        req_id = payload.get('id', 1)
        method = payload.get('method', '')
        params = payload.get('params', []) or []
        try:
            result = _dispatch(method, params)
            return jsonify({'jsonrpc': '2.0', 'id': req_id, 'result': result})
        except NotImplementedError as e:
            return jsonify({'jsonrpc': '2.0', 'id': req_id,
                            'error': {'code': -32601, 'message': str(e)}}), 200
        except Exception as e:  # erros de execução viram erro JSON-RPC
            logger.warning('[EVM-RPC] %s falhou: %s', method, e)
            return jsonify({'jsonrpc': '2.0', 'id': req_id,
                            'error': {'code': -32000, 'message': str(e)}}), 200

    return bp
