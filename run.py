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

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.blockchain import Blockchain
from core.wallet import Wallet
from core.crypto_utils import CryptoUtils
from core.transaction import Transaction
from config import DEFAULT_PORT, DEFAULT_DIFFICULTY, CHAIN_FILE


def parse_args():
    """Analisa argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description='💎 Blockchain com Proof of Work e API REST',
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
    print("💎 BLOCKCHAIN NODE")
    print(f"{'='*60}\n")

    # Carrega ou cria blockchain
    if args.load and os.path.exists(CHAIN_FILE):
        print("📂 Carregando blockchain do arquivo...")
        blockchain = Blockchain.load_from_file(CHAIN_FILE)
        blockchain.difficulty = args.difficulty
    else:
        print("🆕 Criando nova blockchain...")
        blockchain = Blockchain(difficulty=args.difficulty)

    # Cria carteira do nó
    wallet = Wallet()
    miner_address = wallet.address

    print(f"\n📋 Informações do Nó:")
    print(f"   ID: {blockchain.node_id[:16]}...")
    print(f"   Blocos: {len(blockchain.chain)}")
    print(f"   Dificuldade: {blockchain.difficulty}")
    print(f"   Minerador: {miner_address[:20]}...")
    print(f"   Transações pendentes: {len(blockchain.pending_transactions)}")
    print(f"\n🔑 Chave privada do minerador (guarde!):")
    print(f"   {wallet.private_key_pem[:50]}...\n")

    # Verifica integridade
    if len(blockchain.chain) > 1:
        print("🔍 Verificando integridade...")
        blockchain.is_chain_valid()

    # Inicia servidor Flask
    from api.routes import create_app
    app = create_app(
        blockchain=blockchain,
        node_address=miner_address,
        port=args.port
    )

    print(f"\n🚀 Servidor rodando em http://localhost:{args.port}")
    print(f"\n📌 Endpoints disponíveis:")
    print(f"   GET  /chain              - Blockchain completa")
    print(f"   GET  /mine               - Minerar bloco")
    print(f"   POST /transactions/new   - Nova transação")
    print(f"   GET  /wallet/new         - Nova carteira")
    print(f"   GET  /balance/<address>  - Saldo")
    print(f"   POST /nodes/register     - Registrar nós vizinhos")
    print(f"   GET  /nodes/resolve      - Consenso")
    print(f"   GET  /validate           - Validar blockchain")
    print(f"   GET  /stats              - Estatísticas")
    print(f"\n💡 Teste: curl http://localhost:{args.port}/chain\n")

    try:
        app.run(host='0.0.0.0', port=args.port, debug=False)
    except KeyboardInterrupt:
        print("\n\n💾 Salvando blockchain...")
        blockchain.save_to_file(CHAIN_FILE)
        print("👋 Encerrando...")


def run_network(args):
    """
    Executa uma rede multi-nó simulada.
    Cria, inicia e configura vários nós em threads separadas.

    Args:
        args: Argumentos da linha de comando
    """
    from node.node_manager import NodeManager

    manager = NodeManager(base_port=args.port)
    manager.start_network(num_nodes=args.nodes)

    print(f"\n📊 Pressione Ctrl+C para parar todos os nós\n")

    try:
        # Mantém o programa rodando
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Parando todos os nós...")
        for nid in list(manager.nodes.keys()):
            manager.stop_node(nid)
        print("👷 Rede encerrada.")
        print("\n📊 Estatísticas finais:")
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
    print("💎 BLOCKCHAIN INTERATIVA")
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
        print(f"📋 Blocos: {len(blockchain.chain)} | "
              f"Dificuldade: {blockchain.difficulty} | "
              f"Pendentes: {len(blockchain.pending_transactions)}")
        print(f"{'>'*40}")
        print("\nComandos:")
        for key, (cmd, _) in commands.items():
            print(f"   [{key}] {cmd}")

        choice = input("\n👉 Escolha: ").strip()

        if choice == '1':
            # Nova carteira
            wallet = Wallet()
            wallets[wallet.address[:12]] = wallet
            print(f"\n✅ Carteira criada!")
            print(f"   Endereço: {wallet.address}")
            print(f"   Chave pública: {wallet.public_key_pem[:40]}...")

        elif choice == '2':
            # Listar carteiras
            if not wallets:
                print("\n⚠️  Nenhuma carteira criada.")
            else:
                print(f"\n📋 Carteiras ({len(wallets)}):")
                for name, w in wallets.items():
                    balance = blockchain.get_balance(w.address)
                    print(f"   {name}: {w.address[:20]}... | "
                          f"Saldo: {balance:.2f}")

        elif choice == '3':
            # Nova transação
            if len(wallets) < 2:
                print("\n⚠️  Crie pelo menos 2 carteiras primeiro.")
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

                print(f"\n✅ Transação criada: {tx}")
            except (ValueError, IndexError) as e:
                print(f"\n❌ Erro: {e}")

        elif choice == '4':
            # Minerar bloco
            if not wallets:
                print("\n⚠️  Crie uma carteira primeiro para receber a recompensa.")
                continue

            # Usa a primeira carteira como minerador
            miner = list(wallets.values())[0]
            block = blockchain.mine_block(miner.address)

            if block:
                balance = blockchain.get_balance(miner.address)
                print(f"\n💰 Saldo do minerador: {balance:.2f}")

        elif choice == '5':
            # Ver blockchain
            print(f"\n📜 BLOCKCHAIN ({len(blockchain.chain)} blocos):\n")
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
                print("\n⚠️  Nenhuma carteira criada.")
                continue

            for name, w in wallets.items():
                balance = blockchain.get_balance(w.address)
                print(f"   {name}: {w.address[:20]}... → {balance:.2f} coins")

        elif choice == '7':
            # Validar blockchain
            print("\n🔍 Validando blockchain...")
            valid = blockchain.is_chain_valid()
            if valid:
                print("✅ Blockchain válida e íntegra!")
            else:
                print("❌ Blockchain corrompida!")

        elif choice == '8':
            # Salvar blockchain
            blockchain.save_to_file(CHAIN_FILE)
            print(f"\n💾 Blockchain salva em {CHAIN_FILE}")

        elif choice == '9':
            # Estatísticas
            print(f"\n📊 Estatísticas:")
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
            print("\n👋 Encerrando...")
            save = input("Salvar blockchain? (s/N): ").strip().lower()
            if save == 's':
                blockchain.save_to_file(CHAIN_FILE)
            break

        else:
            print("\n❌ Comando inválido!")


def run_demo(args):
    """
    Executa uma demonstração completa e automatizada da blockchain.
    Mostra todos os conceitos em ação passo a passo.

    Args:
        args: Argumentos da linha de comando
    """
    print(f"\n{'='*60}")
    print("💎 DEMONSTRAÇÃO COMPLETA DA BLOCKCHAIN")
    print(f"{'='*60}\n")

    # ─── 1. CRIAÇÃO DA BLOCKCHAIN ────────────────────────────────
    print("1️⃣  CRIANDO A BLOCKCHAIN")
    print("-" * 40)
    blockchain = Blockchain(difficulty=4)
    print(f"   ✅ Blockchain criada!")
    print(f"   📦 Bloco gênese: {blockchain.chain[0].hash[:32]}...")
    print(f"   🔗 Total: {len(blockchain.chain)} bloco(s)")
    print()

    # ─── 2. CRIAÇÃO DE CARTEIRAS ─────────────────────────────────
    print("2️⃣  CRIANDO CARTEIRAS")
    print("-" * 40)
    alice = Wallet()
    bob = Wallet()
    miner = Wallet()
    print(f"   👤 Alice:   {alice.address[:20]}...")
    print(f"   👤 Bob:     {bob.address[:20]}...")
    print(f"   ⛏️  Minerador: {miner.address[:20]}...")
    print()

    # ─── 3. MINERAÇÃO DO BLOCO #1 ────────────────────────────────
    print("3️⃣  MINERANDO BLOCO #1 (recompensa inicial)")
    print("-" * 40)
    # Adiciona uma transação de coinbase manualmente
    blockchain.pending_transactions.append(
        Transaction(sender='0', receiver=alice.address, amount=100.0)
    )
    blockchain.mine_block(miner.address)
    print()

    # ─── 4. TRANSAÇÕES ───────────────────────────────────────────
    print("4️⃣  CRIANDO TRANSAÇÕES")
    print("-" * 40)
    # Alice envia 30 coins para Bob
    tx1 = alice.create_transaction(bob.address, 30.0)
    blockchain.pending_transactions.append(tx1)
    print(f"   ✅ Alice → Bob: 30.0 coins")
    print(f"      ID: {tx1.transaction_id[:20]}...")
    print(f"      Assinatura: {tx1.signature[:20] if tx1.signature else 'N/A'}...")

    # Alice envia 20 coins para o minerador
    tx2 = alice.create_transaction(miner.address, 20.0)
    blockchain.pending_transactions.append(tx2)
    print(f"   ✅ Alice → Minerador: 20.0 coins")
    print()

    # ─── 5. VALIDAÇÃO DE ASSINATURA ──────────────────────────────
    print("5️⃣  VERIFICANDO ASSINATURAS DIGITAIS")
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
    print("6️⃣  MINERANDO BLOCO #2 (com transações)")
    print("-" * 40)
    blockchain.mine_block(miner.address)
    print()

    # ─── 7. CONSULTA DE SALDOS ────────────────────────────────────
    print("7️⃣  CONSULTANDO SALDOS")
    print("-" * 40)
    for name, wallet in [('Alice', alice), ('Bob', bob), ('Minerador', miner)]:
        balance = blockchain.get_balance(wallet.address)
        print(f"   👛 {name}: {balance:.2f} coins")
    print()

    # ─── 8. VALIDAÇÃO DA CADEIA ──────────────────────────────────
    print("8️⃣  VALIDANDO A BLOCKCHAIN")
    print("-" * 40)
    valid = blockchain.is_chain_valid()
    print(f"   {'✅ VÁLIDA!' if valid else '❌ INVÁLIDA!'}")
    print()

    # ─── 9. TENTATIVA DE ADULTERAÇÃO ─────────────────────────────
    print("9️⃣  SIMULANDO ADULTERAÇÃO DA CADEIA")
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
    print("🔟  DEMONSTRANDO ÁRVORE DE MERKLE")
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
    print("🏁  TESTE DE PROOF OF WORK")
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
            print("   ⚠️  Limite excedido")
            break
    print()

    # ─── 12. RESUMO FINAL ────────────────────────────────────────
    print("=" * 60)
    print("📊 RESUMO DA BLOCKCHAIN")
    print("=" * 60)
    print(f"   Blocos minerados: {len(blockchain.chain)}")
    print(f"   Dificuldade atual: {blockchain.difficulty}")
    print(f"   Total de transações: {sum(len(b.transactions) for b in blockchain.chain)}")
    print(f"   Saldo Alice: {blockchain.get_balance(alice.address):.2f}")
    print(f"   Saldo Bob:   {blockchain.get_balance(bob.address):.2f}")
    print(f"   Saldo Miner: {blockchain.get_balance(miner.address):.2f}")
    print(f"   Recompensa total minerada: "
          f"{len(blockchain.chain) * blockchain.reward:.2f}")
    print("=" * 60)
    print("\n✅ DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO!")
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
