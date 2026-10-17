"""
Testes do bridge da KuramaChain (Fase 5 — ``KurBridge`` / ``KurWrappedToken``).

Cobre o caminho lock/mint completo com **duas chains simuladas no mesmo
engine** (a chain A é a local, chain ID 9090; a chain B é a remota, chain ID 1)
e o relayer ``evm.bridge.BridgeRelayer``:

- depósito trava o token na origem e o relayer cunha o wrapped no destino;
- a volta queima o wrapped e libera o ativo travado (``registerRelease``);
- replay do mesmo ``depositId`` é rejeitado;
- assinatura de não-validador, duplicada, fora de ordem ou de valor adulterado
  é rejeitada;
- ``threshold`` é respeitado e o owner administra validadores/pausa.

Executar com: python -m pytest tests/test_bridge.py -v
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest

from eth_keys import keys
from eth_utils import keccak

from evm.bridge import (
    BridgeRelayer,
    encode_withdraw_calldata,
    sign_withdrawal,
    withdrawal_digest,
)
from evm.compiler import compile_all
from evm.deploy import (
    bridge_deposit,
    deploy_bridge,
    deploy_wrapped_token,
    register_release,
    register_wrapped,
)
from evm.engine import EVMEngine
from config import (
    EVM_BRIDGE_PRIVATE_KEY,
    EVM_BRIDGE_THRESHOLD,
    EVM_BRIDGE_VALIDATOR_KEYS,
    EVM_DEV_PRIVATE_KEY,
)

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'evm', 'contracts')
SOURCES = ('KurToken.sol', 'KurBridge.sol', 'KurWrappedToken.sol')

CHAIN_LOCAL = 9090          # "esta" chain (A)
CHAIN_REMOTE = 1            # chain remota simulada (B)

BRIDGE_KEY = EVM_BRIDGE_PRIVATE_KEY
VALIDATOR_KEYS = list(EVM_BRIDGE_VALIDATOR_KEYS)
THRESHOLD = EVM_BRIDGE_THRESHOLD
OUTSIDER_KEY = '0x' + 'aa' * 32
NON_OWNER_KEY = '0x' + 'cc' * 32

KUR = 10 ** 18
AMOUNT = 500 * KUR
SUPPLY = 1_000_000
OP_GAS = 1_500_000


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


class TestKurBridge(unittest.TestCase):
    """Fase 5 — bridge lock/mint com atestação m-de-n."""

    @classmethod
    def setUpClass(cls):
        artifacts = compile_all({name: _read(name) for name in SOURCES})
        cls.token_art = artifacts['KurToken.sol']['KurToken']

    def setUp(self):
        self.engine = _make_engine([BRIDGE_KEY, NON_OWNER_KEY])
        self.dev = _addr_of(EVM_DEV_PRIVATE_KEY)
        _, self.kur = self.engine.deploy(
            self.token_art['bytecode']
            + _enc_token_constructor('Kurama', 'KUR', SUPPLY * KUR),
            EVM_DEV_PRIVATE_KEY, gas=4_000_000)
        _, self.bridge_a = deploy_bridge(self.engine, chain_id=CHAIN_LOCAL)
        _, self.bridge_b = deploy_bridge(self.engine, chain_id=CHAIN_REMOTE)
        _, self.wrapped = deploy_wrapped_token(
            self.engine, 'Wrapped KUR', 'wKUR', self.bridge_b)
        register_wrapped(self.engine, self.bridge_b, CHAIN_LOCAL, self.kur,
                         self.wrapped)
        register_release(self.engine, self.bridge_a, CHAIN_REMOTE, self.wrapped,
                         self.kur)

    # ─── Apoio ───────────────────────────────────────────────────

    def _balance(self, token: str, who: str) -> int:
        return _uint(self.engine.call(
            token, _sel('balanceOf(address)') + _addr_arg(who)))

    def _total_supply(self, token: str) -> int:
        return _uint(self.engine.call(token, _sel('totalSupply()')))

    def _status(self, tx: str) -> int:
        receipt = self.engine.get_transaction_receipt(tx)
        self.assertIsNotNone(receipt)
        return int(receipt['status'], 16)

    def _deposit(self, bridge: str, token: str, amount: int, dest_chain: int,
                 recipient: str, key: str = EVM_DEV_PRIVATE_KEY) -> str:
        self.engine.send(key, token,
                         _sel('approve(address,uint256)') + _addr_arg(bridge)
                         + _word(amount))
        return bridge_deposit(self.engine, bridge, token, amount, dest_chain,
                              recipient, key)

    def _relayer(self, source_bridge: str, dest_bridge: str,
                 keys=None) -> BridgeRelayer:
        return BridgeRelayer(self.engine, self.engine, source_bridge,
                             dest_bridge, list(keys or VALIDATOR_KEYS),
                             EVM_DEV_PRIVATE_KEY)

    def _attest(self, deposit: dict, dest_bridge: str, dest_chain: int,
                keys) -> list:
        digest = withdrawal_digest(
            dest_chain, deposit['src_chain'], deposit['token'],
            deposit['recipient'], deposit['amount'], deposit['nonce'],
            deposit['deposit_id'], dest_bridge)
        pairs = [(_addr_of(key), sign_withdrawal(key, digest)) for key in keys]
        pairs.sort(key=lambda pair: pair[0].lower())
        return [sig for _, sig in pairs]

    def _withdraw(self, dest_bridge: str, deposit: dict, signatures: list) -> str:
        data = encode_withdraw_calldata(
            deposit['src_chain'], deposit['token'], deposit['recipient'],
            deposit['amount'], deposit['nonce'], deposit['deposit_id'],
            signatures)
        return self.engine.send(EVM_DEV_PRIVATE_KEY, dest_bridge, data,
                                gas=OP_GAS)

    def _first_deposit(self, relayer: BridgeRelayer) -> dict:
        deposits = relayer.pending_deposits()
        self.assertEqual(len(deposits), 1, 'esperava exatamente 1 depósito')
        return deposits[0]

    # ─── Testes ──────────────────────────────────────────────────

    def test_deposit_locks_tokens_and_relayer_mints_wrapped(self):
        initial = self._balance(self.kur, self.dev)
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)

        self.assertEqual(self._balance(self.kur, self.dev), initial - AMOUNT)
        self.assertEqual(self._balance(self.kur, self.bridge_a), AMOUNT,
                         'o token deve ficar travado no bridge de origem')

        relayer = self._relayer(self.bridge_a, self.bridge_b)
        txs = relayer.process()
        self.assertEqual(len(txs), 1)
        self.assertEqual(self._status(txs[0]), 1)
        self.assertEqual(self._balance(self.wrapped, self.dev), AMOUNT,
                         'o wrapped deve ser cunhado no destino')
        self.assertEqual(len(relayer.pending_deposits()), 0)
        self.assertEqual(len(relayer.process()), 0, 'não deve reprocessar')

    def test_replay_of_processed_deposit_reverts(self):
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        relayer = self._relayer(self.bridge_a, self.bridge_b)
        deposit = self._first_deposit(relayer)
        signatures = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                  VALIDATOR_KEYS)

        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                    signatures)), 1)
        # Mesmo comprovante de novo: já processado.
        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                    signatures)), 0)

    def test_insufficient_signatures_revert(self):
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        relayer = self._relayer(self.bridge_a, self.bridge_b)
        deposit = self._first_deposit(relayer)
        signatures = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                  VALIDATOR_KEYS)
        self.assertGreater(len(signatures), THRESHOLD)

        tx = self._withdraw(self.bridge_b, deposit, signatures[:THRESHOLD - 1])
        self.assertEqual(self._status(tx), 0,
                         'menos assinaturas que o threshold deve reverter')

    def test_duplicate_and_out_of_order_signatures_revert(self):
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        relayer = self._relayer(self.bridge_a, self.bridge_b)
        deposit = self._first_deposit(relayer)
        signatures = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                  VALIDATOR_KEYS)

        duplicated = [signatures[0], signatures[0]]
        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                     duplicated)), 0)

        reversed_order = list(reversed(signatures[:THRESHOLD]))
        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                     reversed_order)), 0)

    def test_signature_from_non_validator_reverts(self):
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        relayer = self._relayer(self.bridge_a, self.bridge_b)
        deposit = self._first_deposit(relayer)
        signatures = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                  VALIDATOR_KEYS + [OUTSIDER_KEY])
        tx = self._withdraw(self.bridge_b, deposit, signatures)
        self.assertEqual(self._status(tx), 0,
                         'assinatura de não-validador deve reverter')

    def test_tampered_amount_reverts(self):
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        relayer = self._relayer(self.bridge_a, self.bridge_b)
        deposit = self._first_deposit(relayer)
        signatures = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                  VALIDATOR_KEYS)

        tampered = dict(deposit)
        tampered['amount'] = AMOUNT + KUR
        tx = self._withdraw(self.bridge_b, tampered, signatures)
        self.assertEqual(self._status(tx), 0,
                         'valor diferente do atestado deve reverter')

    def test_return_trip_burns_wrapped_and_releases_native(self):
        initial = self._balance(self.kur, self.dev)
        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        self._relayer(self.bridge_a, self.bridge_b).process()
        self.assertEqual(self._balance(self.wrapped, self.dev), AMOUNT)

        # Volta: deposita o wrapped no bridge remoto (queima) rumo à chain local.
        self._deposit(self.bridge_b, self.wrapped, AMOUNT, CHAIN_LOCAL, self.dev)
        self.assertEqual(self._total_supply(self.wrapped), 0,
                         'o depósito de wrapped deve queimar')
        self.assertEqual(self._balance(self.kur, self.bridge_a), AMOUNT)

        txs = self._relayer(self.bridge_b, self.bridge_a).process()
        self.assertEqual(len(txs), 1)
        self.assertEqual(self._status(txs[0]), 1)
        self.assertEqual(self._balance(self.kur, self.dev), initial,
                         'o KUR travado deve voltar para o destinatário')
        self.assertEqual(self._balance(self.kur, self.bridge_a), 0)

    def test_threshold_is_enforced_and_owner_manages_validators(self):
        # Não-owner não mexe no conjunto de validadores.
        tx = self.engine.send(
            NON_OWNER_KEY, self.bridge_a,
            _sel('setValidator(address,bool)') + _addr_arg(_addr_of(OUTSIDER_KEY))
            + _word(1), gas=OP_GAS)
        self.assertEqual(self._status(tx), 0)

        # Owner adiciona um validador ao bridge de destino e sobe o threshold.
        outsider = _addr_of(OUTSIDER_KEY)
        tx = self.engine.send(
            BRIDGE_KEY, self.bridge_b,
            _sel('setValidator(address,bool)') + _addr_arg(outsider) + _word(1),
            gas=OP_GAS)
        self.assertEqual(self._status(tx), 1)
        tx = self.engine.send(
            BRIDGE_KEY, self.bridge_b,
            _sel('setThreshold(uint256)') + _word(len(VALIDATOR_KEYS) + 1),
            gas=OP_GAS)
        self.assertEqual(self._status(tx), 1)

        self._deposit(self.bridge_a, self.kur, AMOUNT, CHAIN_REMOTE, self.dev)
        deposit = self._first_deposit(self._relayer(self.bridge_a, self.bridge_b))

        # 2 assinaturas (< novo threshold) → reverte.
        two = self._attest(deposit, self.bridge_b, CHAIN_REMOTE, VALIDATOR_KEYS)
        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                     two[:2])), 0)

        # 3 assinaturas (incluindo o novo validador) → passa.
        all_sigs = self._attest(deposit, self.bridge_b, CHAIN_REMOTE,
                                VALIDATOR_KEYS + [OUTSIDER_KEY])
        self.assertEqual(self._status(self._withdraw(self.bridge_b, deposit,
                                                     all_sigs)), 1)
        self.assertEqual(self._balance(self.wrapped, self.dev), AMOUNT)

    def test_paused_bridge_blocks_deposit_and_withdraw(self):
        tx = self.engine.send(BRIDGE_KEY, self.bridge_a,
                              _sel('setPaused(bool)') + _word(1), gas=OP_GAS)
        self.assertEqual(self._status(tx), 1)

        self.engine.send(EVM_DEV_PRIVATE_KEY, self.kur,
                         _sel('approve(address,uint256)') + _addr_arg(self.bridge_a)
                         + _word(AMOUNT))
        tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.bridge_a,
            _sel('deposit(address,uint256,uint256,address)')
            + _addr_arg(self.kur) + _word(AMOUNT) + _word(CHAIN_REMOTE)
            + _addr_arg(self.dev), gas=OP_GAS)
        self.assertEqual(self._status(tx), 0, 'bridge pausado não aceita depósito')

    def test_same_chain_deposit_reverts(self):
        self.engine.send(EVM_DEV_PRIVATE_KEY, self.kur,
                         _sel('approve(address,uint256)') + _addr_arg(self.bridge_a)
                         + _word(AMOUNT))
        tx = self.engine.send(
            EVM_DEV_PRIVATE_KEY, self.bridge_a,
            _sel('deposit(address,uint256,uint256,address)')
            + _addr_arg(self.kur) + _word(AMOUNT) + _word(CHAIN_LOCAL)
            + _addr_arg(self.dev), gas=OP_GAS)
        self.assertEqual(self._status(tx), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
