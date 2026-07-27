"""
Simulacao realista do Cascade Multi-Hop da Lightning Network.
Testa exatamente o mesmo fluxo que ocorreria via API Flask.
"""
import sys
import os

# Forca UTF-8 no Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

from lightning.lightning_network import LightningNetwork
from lightning.channel import ChannelState
from core.crypto_utils import CryptoUtils
import traceback

CHECK = "[OK]" if os.name != 'nt' else "[OK]"
FAIL = "[FAIL]" if os.name != 'nt' else "[FAIL]"

def simular_cascade_3_hops():
    print("=" * 70)
    print("SIMULACAO REALISTA: CASCADE 3 HOPS (Alice->Bob->Carol->Dave)")
    print("=" * 70)

    ln = LightningNetwork()
    alice = "alice_sim_" + CryptoUtils.generate_nonce()[:6]
    bob = "bob_sim_" + CryptoUtils.generate_nonce()[:6]
    carol = "carol_sim_" + CryptoUtils.generate_nonce()[:6]
    dave = "dave_sim_" + CryptoUtils.generate_nonce()[:6]

    print("\n[1] ABRINDO CANAIS:")
    ch_ab = ln.open_channel(alice, bob, 50.0, 50.0)
    print("    Alice(50) x Bob(50)")
    ch_bc = ln.open_channel(bob, carol, 30.0, 70.0)
    print("    Bob(30) x Carol(70)")
    ch_cd = ln.open_channel(carol, dave, 40.0, 60.0)
    print("    Carol(40) x Dave(60)")

    def get_all_balances():
        ab = ln.get_channel(ch_ab['channel_id'])
        bc = ln.get_channel(ch_bc['channel_id'])
        cd = ln.get_channel(ch_cd['channel_id'])
        return {
            'alice': ab['balance_a'] if ab else 0,
            'bob_ab': ab['balance_b'] if ab else 0,
            'bob_bc': bc['balance_a'] if bc else 0,
            'carol_bc': bc['balance_b'] if bc else 0,
            'carol_cd': cd['balance_a'] if cd else 0,
            'dave': cd['balance_b'] if cd else 0,
        }

    inicial = get_all_balances()
    print("\n[2] ESTADO INICIAL:")
    for k, v in inicial.items():
        print(f"    {k}: {v}")
    total_inicial = sum(inicial.values())
    print(f"    TOTAL: {total_inicial}")

    print("\n[3] ENVIANDO PAGAMENTO: Alice -> Dave (5 KUR)")
    try:
        resultado = ln.send_payment(alice, dave, 5.0)
        if resultado.get('success'):
            print(f"    SUCESSO! Hash: {resultado['payment_hash'][:16]}...")
            print(f"    Hops: {resultado['hops']}")
        else:
            print(f"    FALHA: {resultado.get('error', 'desconhecido')}")
            return False
    except Exception as e:
        print(f"    ERRO: {e}")
        traceback.print_exc()
        return False

    final = get_all_balances()
    print("\n[4] ESTADO FINAL:")
    alice_ok = abs(final['alice'] - 45.0) < 0.001
    bob_total = final['bob_ab'] + final['bob_bc']
    bob_ok = abs(bob_total - 80.0) < 0.001
    carol_total = final['carol_bc'] + final['carol_cd']
    carol_ok = abs(carol_total - 110.0) < 0.001
    dave_ok = abs(final['dave'] - 65.0) < 0.001
    total_final = sum(final.values())
    total_ok = abs(total_final - total_inicial) < 0.001

    print(f"    Alice: {final['alice']} {'OK' if alice_ok else 'FAIL'} (esperado 45.0)")
    print(f"    Bob:   {bob_total} {'OK' if bob_ok else 'FAIL'} (esperado 80.0)")
    print(f"    Carol: {carol_total} {'OK' if carol_ok else 'FAIL'} (esperado 110.0)")
    print(f"    Dave:  {final['dave']} {'OK' if dave_ok else 'FAIL'} (esperado 65.0)")
    print(f"    TOTAL: {total_final} {'OK' if total_ok else 'FAIL'} (deve ser igual ao inicial)")

    erros = []
    if not alice_ok: erros.append(f"Alice: {final['alice']} != 45.0")
    if not bob_ok: erros.append(f"Bob: {bob_total} != 80.0")
    if not carol_ok: erros.append(f"Carol: {carol_total} != 110.0")
    if not dave_ok: erros.append(f"Dave: {final['dave']} != 65.0")
    if not total_ok: erros.append(f"Total mudou: {total_final} != {total_inicial}")

    print()
    if erros:
        print("[ERRO] PROBLEMAS ENCONTRADOS:")
        for e in erros:
            print(f"    - {e}")
        return False
    else:
        print("[OK] TODAS AS VERIFICACOES PASSARAM! Cascade funcionando!")
        return True


