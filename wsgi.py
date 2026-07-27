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

# ─── Registra Blueprint do Cassino ───────────────────────────────
try:
    from casino.backend.routes import create_casino_blueprint
    casino_bp = create_casino_blueprint(blockchain=blockchain)
    app.register_blueprint(casino_bp)
    print("[CASINO] Blueprint registrado em /api/casino/*")
except Exception as e:
    print(f"[WARN] Cassino: {e}")

# ─── Registra Blueprint de Produção (Polygon + Lucro) ───────────
prod_manager = None
try:
    from casino.backend.infrastructure.routes import create_production_blueprint
    from casino.backend.infrastructure.deposit_manager_production import ProductionDepositManager
    prod_manager = ProductionDepositManager()
    prod_bp = create_production_blueprint(prod_manager)
    app.register_blueprint(prod_bp)
    app.prod_manager = prod_manager
    print("[PRODUCTION] Blueprint de produção registrado em /api/v2/casino/*")
except Exception as e:
    print(f"[WARN] Blueprint de produção: {e}")

# Inicializa ProductionDepositManager
if prod_manager:
    try:
        prod_manager.initialize()
        print("[PRODUCTION] ProductionDepositManager inicializado!")
    except Exception as e:
        print(f"[WARN] ProductionDepositManager: {e}")

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

# ─── Registra Blueprint Polygon ──────────────────────────────────
try:
    from api.polygon_routes import polygon_bp
    app.register_blueprint(polygon_bp)
    print("[POLYGON] Blueprint do Polygon registrado")
except Exception as e:
    print(f"[WARN] Polygon: {e}")

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
