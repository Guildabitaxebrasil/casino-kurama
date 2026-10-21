#!/usr/bin/env python3
"""
Ponto de entrada principal da Blockchain.

Modos de execução:
  1. Nó único (API REST):
     python run.py --port 5000

  2. Rede multi-nó (simulação):
     python run.py --network --nodes 3

  3. Modo interativo (console):
     python run.py --interactive

  4. Testes rápidos:
     python run.py --demo

Uso:
  python run.py [--port PORT] [--difficulty N] [--load]
                [--network] [--nodes N]
                [--interactive] [--demo]
"""
import sys
import os
import argparse
import time
import json
import subprocess
import uuid

# ─── Limpa cache bytecode FORÇADAMENTE ────────────────────────────
# No Windows, o comando rm -rf pode não funcionar no bash.
# Esta função garante que o cache seja limpo antes de qualquer import.
import glob
_script_dir = os.path.dirname(os.path.abspath(__file__))
for _pyc in glob.glob(os.path.join(_script_dir, '**', '__pycache__', '**', '*.pyc'), recursive=True):
    try:
        os.remove(_pyc)
    except OSError:
        pass
for _pyc in glob.glob(os.path.join(_script_dir, '**', '*.pyc'), recursive=True):
    try:
        os.remove(_pyc)
    except OSError:
        pass

# ─── Força UTF-8 no stdout/stderr (anti-UnicodeEncodeError no Windows) ─
# O terminal Windows usa cp1252 como padrão, que não suporta emojis.
# Esta configuração força UTF-8, prevenindo erros de codificação
# em prints com caracteres Unicode.
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    # Python < 3.7 não tem reconfigure
    pass

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.blockchain import Blockchain
from core.wallet import Wallet
from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from config import (
    DEFAULT_PORT, DEFAULT_DIFFICULTY, CHAIN_FILE,
    SSL_CERT_DIR, SSL_CERT_FILE, SSL_KEY_FILE, USE_HTTPS,
    NETWORK_SECRET, DATA_DIR, EVM_AUTO_MINE, EVM_CHAIN_ID
)

# ─── Auto-gera NETWORK_SECRET se vazio ─────────────────────────
# Garante que toda execução tenha um secret P2P único, mesmo que
# o usuário não tenha configurado um manualmente.
if not NETWORK_SECRET:
    import importlib
    import config as cfg
    cfg.NETWORK_SECRET = uuid.uuid4().hex
    NETWORK_SECRET = cfg.NETWORK_SECRET
    print(f"Secret P2P auto-gerado: {NETWORK_SECRET[:16]}...")


def ensure_certificates():
    """
    Gera certificados SSL auto-assinados se não existirem.

    Os certificados são gerados com OpenSSL e armazenados no
    diretório 'certs/'. São auto-assinados e válidos por 10 anos.
    Em produção, substitua por certificados de uma CA confiável.
    """
    os.makedirs(SSL_CERT_DIR, exist_ok=True)

    if not os.path.exists(SSL_CERT_FILE) or not os.path.exists(SSL_KEY_FILE):
        print("[SSL] Gerando certificados SSL auto-assinados...")
        try:
            # NOTA: No Windows/Git Bash, o subject deve usar
            # barras invertidas para separar os campos, senão
            # o OpenSSL interpreta as barras como caminhos.
            subprocess.run([
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                '-keyout', SSL_KEY_FILE,
                '-out', SSL_CERT_FILE,
                '-days', '3650', '-nodes',
                '-subj', '//CN=KuramaChain\\O=KuramaNetwork\\C=BR'
            ], check=True, capture_output=True, text=True)
            print(f"   [OK] Certificados salvos em {SSL_CERT_DIR}/")
            print(f"   [WARN] Auto-assinados — use CA confiavel em producao")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"   [ERR] Falha ao gerar certificados: {e}")
            print("   [WARN]  Continuando sem SSL (HTTP puro)")
            return False
    else:
        print(f"   [OK] Certificados SSL encontrados em {SSL_CERT_DIR}/")

    return True