def simular_cascade_2_hops():
    print("\n" + "=" * 70)
    print("SIMULACAO: CASCADE 2 HOPS (Alice->Bob->Carol)")
    print("=" * 70)

    ln = LightningNetwork()
    alice = "alice2_" + CryptoUtils.generate_nonce()[:6]
    bob = "bob2_" + CryptoUtils.generate_nonce()[:6]
    carol = "carol2_" + CryptoUtils.generate_nonce()[:6]

    print("\n[1] ABRINDO CANAIS:")
    ch_ab = ln.open_channel(alice, bob, 100.0, 50.0)
    print("    Alice(100) x Bob(50)")
    ch_bc = ln.open_channel(bob, carol, 30.0, 70.0)
    print("    Bob(30) x Carol(70)")

    print("\n[2] ENVIANDO PAGAMENTO: Alice -> Carol (8 KUR)")
    try:
        resultado = ln.send_payment(alice, carol, 8.0)
        if not resultado.get('success'):
            print(f"    FALHA: {resultado.get('error')}")
            return False
        print(f"    SUCESSO! Hops: {resultado['hops']}")
    except Exception as e:
        print(f"    ERRO: {e}")
        traceback.print_exc()
        return False

    ab = ln.get_channel(ch_ab['channel_id'])
    bc = ln.get_channel(ch_bc['channel_id'])

    alice_ok = abs(ab['balance_a'] - 92.0) < 0.001
    bob_total = ab['balance_b'] + bc['balance_a']
    bob_ok = abs(bob_total - 80.0) < 0.001
    carol_ok = abs(bc['balance_b'] - 78.0) < 0.001

    print("\n[3] VERIFICANDO:")
    print(f"    Alice: {ab['balance_a']} {'OK' if alice_ok else 'FAIL'} (esperado 92.0)")
    print(f"    Bob:   {bob_total} {'OK' if bob_ok else 'FAIL'} (esperado 80.0)")
    print(f"    Carol: {bc['balance_b']} {'OK' if carol_ok else 'FAIL'} (esperado 78.0)")

    erros = []
    if not alice_ok: erros.append(f"Alice: {ab['balance_a']} != 92.0")
    if not bob_ok: erros.append(f"Bob: {bob_total} != 80.0")
    if not carol_ok: erros.append(f"Carol: {bc['balance_b']} != 78.0")

    if erros:
        print(f"\n[ERRO] PROBLEMAS:")
        for e in erros:
            print(f"    - {e}")
        return False
    print(f"\n[OK] Cascade 2 hops OK!")
    return True


if __name__ == '__main__':
    # Forca UTF-8 no Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    
    ok_3 = simular_cascade_3_hops()
    ok_2 = simular_cascade_2_hops()
    print("\n" + "=" * 70)
    if ok_3 and ok_2:
        print("TODOS OS CASCADES FUNCIONANDO CORRETAMENTE!")
    else:
        print("ALGUM CASCADE FALHOU!")
    print("=" * 70)
    
    sys.exit(0 if (ok_3 and ok_2) else 1)
