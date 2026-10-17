"""
Testes do staking da KuramaChain (Fase 5 — ``KurStaking``).

Cobre:
- criação de pool (KUR → KUR), orçamento de recompensa e info do pool;
- accrual de recompensa por segundo, ``claim`` e ``pendingReward``;
- ``withdraw`` devolvendo o principal e ``emergencyWithdraw`` sem prêmio;
- recompensa nunca sai do principal (``rewardBudget``) e para em ``rewardEnd``;
- apenas o owner cria/configura pools.

O relógio da EVM é fixado com ``engine.advance_time(0)``: cada bloco avança
exatamente 1s, então o accrual é determinístico (com tolerância de poucos
segundos pelos blocos de aprovação/stake).

Executar com: python -m pytest tests/test_staking.py -v
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.compiler import compile_all
from evm.deploy import (
    claim_rewards,
    create_staking_pool,
    deploy_staking,
    fund_staking_pool,
    stake_tokens,
    unstake_tokens,
)
from evm.engine import EVMEngine
from config import EVM_DEV_PRIVATE_KEY, EVM_STAKING_PRIVATE_KEY

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'evm', 'contracts')
SOURCES = ('KurToken.sol', 'KurStaking.sol')

STAKING_KEY = EVM_STAKING_PRIVATE_KEY
OTHER_KEY = '0x' + 'ee' * 32

KUR = 10 ** 18
RATE = 10 ** 17          # 0.1 KUR por segundo
OP_GAS = 1_000_000
SUPPLY = 1_000_000       # KUR iniciais do deployer


# ─── Helpers ─────────────────────────────────────────────────────

def _read(name: str) -> str:
    with open(os.path.join(CONTRACTS_DIR, name), encoding='utf-8') as fh:
        return fh.read()


def _sel(sig: str) -> bytes:
    return keccak(text=sig)[:4]


def _addr_of(private_key: str) -> str:
    return '0x' + keys.PrivateKey(
        bytes.fromhex(private_key[2:])).public_key.to_address()[2:]


def _addr_arg(address: str) -> bytes:
    return bytes.fromhex(address[2:]).rjust(32, b'\x00')


def _word(value: int) -> bytes:
    return int(value).to_bytes(32, 'big')


def _uint(data) -> int:
    return int.from_bytes(bytes(data)[:32], 'big')


def _enc_string(s: str) -> bytes:
    b = s.encode()
    pad = (32 - len(b) % 32) % 32
    return len(b).to_bytes(32, 'big') + b + b'\x00' * pad


def _enc_token_constructor(name: str, symbol: str, supply: int) -> bytes:
    return (((3 * 32).to_bytes(32, 'big')
             + (3 * 32 + 64).to_bytes(32, 'big')
             + supply.to_bytes(32, 'big'))
            + _enc_string(name) + _enc_string(symbol))


def _make_engine(funded_keys=()) -> EVMEngine:
    accounts = {_addr_of(key): 1_000.0 for key in funded_keys}
    engine = EVMEngine(auto_mine=True, genesis_accounts=accounts)
    engine.advance_time(0)
    return engine


# ─── Testes ──────────────────────────────────────────────────────

class TestKurStaking(unittest.TestCase):
    """Fase 5 — pools de staking/farming."""

    @classmethod
    def setUpClass(cls):
        artifacts = compile_all({name: _read(name) for name in SOURCES})
        cls.token_art = artifacts['KurToken.sol']['KurToken']

    def setUp(self):
        self.engine = _make_engine([STAKING_KEY, OTHER_KEY])
        self.dev = _addr_of(EVM_DEV_PRIVATE_KEY)
        self.staking_addr = _addr_of(STAKING_KEY)
        _, self.kur = self.engine.deploy(
            self.token_art['bytecode']
            + _enc_token_constructor('Kurama', 'KUR', SUPPLY * KUR),
            EVM_DEV_PRIVATE_KEY, gas=4_000_000)
        _, self.staking = deploy_staking(self.engine)
        # O owner do pool precisa de KUR para abastecer o orçamento.
        self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.kur,
            _sel('transfer(address,uint256)') + _addr_arg(self.staking_addr)
            + _word(10_000 * KUR))

    # ─── Apoio ───────────────────────────────────────────────────

    def _balance(self, who: str) -> int:
        return _uint(self.engine.call(
            self.kur, _sel('balanceOf(address)') + _addr_arg(who)))

    def _create_pool(self, rate=RATE, reward=500 * KUR, duration=100_000):
        """Cria um pool KUR → KUR com orçamento abastecido. Devolve o pid."""
        end = self.engine.block_timestamp + duration
        _, pid = create_staking_pool(self.engine, self.staking, self.kur,
                                     self.kur, rate, end)
        self.engine.send(
            STAKING_KEY, self.kur,
            _sel('approve(address,uint256)') + _addr_arg(self.staking)
            + _word(reward))
        fund_staking_pool(self.engine, self.staking, pid, reward)
        return pid

    def _approve_staking(self, who_key: str, amount=10 ** 24):
        self.engine.send(
            who_key, self.kur,
            _sel('approve(address,uint256)') + _addr_arg(self.staking)
            + _word(amount))

    def _pending(self, pid: int, who: str) -> int:
        return _uint(self.engine.call(
            self.staking,
            _sel('pendingReward(uint256,address)') + _word(pid) + _addr_arg(who)))

    def _pool_info(self, pid: int) -> dict:
        out = bytes(self.engine.call(
            self.staking, _sel('poolInfo(uint256)') + _word(pid)))
        words = [int.from_bytes(out[i * 32:(i + 1) * 32], 'big') for i in range(7)]
        return {
            'staking_token': '0x' + out[12:32].hex(),
            'reward_token': '0x' + out[44:64].hex(),
            'reward_rate': words[2],
            'reward_end': words[3],
            'total_staked': words[4],
            'reward_budget': words[6],
        }

    def _status(self, tx: str) -> int:
        receipt = self.engine.get_transaction_receipt(tx)
        self.assertIsNotNone(receipt)
        return int(receipt['status'], 16)

    # ─── Testes ──────────────────────────────────────────────────

    def test_create_pool_registers_info_and_budget(self):
        pid = self._create_pool()
        self.assertEqual(pid, 0)
        info = self._pool_info(pid)
        self.assertEqual(info['staking_token'].lower(), self.kur.lower())
        self.assertEqual(info['reward_token'].lower(), self.kur.lower())
        self.assertEqual(info['reward_rate'], RATE)
        self.assertEqual(info['reward_budget'], 500 * KUR)
        self.assertEqual(info['total_staked'], 0)

    def test_stake_accrues_rewards_per_second(self):
        pid = self._create_pool()
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)

        self.assertEqual(self._pool_info(pid)['total_staked'], 100 * KUR)
        # Tolerância de 1s: a py-evm executa a tx com o timestamp do bloco
        # anterior e só depois sela o header novo (dust conhecido do engine).
        self.assertLessEqual(self._pending(pid, self.dev), 2 * RATE,
                             'sem tempo relevante decorrido, o prêmio é ~0')

        self.engine.advance_time(100)
        pending = self._pending(pid, self.dev)
        # ~101s (o bloco do stake já consome 1s) — tolerância de poucos segundos.
        self.assertGreaterEqual(pending, 100 * RATE)
        self.assertLessEqual(pending, 104 * RATE)

    def test_claim_pays_rewards_and_resets_pending(self):
        pid = self._create_pool()
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)
        self.engine.advance_time(100)

        before = self._balance(self.dev)
        claim_rewards(self.engine, self.staking, pid, EVM_DEV_PRIVATE_KEY)
        paid = self._balance(self.dev) - before

        self.assertGreaterEqual(paid, 100 * RATE)
        self.assertLessEqual(paid, 104 * RATE)
        self.assertLessEqual(self._pending(pid, self.dev), 2 * RATE,
                             'após o claim, o pendente deve zerar (~dust de 1s)')
        self.assertEqual(self._pool_info(pid)['reward_budget'], 500 * KUR - paid)

    def test_unstake_returns_principal(self):
        pid = self._create_pool()
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)
        self.engine.advance_time(10)

        before = self._balance(self.dev)
        unstake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)

        self.assertEqual(self._balance(self.dev) - before, 100 * KUR)
        self.assertEqual(self._pool_info(pid)['total_staked'], 0)

    def test_claim_stops_when_budget_is_exhausted(self):
        """O principal NUNCA é usado para pagar prêmio: sem orçamento, claim reverte."""
        rate = 1 * KUR          # 1 KUR/s
        pid = self._create_pool(rate=rate, reward=1 * KUR, duration=100_000)
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)
        self.engine.advance_time(100)          # ~100 KUR devidos, orçamento de 1 KUR

        self.assertGreater(self._pending(pid, self.dev), 1 * KUR)
        with self.assertRaises(RuntimeError):
            claim_rewards(self.engine, self.staking, pid, EVM_DEV_PRIVATE_KEY)

        # O principal continua intacto e sacável.
        before = self._balance(self.dev)
        unstake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)
        self.assertEqual(self._balance(self.dev) - before, 100 * KUR)

    def test_emission_stops_at_reward_end(self):
        pid = self._create_pool(rate=RATE, reward=10_000 * KUR, duration=100)
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 100 * KUR, EVM_DEV_PRIVATE_KEY)

        self.engine.advance_time(1_000)        # muito depois do fim da emissão
        pending = self._pending(pid, self.dev)

        self.assertGreaterEqual(pending, 95 * RATE)
        self.assertLessEqual(pending, 110 * RATE,
                             'a emissão deve parar em rewardEnd')

    def test_emergency_withdraw_returns_principal_without_reward(self):
        pid = self._create_pool()
        self._approve_staking(EVM_DEV_PRIVATE_KEY)
        stake_tokens(self.engine, self.staking, pid, 50 * KUR, EVM_DEV_PRIVATE_KEY)
        self.engine.advance_time(100)
        self.assertGreater(self._pending(pid, self.dev), 0)

        before = self._balance(self.dev)
        tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.staking,
            _sel('emergencyWithdraw(uint256)') + _word(pid))
        self.assertEqual(self._status(tx), 1)

        self.assertEqual(self._balance(self.dev) - before, 50 * KUR)
        self.assertEqual(self._pending(pid, self.dev), 0)
        self.assertEqual(self._pool_info(pid)['total_staked'], 0)

    def test_only_owner_can_create_or_fund_pools(self):
        pid = self._create_pool()
        # Chave não-owner tentando criar um pool novo.
        end = self.engine.block_timestamp + 1_000
        data = (_sel('createPool(address,address,uint256,uint256)')
                + _addr_arg(self.kur) + _addr_arg(self.kur)
                + _word(RATE) + _word(end))
        tx = self.engine.send(OTHER_KEY, self.staking, data, gas=OP_GAS)
        self.assertEqual(self._status(tx), 0)

        # Chave não-owner tentando abastecer o pool existente.
        tx = self.engine.send(
            OTHER_KEY, self.staking,
            _sel('fundPool(uint256,uint256)') + _word(pid) + _word(KUR),
            gas=OP_GAS)
        self.assertEqual(self._status(tx), 0)

    def test_stake_without_allowance_reverts(self):
        pid = self._create_pool()
        tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.staking,
            _sel('stake(uint256,uint256)') + _word(pid) + _word(10 * KUR),
            gas=OP_GAS)
        self.assertEqual(self._status(tx), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