def parse_args():
    """Analisa argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description='Blockchain com Proof of Work e API REST',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python run.py --port 5000 --difficulty 4
  python run.py --network --nodes 3
  python run.py --demo
  python run.py --interactive
        """
    )

    # Configuração do servidor
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'Porta do servidor (default: {DEFAULT_PORT})')
    parser.add_argument('--difficulty', type=int, default=DEFAULT_DIFFICULTY,
                        help=f'Dificuldade do PoW (default: {DEFAULT_DIFFICULTY})')
    parser.add_argument('--load', action='store_true',
                        help='Carregar blockchain salva')

    # Segurança
    parser.add_argument('--no-ssl', action='store_true',
                        help='Desabilitar HTTPS (usar HTTP puro)')

    # Modo multi-nó
    parser.add_argument('--network', action='store_true',
                        help='Iniciar rede multi-nó simulada')
    parser.add_argument('--nodes', type=int, default=3,
                        help='Número de nós na rede (default: 3)')

    # Modos especiais
    parser.add_argument('--interactive', action='store_true',
                        help='Modo interativo no console')
    parser.add_argument('--demo', action='store_true',
                        help='Executar demonstração automatizada')

    return parser.parse_args()


def run_single_node(args):
    """
    Executa um nó único da blockchain com API REST.

    Args:
        args: Argumentos da linha de comando
    """
    print(f"\n{'='*60}")
    print("BLOCKCHAIN NODE")
    print(f"{'='*60}\n")

    # Carrega ou cria blockchain
    if args.load and os.path.exists(CHAIN_FILE):
        print("[DIR] Carregando blockchain do arquivo...")
        blockchain = Blockchain.load_from_file(CHAIN_FILE)
        blockchain.difficulty = args.difficulty
    else:
        print("[NEW] Criando nova blockchain...")
        blockchain = Blockchain(difficulty=args.difficulty)

    # ─── Identidade do Nó (ECDSA Persistente) ───────────────────
    # Carrega identidade existente ou gera nova.
    # Persiste em DATA_DIR/node_identity.json entre restarts.
    from core.identity import get_or_create_identity
    identity_file = os.path.join(DATA_DIR, 'node_identity.json')
    node_identity = get_or_create_identity(identity_file)

    # Cria carteira do nó a partir da identidade persistente
    from core.wallet import Wallet
    wallet = Wallet(private_key_pem=node_identity.private_key_pem)
    miner_address = wallet.address

    print(f"\n[INFO] Informações do Nó:")
    print(f"   ID: {blockchain.node_id[:16]}...")
    print(f"   Blocos: {len(blockchain.chain)}")
    print(f"   Dificuldade: {blockchain.difficulty}")
    print(f"   Minerador: {miner_address[:20]}...")
    print(f"   Transações pendentes: {len(blockchain.pending_transactions)}")
    # ATENÇÃO: NÃO imprimimos a chave privada no console por segurança.
    # Em produção, a chave privada NUNCA deve ser exibida em logs.

    # Verifica integridade
    if len(blockchain.chain) > 1:
        print("[CHECK] Verificando integridade...")
        blockchain.is_chain_valid()

    # ─── HTTPS Setup ─────────────────────────────────────────────
    use_ssl = not args.no_ssl
    ssl_context = None
    protocol = 'http'

    if use_ssl:
        if ensure_certificates():
            ssl_context = (SSL_CERT_FILE, SSL_KEY_FILE)
            protocol = 'https'
        else:
            print("   [WARN]  Rodando sem SSL (use --no-ssl para suprimir)")
    else:
        print("   [WARN]  HTTPS desabilitado via --no-ssl")

    # Inicia servidor Flask
    from api.routes import create_app
    app = create_app(
        blockchain=blockchain,
        node_address=miner_address,
        port=args.port
    )

    # ─── Registra Blueprint da Lightning Network ────────────────
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
        # Armazena referência para acesso via current_app
        app.lightning_network = ln
        print("   [LIGHTNING] Blueprint da Lightning Network registrado em /api/lightning/*")
    except ImportError as e:
        print(f"   [WARN] Lightning Network nao disponivel: {e}")
    except Exception as e:
        print(f"   [WARN] Erro ao registrar Lightning Network: {e}")

    # ─── Registra EVM (Contratos Inteligentes / DeFi) ───────────
    try:
        from evm.engine import EVMEngine
        from evm.rpc import create_evm_blueprint
        evm_engine = EVMEngine(auto_mine=EVM_AUTO_MINE)
        app.register_blueprint(create_evm_blueprint(evm_engine))
        app.evm_engine = evm_engine
        # Integra com o PoW: cada bloco minerado sela um bloco EVM.
        blockchain.on('on_block_mined', evm_engine.on_pow_block)
        # Recredita na EVM os depósitos que já estão no ledger nativo
        # (o estado EVM é em memória e recomeça do gênesis).
        from evm.deposits import reconcile_native_deposits
        deposit_report = reconcile_native_deposits(blockchain, evm_engine)
        print(f"   [EVM] JSON-RPC eth_* registrado em /rpc "
              f"(chain_id={EVM_CHAIN_ID}, auto_mine={EVM_AUTO_MINE})")
        if deposit_report['credited'] or deposit_report['failed']:
            print(f"   [EVM] depósitos recreditados: {deposit_report['credited']} "
                  f"(falhas: {len(deposit_report['failed'])})")
    except ImportError as e:
        print(f"   [WARN] EVM nao disponivel: {e}")
    except Exception as e:
        print(f"   [WARN] Erro ao registrar EVM: {e}")

    print(f"\n[START] Servidor rodando em {protocol}://localhost:{args.port}")
    print(f"\n[ENDPOINT] Endpoints disponíveis:")
    print(f"   GET  /chain                - Blockchain completa")
    print(f"   POST /mine                 - Minerar bloco")
    print(f"   POST /transactions/new     - Nova transação")
    print(f"   POST /wallet/new           - Nova carteira")
    print(f"   GET  /balance/<address>    - Saldo")
    print(f"   POST /nodes/register       - Registrar nós vizinhos")
    print(f"   GET  /nodes/resolve        - Consenso")
    print(f"   GET  /validate             - Validar blockchain")
    print(f"   GET  /stats                - Estatísticas")
    print(f"   GET  /api/lightning/*     - Lightning Network (canais, pagamentos)")
    print(f"   POST /rpc                 - JSON-RPC EVM (eth_*, contratos Solidity)")
    if use_ssl:
        print(f"\n[TIP] Teste: curl -k https://localhost:{args.port}/chain\n")
    else:
        print(f"\n[TIP] Teste: curl http://localhost:{args.port}/chain\n")

    # ─── Error handler para capturar erros internos ────────────
    @app.errorhandler(500)
    def internal_error(error):
        import traceback
        traceback.print_exc()
        return {'error': 'Erro interno do servidor'}, 500

    try:
        app.run(host='0.0.0.0', port=args.port,
                ssl_context=ssl_context, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\n[SAVE] Salvando blockchain...")
        blockchain.save_to_file(CHAIN_FILE)
        print("[BYE] Encerrando...")


def run_network(args):
    """
    Executa uma rede multi-nó simulada.
    Cria, inicia e configura vários nós em threads separadas.

    Args:
        args: Argumentos da linha de comando
    """
    from node.node_manager import NodeManager

    use_ssl = not args.no_ssl
    if use_ssl:
        ensure_certificates()

    manager = NodeManager(base_port=args.port, use_ssl=use_ssl)
    manager.start_network(num_nodes=args.nodes)

    print(f"\n[STATS] Pressione Ctrl+C para parar todos os nós\n")

    try:
        # Mantém o programa rodando
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[STOP] Parando todos os nós...")
        for nid in list(manager.nodes.keys()):
            manager.stop_node(nid)
        print("[WORKER] Rede encerrada.")
        print("\n[STATS] Estatísticas finais:")
        stats = manager.get_network_stats()
        for nid, info in stats.items():
            print(f"   {nid}: {info['blocks']} blocos, "
                  f"saldo: {info['balance']:.2f}")


def run_interactive(args):
    """
    Modo interativo no console.
    Permite interagir com a blockchain via terminal.

    Args:
        args: Argumentos da linha de comando
    """
    blockchain = Blockchain(difficulty=args.difficulty)
    wallets = {}

    print(f"\n{'='*60}")
    print("[CHAIN] BLOCKCHAIN INTERATIVA")
    print(f"{'='*60}\n")

    commands = {
        '1': ('Nova carteira', None),
        '2': ('Listar carteiras', None),
        '3': ('Nova transação', None),
        '4': ('Minerar bloco', None),
        '5': ('Ver blockchain', None),
        '6': ('Ver saldo', None),
        '7': ('Validar blockchain', None),
        '8': ('Salvar blockchain', None),
        '9': ('Estatísticas', None),
        '0': ('Sair', None)
    }

    while True:
        print(f"\n{'>'*40}")
        print(f"[INFO] Blocos: {len(blockchain.chain)} | "
              f"Dificuldade: {blockchain.difficulty} | "
              f"Pendentes: {len(blockchain.pending_transactions)}")
        print(f"{'>'*40}")
        print("\nComandos:")
        for key, (cmd, _) in commands.items():
            print(f"   [{key}] {cmd}")

        choice = input("\n> Escolha: ").strip()

        if choice == '1':
            # Nova carteira
            wallet = Wallet()
            wallets[wallet.address[:12]] = wallet
            print(f"\n[OK] Carteira criada!")
            print(f"   Endereço: {wallet.address}")
            print(f"   Chave pública: {wallet.public_key_pem[:40]}...")

        elif choice == '2':
            # Listar carteiras
            if not wallets:
                print("\n[WARN]  Nenhuma carteira criada.")
            else:
                print(f"\n[INFO] Carteiras ({len(wallets)}):")
                for name, w in wallets.items():
                    balance = blockchain.get_balance(w.address)
                    print(f"   {name}: {w.address[:20]}... | "
                          f"Saldo: {balance:.2f}")

        elif choice == '3':
            # Nova transação
            if len(wallets) < 2:
                print("\n[WARN]  Crie pelo menos 2 carteiras primeiro.")
                continue

            print("\nCarteiras disponíveis:")
            names = list(wallets.keys())
            for i, name in enumerate(names):
                balance = blockchain.get_balance(wallets[name].address)
                print(f"   [{i}] {name} (saldo: {balance:.2f})")

            try:
                from_idx = int(input("\nCarteira de origem [índice]: "))
                to_idx = int(input("Carteira de destino [índice]: "))
                amount = float(input("Quantidade: "))

                sender = wallets[names[from_idx]]
                receiver = wallets[names[to_idx]].address

                tx = sender.create_transaction(receiver, amount)
                blockchain.pending_transactions.append(tx)

                print(f"\n[OK] Transação criada: {tx}")
            except (ValueError, IndexError) as e:
                print(f"\n[ERR] Erro: {e}")

        elif choice == '4':
            # Minerar bloco
            if not wallets:
                print("\n[WARN]  Crie uma carteira primeiro para receber a recompensa.")
                continue

            # Usa a primeira carteira como minerador
            miner = list(wallets.values())[0]
            block = blockchain.mine_block(miner.address)

            if block:
                balance = blockchain.get_balance(miner.address)
                print(f"\n[MONEY] Saldo do minerador: {balance:.2f}")

        elif choice == '5':
            # Ver blockchain
            print(f"\n[CHAIN] BLOCKCHAIN ({len(blockchain.chain)} blocos):\n")
            for block in blockchain.chain:
                ts = time.strftime('%Y-%m-%d %H:%M:%S',
                                   time.localtime(block.timestamp))
                print(f"╔══ Bloco #{block.index} {'═'*40}")
                print(f"║ Hash:     {block.hash}")
                print(f"║ Anterior: {block.previous_hash}")
                print(f"║ Timestamp: {ts}")
                print(f"║ Proof:    {block.proof}")
                print(f"║ Merkle:   {block.merkle_root[:40]}...")
                print(f"║ Transações: {len(block.transactions)}")
                for tx in block.transactions:
                    txd = tx.to_dict() if hasattr(tx, 'to_dict') else tx
                    print(f"║   ├ {txd.get('sender', '?')[:20]}... → "
                          f"{txd.get('receiver', '?')[:20]}... | "
                          f"{txd.get('amount', 0):.2f} coins")
                print(f"╚{'═'*60}\n")

        elif choice == '6':
            # Ver saldo
            if not wallets:
                print("\n[WARN]  Nenhuma carteira criada.")
                continue

            for name, w in wallets.items():
                balance = blockchain.get_balance(w.address)
                print(f"   {name}: {w.address[:20]}... → {balance:.2f} coins")

        elif choice == '7':
            # Validar blockchain
            print("\n[CHECK] Validando blockchain...")
            valid = blockchain.is_chain_valid()
            if valid:
                print("[OK] Blockchain válida e íntegra!")
            else:
                print("[ERR] Blockchain corrompida!")

        elif choice == '8':
            # Salvar blockchain
            blockchain.save_to_file(CHAIN_FILE)
            print(f"\n[SAVE] Blockchain salva em {CHAIN_FILE}")

        elif choice == '9':
            # Estatísticas
            print(f"\n[STATS] Estatísticas:")
            print(f"   Blocos: {len(blockchain.chain)}")
            print(f"   Dificuldade: {blockchain.difficulty}")
            print(f"   Recompensa: {blockchain.reward}")
            print(f"   Transações pendentes: {len(blockchain.pending_transactions)}")
            print(f"   ID do nó: {blockchain.node_id}")

            if wallets:
                total_balance = sum(
                    blockchain.get_balance(w.address)
                    for w in wallets.values()
                )
                print(f"   Carteiras: {len(wallets)}")
                print(f"   Saldo total: {total_balance:.2f} coins")

        elif choice == '0':
            print("\n[BYE] Encerrando...")
            save = input("Salvar blockchain? (s/N): ").strip().lower()
            if save == 's':
                blockchain.save_to_file(CHAIN_FILE)
            break

        else:
            print("\n[ERR] Comando inválido!")


def run_demo(args):
    """
    Executa uma demonstração completa e automatizada da blockchain.
    Mostra todos os conceitos em ação passo a passo.

    Args:
        args: Argumentos da linha de comando
    """
    print(f"\n{'='*60}")
    print("[CHAIN] DEMONSTRAÇÃO COMPLETA DA BLOCKCHAIN")
    print(f"{'='*60}\n")

    # ─── 1. CRIAÇÃO DA BLOCKCHAIN ────────────────────────────────
    print("[1] CRIANDO A BLOCKCHAIN")
    print("-" * 40)
    blockchain = Blockchain(difficulty=4)
    print(f"   [OK] Blockchain criada!")
    print(f"   [GENESIS] Bloco gênese: {blockchain.chain[0].hash[:32]}...")
    print(f"   [CHAIN] Total: {len(blockchain.chain)} bloco(s)")
    print()

    # ─── 2. CRIAÇÃO DE CARTEIRAS ─────────────────────────────────
    print("[2] CRIANDO CARTEIRAS")
    print("-" * 40)
    alice = Wallet()
    bob = Wallet()
    miner = Wallet()
    print(f"   [USER] Alice:   {alice.address[:20]}...")
    print(f"   [USER] Bob:     {bob.address[:20]}...")
    print(f"   [MINE]  Minerador: {miner.address[:20]}...")
    print()

    # ─── 3. MINERAÇÃO DO BLOCO #1 ────────────────────────────────
    print("[3] MINERANDO BLOCO #1 (recompensa inicial)")
    print("-" * 40)
    # A recompensa de mineração (coinbase) é adicionada automaticamente
    # pelo método mine_block(). A validação de bloco exige EXATAMENTE
    # uma coinbase por bloco (sender='0'), impedindo inflação.
    # Não adicione transações coinbase manualmente — isso é um ataque
    # de inflação detectado pela validação de segurança.
    blockchain.mine_block(miner.address)
    print()
    print("   [TIP] Dica: a coinbase é adicionada automaticamente pelo")
    print("   sistema de mineração. Transações sender='0' manuais são")
    print("   bloqueadas pela validação de segurança (anti-inflação).")
    print()

    # ─── 4. TRANSAÇÕES ───────────────────────────────────────────
    print("[4] CRIANDO TRANSAÇÕES")
    print("-" * 40)
    # Minerador envia 30 coins para Alice (ele recebeu a recompensa)
    # O minerador usa sua chave privada para assinar a transação
    tx_miner_alice = miner.create_transaction(alice.address, 30.0)
    blockchain.pending_transactions.append(tx_miner_alice)
    print(f"   [OK] Minerador → Alice: 30.0 coins")
    print(f"      ID: {tx_miner_alice.transaction_id[:20]}...")

    # Alice envia 15 coins para Bob (ela recebeu 30 do minerador)
    tx1 = alice.create_transaction(bob.address, 15.0)
    blockchain.pending_transactions.append(tx1)
    print(f"   [OK] Alice → Bob: 15.0 coins")
    print(f"      ID: {tx1.transaction_id[:20]}...")
    print(f"      Assinatura: {tx1.signature[:20] if tx1.signature else 'N/A'}...")

    # Alice envia 5 coins para o minerador
    tx2 = alice.create_transaction(miner.address, 5.0)
    blockchain.pending_transactions.append(tx2)
    print(f"   [OK] Alice → Minerador: 5.0 coins")
    print()

    # ─── 5. VALIDAÇÃO DE ASSINATURA ──────────────────────────────
    print("[5] VERIFICANDO ASSINATURAS DIGITAIS")
    print("-" * 40)
    print(f"   Tx1 válida: {tx1.is_valid()}")
    print(f"   Tx2 válida: {tx2.is_valid()}")

    # Tenta criar transação fraudulenta
    fake_tx = Transaction(
        sender=alice.public_key_pem,
        receiver=miner.address,
        amount=999999.0
    )
    print(f"   Tx falsa (sem assinatura) válida: {fake_tx.is_valid()}")
    print()

    # ─── 6. MINERAÇÃO DO BLOCO #2 ────────────────────────────────
    print("[6] MINERANDO BLOCO #2 (com transações)")
    print("-" * 40)
    blockchain.mine_block(miner.address)
    print()

    # ─── 7. CONSULTA DE SALDOS ────────────────────────────────────
    print("[7] CONSULTANDO SALDOS")
    print("-" * 40)
    for name, wallet in [('Alice', alice), ('Bob', bob), ('Minerador', miner)]:
        balance = blockchain.get_balance(wallet.address)
        print(f"   [WALLET] {name}: {balance:.2f} coins")
    # Verificação de consistência dos saldos
    alice_bal = blockchain.get_balance(alice.address)
    bob_bal = blockchain.get_balance(bob.address)
    miner_bal = blockchain.get_balance(miner.address)
    # Alice: 30 recebidos - 15 (Bob) - 5 (Minerador) = 10
    assert abs(alice_bal - 10.0) < 0.001, f"Alice balance mismatch: {alice_bal}"
    # Bob: 15 recebidos
    assert abs(bob_bal - 15.0) < 0.001, f"Bob balance mismatch: {bob_bal}"
    # Minerador: 50 (bloco 1) + 50 (bloco 2) + 5 (Alice) - 30 (enviado Alice) = 75
    assert abs(miner_bal - 75.0) < 0.001, f"Minerador balance mismatch: {miner_bal}"
    print(f"\n   [OK] Saldos verificados e consistentes!")
    print()

    # Salva saldos para o resumo final (antes da adulteração)
    _final_alice = alice_bal
    _final_bob = bob_bal
    _final_miner = miner_bal
    _final_total = alice_bal + bob_bal + miner_bal

    # ─── 8. VALIDAÇÃO DA CADEIA ──────────────────────────────────
    print("[8] VALIDANDO A BLOCKCHAIN")
    print("-" * 40)
    valid = blockchain.is_chain_valid()
    print(f"   {'[OK] VÁLIDA!' if valid else '[ERR] INVÁLIDA!'}")
    print()

    # ─── 9. TENTATIVA DE ADULTERAÇÃO ─────────────────────────────
    print("[9] SIMULANDO ADULTERAÇÃO DA CADEIA")
    print("-" * 40)
    # Altera uma transação no bloco 1
    old_hash = blockchain.chain[1].hash
    print(f"   Hash original do bloco #1: {old_hash[:32]}...")

    # Modifica a transação
    tx_alvo = blockchain.chain[1].transactions[0]
    tx_alvo.amount = 999999.0

    # Tenta recalcular (o hash muda completamente)
    new_hash = blockchain.chain[1].calculate_hash()
    print(f"   Hash após adulteração: {new_hash[:32]}...")
    print(f"   Hashes diferentes: {old_hash != new_hash}")

    valid_after = blockchain.is_chain_valid()
    print(f"   Blockchain válida após adulteração? {valid_after}")
    print()

    # ─── 10. ÁRVORE DE MERKLE ────────────────────────────────────
    print("[10]  DEMONSTRANDO ÁRVORE DE MERKLE")
    print("-" * 40)
    tx_list = [
        alice.create_transaction(bob.address, 5.0),
        alice.create_transaction(miner.address, 3.0),
        bob.create_transaction(alice.address, 2.0)
    ]
    merkle = CryptoUtils.merkle_root([tx.to_dict() for tx in tx_list])
    print(f"   Transações: {len(tx_list)}")
    print(f"   Raiz de Merkle: {merkle}")
    print()

    # ─── 11. TESTE DE PROOF OF WORK ──────────────────────────────
    print("[POW]  TESTE DE PROOF OF WORK")
    print("-" * 40)
    test_difficulty = 3
    print(f"   Dificuldade: {test_difficulty} zeros")

    proof = 0
    import time as time_module
    start = time_module.time()
    while True:
        test_hash = CryptoUtils.sha256(f"test{proof}")
        if CryptoUtils.is_hash_valid(test_hash, test_difficulty):
            elapsed = time_module.time() - start
            print(f"   Nonce encontrado: {proof}")
            print(f"   Hash: {test_hash}")
            print(f"   Tempo: {elapsed:.3f}s")
            break
        proof += 1
        if proof > 500000:
            print("   [WARN]  Limite excedido")
            break
    print()

    # ─── 12. RESUMO FINAL ────────────────────────────────────────
    print("=" * 60)
    print("[STATS] RESUMO DA BLOCKCHAIN")
    print("=" * 60)
    print(f"   Blocos minerados: {len(blockchain.chain)}")
    print(f"   Dificuldade atual: {blockchain.difficulty}")
    print(f"   Total de transações: {sum(len(b.transactions) for b in blockchain.chain)}")
    print(f"   Saldo Alice: {_final_alice:.2f}")
    print(f"   Saldo Bob:   {_final_bob:.2f}")
    print(f"   Saldo Miner: {_final_miner:.2f}")
    print(f"   Oferta total: {_final_total:.2f} coins "
          f"(recompensas mineradas: "
          f"{(len(blockchain.chain)-1) * blockchain.reward:.2f})")
    print("=" * 60)
    print("\n[OK] DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO!")
    print("=" * 60)


def main():
    """Função principal - analisa args e executa o modo apropriado."""
    args = parse_args()

    if args.demo:
        run_demo(args)
    elif args.interactive:
        run_interactive(args)
    elif args.network:
        run_network(args)
    else:
        run_single_node(args)


if __name__ == '__main__':
    main()
