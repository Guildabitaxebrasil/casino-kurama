"""
WSGI entry point para Render / Gunicorn.
Exporta o objeto 'app' no nível do módulo para o gunicorn importar.

Uso: gunicorn wsgi:app --bind 0.0.0.0:$PORT
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Força UTF-8 no Windows ──────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

from api.routes import create_app
from core.blockchain import Blockchain
from core.wallet import Wallet
from config import DEFAULT_DIFFICULTY

# ─── Cria blockchain e carteira do nó ────────────────────────────
blockchain = Blockchain(difficulty=DEFAULT_DIFFICULTY)
wallet = Wallet()
miner_address = wallet.address

# ─── Cria a aplicação Flask ───────────────────────────────────────
app = create_app(
    blockchain=blockchain,
    node_address=miner_address,
    port=int(os.environ.get('PORT', 5000))
)

# ─── Registra Blueprint da Lightning Network ─────────────────────
try:
    from lightning.api import create_lightning_blueprint
    from lightning.lightning_network import LightningNetwork
    ln = LightningNetwork(
        blockchain=blockchain,
        node_address=miner_address,
        private_key_pem=wallet.private_key_pem,
    )
    ln_bp = create_lightning_blueprint(lightning_network=ln)
    app.register_blueprint(ln_bp)
    app.lightning_network = ln
    print("[LIGHTNING] Blueprint da LN registrado em /api/lightning/*")
except Exception as e:
    print(f"[WARN] Lightning: {e}")

# ─── Registra EVM (Contratos Inteligentes / DeFi) ────────────────
try:
    from evm.engine import EVMEngine
    from evm.rpc import create_evm_blueprint
    from config import EVM_AUTO_MINE, EVM_CHAIN_ID
    evm_engine = EVMEngine(auto_mine=EVM_AUTO_MINE)
    app.register_blueprint(create_evm_blueprint(evm_engine))
    app.evm_engine = evm_engine
    blockchain.on('on_block_mined', evm_engine.on_pow_block)
    print(f"[EVM] JSON-RPC eth_* registrado em /rpc (chain_id={EVM_CHAIN_ID})")
except Exception as e:
    print(f"[WARN] EVM: {e}")

# ─── Error handler ───────────────────────────────────────────────
@app.errorhandler(500)
def internal_error(error):
    import traceback
    traceback.print_exc()
    return {'error': 'Erro interno do servidor'}, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n[START] Servidor rodando na porta {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
