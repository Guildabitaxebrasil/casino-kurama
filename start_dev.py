#!/usr/bin/env python3
"""
Script de inicializacao do servidor de desenvolvimento da blockchain.
Inicia o servidor Flask da blockchain KuramaChain.

Uso:
    python start_dev.py [--port PORT]

O servidor inicia em http://localhost:5000
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

    # ─── EVM (Contratos Inteligentes / DeFi) ────────────────
    try:
        from evm.engine import EVMEngine
        from evm.rpc import create_evm_blueprint
        from config import EVM_AUTO_MINE, EVM_CHAIN_ID
        evm_engine = EVMEngine(auto_mine=EVM_AUTO_MINE)
        app.register_blueprint(create_evm_blueprint(evm_engine))
        app.evm_engine = evm_engine
        blockchain.on('on_block_mined', evm_engine.on_pow_block)
        from evm.deposits import reconcile_native_deposits
        deposit_report = reconcile_native_deposits(blockchain, evm_engine)
        print(f"[EVM] /rpc (chain_id={EVM_CHAIN_ID}, auto_mine={EVM_AUTO_MINE})")
        if deposit_report['credited'] or deposit_report['failed']:
            print(f"[EVM] depósitos recreditados: {deposit_report['credited']} "
                  f"(falhas: {len(deposit_report['failed'])})")
    except Exception as e:
        print(f"   [WARN] EVM: {e}")

    print(f"\n[START] Servidor rodando em http://localhost:{args.port}")
    print(f"\n[ENDPOINTS]")
    print(f"   GET  /chain                          - Blockchain completa")
    print(f"   POST /mine                           - Minerar bloco")
    print(f"   POST /transactions/new                - Nova transacao")
    print(f"   POST /wallet/new                      - Nova carteira")
    print(f"   GET  /balance/<address>               - Saldo")
    print(f"   GET  /api/lightning/*                 - Lightning Network")
    print(f"   POST /rpc                             - JSON-RPC EVM (eth_*, DeFi)")

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
