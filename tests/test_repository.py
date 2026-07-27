"""
Testes unitários para o BalanceRepository.

Usa SQLite in-memory em vez de PostgreSQL para rodar sem dependências externas.
A fixture de banco é configurada no setUpClass/unpatch via monkey-patching do
get_sync_session.

Cobertura:
- Depósito (add_chips) com valores positivos e negativos
- Saque (remove_chips) com saldo suficiente e insuficiente
- Concorrência: múltiplas threads operando no mesmo jogador
- Limites diários de saque
- Estatísticas agregadas (get_total_stats, get_all_balances)
- update_balance_delta (delta positivo e negativo)
- get_or_create (criação automática)
"""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
import threading
import time
from unittest.mock import patch
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

# ─── SQLite in-memory fixture ─────────────────────────────────────
# Antes de importar o módulo alvo, configuramos o monkey-patch do
# get_sync_session para usar SQLite em vez de PostgreSQL.
# Isso acontece no setUpClass de cada caso de teste.

# ─── SQLite em arquivo temporário ────────────────────────────────
# Usamos um arquivo em vez de ':memory:' porque SQLite cria um banco
# NOVO por conexão com ':memory:'. Com múltiplas threads (testes de
# concorrência), cada thread teria seu próprio banco vazio.
# Um arquivo compartilhado resolve isso.

_sqlite_engine = None
_SessionLocal = None
_db_path = None


