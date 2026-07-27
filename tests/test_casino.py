"""
Testes unitários para o cassino Kurama.
Testa: roleta, slots, blackjack, deposit_manager e game_manager.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
import time
from casino.backend.roulette import Roulette, RouletteBet, RouletteResult
from casino.backend.slots import SlotMachine, SlotResult
from casino.backend.blackjack import Blackjack, BlackjackHand, BlackjackSession
from casino.backend.deposit_manager import DepositManager, Deposit, DepositStatus
from casino.backend.game_manager import GameManager


class TestRoulette(unittest.TestCase):
    """Testes da Roleta Europeia."""

    def setUp(self):
        self.roulette = Roulette()

    def test_spin_range(self):
        """Giros da roleta devem estar entre 0 e 36."""
        for _ in range(100):
            result = self.roulette.spin()
            self.assertIn(result['number'], range(0, 37))
            self.assertIn(result['color'], ['red', 'black', 'green'])

    def test_color_zero(self):
        """Zero deve ser verde."""
        result = self.roulette.spin()
        if result['number'] == 0:
            self.assertEqual(result['color'], 'green')

    def test_bet_number_win(self):
        """Aposta em numero exato deve pagar 35:1."""
        bet = RouletteBet('number', 10, 7)
        self.assertTrue(bet.check_win(7))
        self.assertFalse(bet.check_win(8))
        self.assertEqual(bet.multiplier, 35.0)

    def test_bet_red(self):
        """Aposta em vermelho deve pagar 2:1."""
        bet = RouletteBet('red', 10)
        self.assertEqual(bet.multiplier, 2.0)
        # Numero 1 = vermelho
        self.assertTrue(bet.check_win(1))
        # Numero 2 = preto
        self.assertFalse(bet.check_win(2))

    def test_bet_odd_even(self):
        """Testa apostas par/impar."""
        odd_bet = RouletteBet('odd', 5)
        even_bet = RouletteBet('even', 5)
        self.assertTrue(odd_bet.check_win(1))
        self.assertFalse(odd_bet.check_win(2))
        self.assertTrue(even_bet.check_win(2))
        self.assertFalse(even_bet.check_win(1))

    def test_play_roulette(self):
        """Rodada completa de roleta."""
        bets = [
            RouletteBet('number', 10, 7),
            RouletteBet('red', 5),
        ]
        result = self.roulette.play('test_player', bets, 100.0)
        self.assertIsInstance(result, RouletteResult)
        self.assertEqual(result.player, 'test_player')
        self.assertEqual(result.bet_amount, 15.0)
        self.assertIn(result.number, range(0, 37))
        self.assertIn(result.color, ['red', 'black', 'green'])

    def test_validate_bet(self):
        """Validacao de aposta."""
        valid, msg = self.roulette.validate_bet(10.0, 100.0)
        self.assertTrue(valid)
        valid, msg = self.roulette.validate_bet(0.01, 100.0)
        self.assertFalse(valid)
        valid, msg = self.roulette.validate_bet(10000.0, 100.0)
        self.assertFalse(valid)


class TestSlots(unittest.TestCase):
    """Testes do Caca-niqueis."""

    def setUp(self):
        self.slots = SlotMachine()

    def test_spin_reels(self):
        """Spin deve retornar 4 simbolos crypto."""
        reels = self.slots.spin_reels()
        self.assertEqual(len(reels), 4)
        valid_ids = ['btc', 'eth', 'usdt', 'usd', 'btc2', 'eth2', 'usdt2', 'sol']
        for r in reels:
            self.assertIn(r, valid_ids)

    def test_play_slots(self):
        """Rodada completa de slots."""
        result = self.slots.play('test_player', 1.0, 100.0, lines=1)
        self.assertIsInstance(result, SlotResult)
        self.assertEqual(result.player, 'test_player')
        self.assertEqual(result.bet_amount, 1.0)

    def test_symbols_list(self):
        """Lista de simbolos deve ter 8 itens."""
        symbols = self.slots.get_symbols()
        self.assertEqual(len(symbols), 8)


class TestBlackjack(unittest.TestCase):
    """Testes do Blackjack."""

    def setUp(self):
        self.blackjack = Blackjack()

    def test_hand_value(self):
        """Testa calculo de valor da mao."""
        hand = BlackjackHand()
        hand.cards = [('A', 'copas'), ('K', 'ouros')]
        self.assertEqual(hand.get_value(), 21)
        self.assertTrue(hand.is_blackjack())

    def test_hand_value_with_aces(self):
        """Testa valor com Ases (11 ou 1)."""
        hand = BlackjackHand()
        hand.cards = [('A', 'kopas'), ('A', 'ouros')]
        self.assertEqual(hand.get_value(), 12)

    def test_bust(self):
        """Mao deve estourar acima de 21."""
        hand = BlackjackHand()
        hand.cards = [('K', 'kopas'), ('Q', 'ouros'), ('5', 'paus')]
        self.assertTrue(hand.is_busted())

    def test_play_blackjack(self):
        """Rodada completa de blackjack (modo auto)."""
        result = self.blackjack.play('test_player', 10.0, 100.0)
        self.assertIn('status', result)
        self.assertIn('player_hand', result)
        self.assertIn('dealer_hand', result)
        self.assertIn(result['status'], ['playing', 'finished'])
        self.assertIn(result['result_type'],
                     ['blackjack', 'bust', 'win', 'push', 'lose', 'dealer_bust', 'push_blackjack'])

    def test_blackjack_session_start(self):
        """Nova sessao de blackjack deve ter 2 cartas cada."""
        session = BlackjackSession('test_player', 10.0)
        self.assertEqual(len(session.player_hand.cards), 2)
        self.assertEqual(len(session.dealer_hand.cards), 2)
        self.assertIn(session.status, ['playing', 'finished'])

    def test_blackjack_hit_continues(self):
        """Hit so adiciona carta se mao nao estourou nem tem blackjack."""
        session = BlackjackSession('test_player', 10.0)
        if session.status == 'playing':
            card_count = len(session.player_hand.cards)
            session.hit()
            self.assertEqual(len(session.player_hand.cards), card_count + 1)
        else:
            # Ja terminou (blackjack inicial) - hit nao adiciona carta
            card_count = len(session.player_hand.cards)
            session.hit()
            self.assertEqual(len(session.player_hand.cards), card_count)

    def test_blackjack_session_stand(self):
        """Stand deve finalizar a partida (dealer joga)."""
        session = BlackjackSession('test_player', 10.0)
        session.stand()
        self.assertEqual(session.status, 'finished')
        # Inclui todos os result_types possiveis, incluindo
        # blackjack/push_blackjack (mao ja terminou ao nascer)
        # e bust (estourou no hit)
        self.assertIn(session.result_type,
                     ['win', 'push', 'lose', 'dealer_bust',
                      'blackjack', 'push_blackjack', 'bust'])


class TestDepositManager(unittest.TestCase):
    """Testes do Gerenciador de Depositos."""

    def setUp(self):
        self.dm = DepositManager()

    def test_deposit(self):
        """Deposito deve creditar fichas."""
        deposit = self.dm.deposit('test_addr', 100.0)
        self.assertEqual(deposit.amount_usdt, 100.0)
        self.assertEqual(deposit.chips_amount, 100.0)
        self.assertEqual(deposit.status, DepositStatus.PENDING)
        self.assertEqual(self.dm.get_balance('test_addr'), 100.0)

    def test_withdraw(self):
        """Saque deve debitar fichas."""
        self.dm.deposit('test_addr', 100.0)
        withdraw = self.dm.withdraw('test_addr', 30.0)
        self.assertEqual(withdraw.chips_amount, 30.0)
        self.assertEqual(self.dm.get_balance('test_addr'), 70.0)

    def test_insufficient_balance(self):
        """Saque com saldo insuficiente deve falhar."""
        with self.assertRaises(ValueError):
            self.dm.withdraw('test_addr', 100.0)

    def test_deposit_confirm(self):
        """Confirmacao de deposito."""
        deposit = self.dm.deposit('test_addr', 50.0)
        deposit.confirm('kur_tx_test123')
        self.assertEqual(deposit.kurama_tx_id, 'kur_tx_test123')
        self.assertEqual(deposit.status, DepositStatus.CONFIRMED)

    def test_balance_update(self):
        """Atualizacao de saldo (para pagamentos de jogos)."""
        self.dm.deposit('test_addr', 100.0)
        self.dm.update_balance('test_addr', 50.0)  # Ganhou 50
        self.assertEqual(self.dm.get_balance('test_addr'), 150.0)
        self.dm.update_balance('test_addr', -30.0)  # Perdeu 30
        self.assertEqual(self.dm.get_balance('test_addr'), 120.0)


class TestGameManager(unittest.TestCase):
    """Testes do Gerenciador de Jogos."""

    def setUp(self):
        self.dm = DepositManager()
        self.gm = GameManager(deposit_manager=self.dm)

    def test_available_games(self):
        """Deve listar 3 jogos."""
        games = self.gm.get_available_games()
        self.assertEqual(len(games), 4)
        game_ids = [g['id'] for g in games]
        self.assertIn('roulette', game_ids)
        self.assertIn('slots', game_ids)
        self.assertIn('blackjack', game_ids)

    def test_player_balance(self):
        """Saldo do jogador."""
        self.dm.deposit('test_player', 200.0)
        self.assertEqual(self.gm.get_player_balance('test_player'), 200.0)

    def test_play_roulette_through_manager(self):
        """Rodada de roleta via GameManager."""
        self.dm.deposit('test_player', 100.0)
        bets = [{'bet_type': 'red', 'amount': 10}]
        result = self.gm.play_roulette('test_player', bets, 100.0)
        self.assertIn('game', result)
        self.assertEqual(result['game'], 'roleta')

    def test_play_slots_through_manager(self):
        """Rodada de slots via GameManager."""
        self.dm.deposit('test_player', 100.0)
        result = self.gm.play_slots('test_player', 1.0, 100.0, lines=1)
        self.assertIn('game', result)
        self.assertEqual(result['game'], 'slots')

    def test_blackjack_start_through_manager(self):
        """Iniciar blackjack via GameManager."""
        self.dm.deposit('test_player', 100.0)
        result = self.gm.blackjack_start('test_player', 10.0, 100.0)
        self.assertIn('player_hand', result)
        self.assertIn('dealer_hand', result)

    def test_casino_stats(self):
        """Estatisticas do cassino."""
        stats = self.gm.get_casino_stats()
        self.assertIn('total_players', stats)
        self.assertIn('total_bets', stats)
        self.assertIn('total_payouts', stats)
        self.assertIn('house_edge', stats)

    def test_player_history(self):
        """Historico do jogador."""
        self.dm.deposit('test_player', 100.0)
        self.gm.play_roulette('test_player', [{'bet_type': 'red', 'amount': 10}], 100.0)
        history = self.gm.get_player_history('test_player')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['game'], 'roleta')


if __name__ == '__main__':
    unittest.main()
