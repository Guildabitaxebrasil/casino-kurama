#!/usr/bin/env python3
"""
Script de inicializacao do servidor de desenvolvimento.
Inicia o servidor Flask com todos os blueprints registrados,
incluindo o blueprint de producao (/api/v2/casino/owner/*).

Uso:
    python start_dev.py [--port PORT]

O servidor inicia em http://localhost:5000
O frontend Vite deve ser iniciado separadamente:
    cd casino/frontend && npm run dev
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.routes import create_app
from core.blockchain import Blockchain
from core.wallet import Wallet

def main():
    parser = argparse.ArgumentParser(description='Dev server')
    parser.add_argument('--port', type=int, default=5000, help='Porta (default: 5000)')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("SERVIDOR DE DESENVOLVIMENTO")
    print(f"{'='*60}\n")

    # Cria blockchain e wallet
    blockchain = Blockchain(difficulty=4)
    wallet = Wallet()
    miner_address = wallet.address

    # Cria o app Flask
    app = create_app(
        blockchain=blockchain,
        node_address=miner_address,
        port=args.port
    )

    # ─── Registra Blueprint do Cassino ──────────────────────
    print("[CASINO] Registrando blueprint do cassino...")
    try:
        from casino.backend.routes import create_casino_blueprint
        casino_bp = create_casino_blueprint(blockchain=blockchain)
        app.register_blueprint(casino_bp)
        print("   [OK] /api/casino/*")
    except Exception as e:
        print(f"   [WARN] {e}")

    # ─── Registra Blueprint de Producao ─────────────────────
    print("[PRODUCTION] Registrando blueprint de producao...")
    try:
        from casino.backend.infrastructure.routes import create_production_blueprint
        from casino.backend.infrastructure.deposit_manager_production import ProductionDepositManager
        prod_manager = ProductionDepositManager()
        prod_bp = create_production_blueprint(prod_manager)
        app.register_blueprint(prod_bp)
        app.prod_manager = prod_manager
        print("   [OK] /api/v2/casino/owner/*")
        print("   [OK] GET /api/v2/casino/owner/challenge")
        print("   [OK] GET /api/v2/casino/owner/profit (requer auth)")
        print("   [OK] POST /api/v2/casino/owner/withdraw-profit (requer auth)")
    except Exception as e:
        print(f"   [WARN] Erro ao registrar blueprint de producao: {e}")

    # ─── Lightning Network ──────────────────────────────────
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
        print("[LIGHTNING] /api/lightning/*")
    except Exception as e:
        print(f"   [WARN] Lightning: {e}")

    print(f"\n[START] Servidor rodando em http://localhost:{args.port}")
    print(f"\n[ENDPOINTS]")
    print(f"   GET  /chain                          - Blockchain completa")
    print(f"   POST /mine                           - Minerar bloco")
    print(f"   POST /transactions/new                - Nova transacao")
    print(f"   POST /wallet/new                      - Nova carteira")
    print(f"   GET  /balance/<address>               - Saldo")
    print(f"   GET  /api/casino/*                    - Cassino (jogos)")
    print(f"   GET  /api/v2/casino/owner/challenge   - Obter challenge")
    print(f"   GET  /api/v2/casino/owner/profit      - Ver lucro")
    print(f"   POST /api/v2/casino/owner/withdraw-profit - Sacar lucro")
    print(f"   GET  /api/lightning/*                 - Lightning Network")
    print(f"\n[TIP] Frontend: cd casino/frontend && npm run dev")

    # Error handler
    @app.errorhandler(500)
    def internal_error(error):
        import traceback
        traceback.print_exc()
        return {'error': 'Erro interno do servidor'}, 500

    try:
        app.run(host='0.0.0.0', port=args.port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\n[BYE] Encerrando...")
        blockchain.save_to_file('data/chain_backup.json')

if __name__ == '__main__':
    main()