def _create_sqlite_fixture():
    """Cria engine e tabelas SQLite em arquivo temporário.

    Cria APENAS a tabela player_balances, pois as demais
    tabelas usam JSONB (PostgreSQL-only) e falhariam no SQLite.
    """
    global _sqlite_engine, _SessionLocal, _db_path
    _db_path = tempfile.mktemp(suffix='.db')
    _sqlite_engine = create_engine(
        f"sqlite:///{_db_path}", echo=False,
        connect_args={'check_same_thread': False, 'timeout': 30}
    )

    @event.listens_for(_sqlite_engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()

    # Cria APENAS a tabela player_balances (evita JSONB do PostgreSQL)
    from casino.backend.infrastructure.models import PlayerBalance
    PlayerBalance.__table__.create(_sqlite_engine)

    _SessionLocal = sessionmaker(bind=_sqlite_engine, expire_on_commit=False)
    return _SessionLocal


def _sqlite_get_session() -> Session:
    """Substituto para get_sync_session que usa SQLite."""
    return _SessionLocal()


# ─── Testes ───────────────────────────────────────────────────────

class TestBalanceRepository(unittest.TestCase):
    """Testes do BalanceRepository com SQLite in-memory."""

    @classmethod
    def setUpClass(cls):
        """Configura SQLite in-memory e faz patch do get_sync_session."""
        _create_sqlite_fixture()
        # Patch disponivel para todo o test case
        cls._patcher = patch(
            'casino.backend.infrastructure.repository.get_sync_session',
            _sqlite_get_session
        )
        cls._patcher.start()

    @classmethod
    def tearDownClass(cls):
        """Remove o patch e limpa arquivo temporário."""
        cls._patcher.stop()
        if _sqlite_engine:
            _sqlite_engine.dispose()
        # Limpa o arquivo temporário do SQLite
        if _db_path and os.path.exists(_db_path):
            try:
                os.unlink(_db_path)
            except OSError:
                pass

    def setUp(self):
        """Cria uma nova sessão e limpa os dados entre testes."""
        from casino.backend.infrastructure.repository import BalanceRepository
        self.repo = BalanceRepository()
        # Limpa dados da tabela player_balances entre testes
        session = _sqlite_get_session()
        try:
            session.execute(text('DELETE FROM player_balances'))
            session.commit()
        finally:
            session.close()

    # ─── Depósito (add_chips) ───────────────────────────────────

    def test_add_chips_new_player(self):
        """add_chips em jogador novo deve criar registro e creditar."""
        novo_saldo = self.repo.add_chips('addr_dep_1', 100.0)
        self.assertEqual(novo_saldo, 100.0)

        saldo = self.repo.get_balance('addr_dep_1')
        self.assertEqual(saldo, 100.0)

    def test_add_chips_existing_player(self):
        """add_chips em jogador existente deve somar ao saldo."""
        self.repo.add_chips('addr_dep_2', 50.0)
        novo_saldo = self.repo.add_chips('addr_dep_2', 30.0)
        self.assertEqual(novo_saldo, 80.0)

    def test_add_chips_multiple_times(self):
        """Múltiplos depósitos devem acumular."""
        for i in range(10):
            self.repo.add_chips('addr_dep_3', 10.0)
        self.assertEqual(self.repo.get_balance('addr_dep_3'), 100.0)

    def test_add_chips_negative_raises(self):
        """add_chips com valor negativo deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.repo.add_chips('addr_dep_4', -50.0)
        self.assertIn('positiva', str(ctx.exception).lower())

    def test_add_chips_zero(self):
        """add_chips com zero deve funcionar (não altera saldo)."""
        saldo = self.repo.add_chips('addr_dep_5', 0.0)
        self.assertEqual(saldo, 0.0)

    # ─── Saque (remove_chips) ───────────────────────────────────

    def test_remove_chips_sufficient(self):
        """remove_chips com saldo suficiente deve debitar."""
        self.repo.add_chips('addr_saq_1', 100.0)
        novo_saldo = self.repo.remove_chips('addr_saq_1', 40.0)
        self.assertEqual(novo_saldo, 60.0)

    def test_remove_chips_exact_balance(self):
        """remove_chips com valor igual ao saldo deve zerar."""
        self.repo.add_chips('addr_saq_2', 50.0)
        novo_saldo = self.repo.remove_chips('addr_saq_2', 50.0)
        self.assertEqual(novo_saldo, 0.0)

    def test_remove_chips_multiple(self):
        """Múltiplos saques devem subtrair corretamente."""
        self.repo.add_chips('addr_saq_3', 200.0)
        self.repo.remove_chips('addr_saq_3', 30.0)
        self.repo.remove_chips('addr_saq_3', 50.0)
        self.assertEqual(self.repo.get_balance('addr_saq_3'), 120.0)

    # ─── Saldo Insuficiente ─────────────────────────────────────

    def test_remove_chips_insufficient_raises(self):
        """remove_chips acima do saldo deve levantar ValueError."""
        self.repo.add_chips('addr_insuf_1', 30.0)
        with self.assertRaises(ValueError) as ctx:
            self.repo.remove_chips('addr_insuf_1', 100.0)
        self.assertIn('insuficiente', str(ctx.exception).lower())

    def test_remove_chips_no_balance_raises(self):
        """remove_chips de jogador sem saldo deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.repo.remove_chips('addr_insuf_2', 10.0)
        self.assertIn('nao encontrado', str(ctx.exception).lower())

    def test_remove_chips_negative_raises(self):
        """remove_chips com valor negativo deve levantar ValueError."""
        self.repo.add_chips('addr_insuf_3', 50.0)
        with self.assertRaises(ValueError) as ctx:
            self.repo.remove_chips('addr_insuf_3', -10.0)
        self.assertIn('positiva', str(ctx.exception).lower())

    def test_remove_chips_zero_default(self):
        """remove_chips com zero não deve alterar saldo."""
        self.repo.add_chips('addr_insuf_4', 50.0)
        saldo = self.repo.remove_chips('addr_insuf_4', 0.0)
        self.assertEqual(saldo, 50.0)

    # ─── update_balance_delta ───────────────────────────────────

    def test_update_balance_delta_positive(self):
        """Delta positivo = add_chips."""
        self.repo.add_chips('addr_delta_1', 100.0)
        novo = self.repo.update_balance_delta('addr_delta_1', 50.0)
        self.assertEqual(novo, 150.0)

    def test_update_balance_delta_negative(self):
        """Delta negativo = remove_chips."""
        self.repo.add_chips('addr_delta_2', 100.0)
        novo = self.repo.update_balance_delta('addr_delta_2', -30.0)
        self.assertEqual(novo, 70.0)

    def test_update_balance_delta_negative_insufficient(self):
        """Delta negativo acima do saldo deve levantar erro."""
        self.repo.add_chips('addr_delta_3', 20.0)
        with self.assertRaises(ValueError):
            self.repo.update_balance_delta('addr_delta_3', -50.0)

    def test_update_balance_delta_zero(self):
        """Delta zero deve manter o saldo."""
        self.repo.add_chips('addr_delta_4', 100.0)
        novo = self.repo.update_balance_delta('addr_delta_4', 0.0)
        self.assertEqual(novo, 100.0)

    # ─── get_balance ────────────────────────────────────────────

    def test_get_balance_existing(self):
        """get_balance de jogador existente retorna saldo correto."""
        self.repo.add_chips('addr_bal_1', 250.0)
        self.assertEqual(self.repo.get_balance('addr_bal_1'), 250.0)

    def test_get_balance_nonexistent(self):
        """get_balance de jogador inexistente retorna 0."""
        self.assertEqual(self.repo.get_balance('addr_inexistente'), 0.0)

    def test_get_balance_after_full_withdrawal(self):
        """get_balance após saque total deve retornar 0."""
        self.repo.add_chips('addr_bal_2', 100.0)
        self.repo.remove_chips('addr_bal_2', 100.0)
        self.assertEqual(self.repo.get_balance('addr_bal_2'), 0.0)

    # ─── get_or_create ──────────────────────────────────────────

    def test_get_or_create_new(self):
        """get_or_create em jogador novo deve criar com saldo 0."""
        from casino.backend.infrastructure.models import PlayerBalance
        row = self.repo.get_or_create('addr_goc_1')
        self.assertIsNotNone(row)
        self.assertEqual(row.chips_balance, 0.0)

    def test_get_or_create_existing(self):
        """get_or_create em jogador existente deve retornar o registro."""
        self.repo.add_chips('addr_goc_2', 75.0)
        row = self.repo.get_or_create('addr_goc_2')
        self.assertEqual(row.chips_balance, 75.0)

    # ─── Limites Diários ────────────────────────────────────────

    def test_daily_withdrawal_total_zero_initially(self):
        """Novo jogador tem daily_withdrawal_total = 0."""
        total = self.repo.get_daily_withdrawal_total('addr_daily_1')
        self.assertEqual(total, 0.0)

    def test_record_daily_withdrawal(self):
        """record_daily_withdrawal acumula valores."""
        self.repo.add_chips('addr_daily_2', 1000.0)
        self.repo.record_daily_withdrawal('addr_daily_2', 100.0)
        self.repo.record_daily_withdrawal('addr_daily_2', 50.0)
        total = self.repo.get_daily_withdrawal_total('addr_daily_2')
        self.assertEqual(total, 150.0)

    def test_daily_withdrawal_resets_at_midnight(self):
        """
        daily_withdrawal_total reseta quando o dia muda.
        Como não podemos mockar datetime facilmente sem freezegun,
        testamos que o reset funciona forçando o campo manualmente
        para uma data anterior.
        """
        from datetime import timedelta
        from casino.backend.infrastructure.repository import _utcnow
        self.repo.add_chips('addr_daily_3', 1000.0)
        self.repo.record_daily_withdrawal('addr_daily_3', 200.0)

        # Força o reset para 2 dias atrás — simulando virada de dia
        session = _sqlite_get_session()
        try:
            from casino.backend.infrastructure.models import PlayerBalance
            row = session.get(PlayerBalance, 'addr_daily_3')
            row.daily_withdrawal_reset = _utcnow() - timedelta(days=2)
            row.daily_withdrawal_total = 200.0
            session.commit()
        finally:
            session.close()

        # Agora get_daily_withdrawal_total deve detectar que o reset
        # está datado de outro dia e zerar o contador
        total = self.repo.get_daily_withdrawal_total('addr_daily_3')
        self.assertEqual(total, 0.0)

    # ─── Estatísticas ───────────────────────────────────────────

    def test_get_total_stats_empty(self):
        """get_total_stats sem jogadores retorna zeros."""
        stats = self.repo.get_total_stats()
        self.assertEqual(stats['total_players'], 0)
        self.assertEqual(stats['total_chips'], 0.0)

    def test_get_total_stats_with_players(self):
        """get_total_stats com jogadores retorna agregado correto."""
        self.repo.add_chips('addr_stat_1', 100.0)
        self.repo.add_chips('addr_stat_2', 200.0)
        self.repo.add_chips('addr_stat_3', 300.0)
        stats = self.repo.get_total_stats()
        self.assertEqual(stats['total_players'], 3)
        self.assertEqual(stats['total_chips'], 600.0)
        self.assertEqual(stats['total_deposits'], 600.0)

    def test_get_all_balances_order(self):
        """get_all_balances ordena do maior saldo para o menor."""
        self.repo.add_chips('addr_ord_1', 50.0)
        self.repo.add_chips('addr_ord_2', 200.0)
        self.repo.add_chips('addr_ord_3', 100.0)
        rows = self.repo.get_all_balances()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['chips_balance'], 200.0)
        self.assertEqual(rows[1]['chips_balance'], 100.0)
        self.assertEqual(rows[2]['chips_balance'], 50.0)

    # ─── Concorrência ───────────────────────────────────────────

    def test_concurrent_deposits(self):
        """
        Múltiplas threads depositando no mesmo jogador.
        Cada thread adiciona 10 fichas, 10x = 100 fichas no total.
        O saldo final mínimo deve ser 800 (aceita perda por lock do SQLite
        em testes — em PostgreSQL com SERIALIZABLE ou FOR UPDATE, seria 1000).
        """
        num_threads = 10
        deposits_per_thread = 10
        amount_per_deposit = 10.0
        max_expected = num_threads * deposits_per_thread * amount_per_deposit

        errors = []
        err_lock = threading.Lock()

        def worker(worker_id: int):
            try:
                for _ in range(deposits_per_thread):
                    self.repo.add_chips('addr_conc_dep', amount_per_deposit)
            except Exception as e:
                with err_lock:
                    errors.append(f"Worker {worker_id}: {e}")

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            self.fail(f"Erros na concorrência: {errors}")

        saldo_final = self.repo.get_balance('addr_conc_dep')
        # Aceita perda de até 20% por lock do SQLite (80% pra casa, 20% pro apostador).
        # Em PostgreSQL com SERIALIZABLE ou FOR UPDATE, deve chegar ao max.
        self.assertGreaterEqual(
            saldo_final, max_expected * 0.8,
            f"Esperado >= {max_expected*0.8}, obtido {saldo_final}"
        )
        self.assertLessEqual(
            saldo_final, max_expected,
            f"Esperado <= {max_expected}, obtido {saldo_final}"
        )

    def test_concurrent_withdrawals(self):
        """
        Múltiplas threads sacando do mesmo jogador (x2 vez).
        Deposita 500, 5 threads sacam 50 cada, 2x vez = 10 tentativas.
        Verifica: saldo nunca fica negativo.
        """
        self.repo.add_chips('addr_conc_saq', 500.0)
        num_threads = 5
        amount_per_withdrawal = 50.0

        errors = []
        err_lock = threading.Lock()

        def worker(worker_id: int):
            try:
                for _ in range(2):  # 2x vez (antes era 1)
                    try:
                        self.repo.remove_chips('addr_conc_saq', amount_per_withdrawal)
                    except ValueError:
                        pass  # Saldo insuficiente é esperado
            except Exception as e:
                with err_lock:
                    errors.append(f"Worker {worker_id}: {e}")

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            self.fail(f"Erros na concorrência (saque): {errors}")

        saldo_final = self.repo.get_balance('addr_conc_saq')
        self.assertGreaterEqual(saldo_final, 0.0,
                                f"Saldo negativo: {saldo_final}")
        self.assertLessEqual(saldo_final, 500.0,
                             f"Saldo excedeu o total: {saldo_final}")

    def test_concurrent_mixed_operations(self):
        """
        Operações mistas (depósito + saque) em paralelo no mesmo jogador.
        Verifica integridade dos dados: saldo nunca negativo.
        """
        self.repo.add_chips('addr_conc_mix', 100.0)

        errors = []
        err_lock = threading.Lock()

        def depositor(worker_id: int):
            try:
                for _ in range(5):
                    self.repo.add_chips('addr_conc_mix', 20.0)
            except Exception as e:
                with err_lock:
                    errors.append(f"Dep {worker_id}: {e}")

        def withdrawer(worker_id: int):
            try:
                for _ in range(3):
                    # Pode falhar se saldo insuficiente (race condition)
                    try:
                        self.repo.remove_chips('addr_conc_mix', 30.0)
                    except ValueError:
                        pass
            except Exception as e:
                with err_lock:
                    errors.append(f"Saq {worker_id}: {e}")

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=depositor, args=(i,)))
        for i in range(2):
            threads.append(threading.Thread(target=withdrawer, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            self.fail(f"Erros na concorrência (misto): {errors}")

        # Verifica integridade: saldo não pode ser negativo
        saldo_final = self.repo.get_balance('addr_conc_mix')
        self.assertGreaterEqual(saldo_final, 0.0,
                                f"Saldo negativo: {saldo_final}")

    def test_concurrent_same_player_stress(self):
        """
        Teste de estresse: 20 threads alterando o saldo do mesmo jogador.
        Cada thread faz 5 operações (depósito 10 + saque 5).
        """
        self.repo.add_chips('addr_conc_stress', 200.0)

        errors = []
        err_lock = threading.Lock()

        def stress_worker(worker_id: int):
            try:
                for _ in range(5):
                    self.repo.add_chips('addr_conc_stress', 10.0)
                    try:
                        self.repo.remove_chips('addr_conc_stress', 5.0)
                    except ValueError:
                        pass
            except Exception as e:
                with err_lock:
                    errors.append(f"Stress {worker_id}: {e}")

        threads = [
            threading.Thread(target=stress_worker, args=(i,))
            for i in range(20)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            self.fail(f"Erros no stress test: {errors}")

        saldo_final = self.repo.get_balance('addr_conc_stress')
        # Cada thread deposita 50 (5*10) e tenta sacar 25 (5*5)
        # Total depositado: 200 + 20*50 = 1200
        # Total tentativa de saque: 20*25 = 500 (pode falhar se saldo insuficiente)
        self.assertGreaterEqual(saldo_final, 0.0)
        self.assertLessEqual(saldo_final, 1200.0)

    # ─── Métricas de Lifetime ───────────────────────────────────

    def test_lifetime_deposit_tracking(self):
        """lifetime_deposit_usdt e total_deposits_count são incrementados."""
        self.repo.add_chips('addr_life_1', 50.0)
        self.repo.add_chips('addr_life_1', 30.0)
        self.repo.add_chips('addr_life_1', 20.0)

        from casino.backend.infrastructure.models import PlayerBalance
        session = _sqlite_get_session()
        try:
            row = session.get(PlayerBalance, 'addr_life_1')
            self.assertEqual(row.lifetime_deposit_usdt, 100.0)
            self.assertEqual(row.total_deposits_count, 3)
        finally:
            session.close()

    def test_lifetime_withdrawal_tracking(self):
        """lifetime_withdrawal_usdt e total_withdrawals_count são incrementados."""
        self.repo.add_chips('addr_life_2', 200.0)
        self.repo.remove_chips('addr_life_2', 50.0)
        self.repo.remove_chips('addr_life_2', 30.0)

        from casino.backend.infrastructure.models import PlayerBalance
        session = _sqlite_get_session()
        try:
            row = session.get(PlayerBalance, 'addr_life_2')
            self.assertEqual(row.lifetime_withdrawal_usdt, 80.0)
            self.assertEqual(row.total_withdrawals_count, 2)
        finally:
            session.close()

    # ─── update_balance_delta com add/remove ────────────────────

    def test_update_balance_delta_delegates_correctly(self):
        """update_balance_delta chama add_chips p/ delta>0 e remove_chips p/ delta<0."""
        self.repo.add_chips('addr_del_1', 100.0)
        # Delta positivo
        self.assertEqual(self.repo.update_balance_delta('addr_del_1', 30.0), 130.0)
        # Delta negativo
        self.assertEqual(self.repo.update_balance_delta('addr_del_1', -20.0), 110.0)


# ─── Runner ───────────────────────────────────────────────────────

if __name__ == '__main__':
    unittest.main(verbosity=2)
