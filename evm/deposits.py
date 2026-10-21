"""
Depósitos nativo → EVM da KuramaChain.

A camada nativa e a EVM têm estados separados: uma transação nativa para um
endereço ``0x...`` não altera o state trie da EVM, então a carteira
(Rabby/MetaMask) não vê o saldo. Este módulo faz a ponte:

- **crédito imediato**: cada envio nativo para ``0x...`` é creditado na EVM
  por uma transferência assinada pela reserva de demo (conta de dev,
  financiada no gênesis) — modelo *lock* (nativo) / *mint* (EVM);
- **reconciliação no startup**: como o estado EVM é em memória e recomeça do
  gênesis, os depósitos já minerados no ledger nativo (que é persistido em
  disco) são recreditados ao subir o nó;
- **ledger**: mapa ``transaction_id`` nativo → hash da tx EVM, persistido em
  ``DATA_DIR/evm_deposits.json`` para o explorer mostrar o depósito.
"""
import json
import logging
import os
import threading
from decimal import Decimal, InvalidOperation

from config import DATA_DIR, EVM_DEV_PRIVATE_KEY
from core.crypto_utils import CryptoUtils

logger = logging.getLogger(__name__)

# Transferência de valor sem calldata.
TRANSFER_GAS = 21_000

_LEDGER_LOCK = threading.Lock()


def kur_to_wei(amount) -> int:
    """Converte KUR para wei via Decimal (sem erro de ponto flutuante)."""
    try:
        return int((Decimal(str(amount)) * 10 ** 18).to_integral_value())
    except (InvalidOperation, ValueError):
        raise ValueError(f'Quantidade inválida: {amount!r}')


def ledger_path() -> str:
    # EVM_DEPOSIT_LEDGER permite isolar testes (default: DATA_DIR).
    return os.environ.get('EVM_DEPOSIT_LEDGER') \
        or os.path.join(DATA_DIR, 'evm_deposits.json')


def load_ledger() -> dict:
    """Carrega o mapa ``transaction_id`` nativo → hash EVM ('' se não houver)."""
    path = ledger_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('[EVM] ledger de depósitos ilegível (%s): %s', path, exc)
        return {}


def _save_ledger(ledger: dict) -> None:
    path = ledger_path()
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        # O crédito já foi feito on-chain; falhar aqui só perde o índice.
        logger.warning('[EVM] não foi possível salvar o ledger de depósitos: %s', exc)


def record_deposit(native_tx_id: str, evm_tx_hash: str, receiver: str,
                   amount: float) -> None:
    """Registra o depósito de uma tx nativa (idempotente por transaction_id)."""
    if not native_tx_id:
        return
    with _LEDGER_LOCK:
        ledger = load_ledger()
        ledger[native_tx_id] = {
            'evm_tx_hash': evm_tx_hash,
            'receiver': receiver,
            'amount': amount,
        }
        _save_ledger(ledger)


def get_deposit_hash(native_tx_id: str, ledger: dict = None):
    """Hash da tx EVM que creditou uma tx nativa (ou None)."""
    entry = (ledger if ledger is not None else load_ledger()).get(native_tx_id)
    if isinstance(entry, dict):
        return entry.get('evm_tx_hash')
    return entry if isinstance(entry, str) else None


def credit_native_deposit(engine, receiver: str, amount: float,
                          native_tx_id: str = None) -> str:
    """
    Credita ``amount`` KUR na EVM de ``receiver`` a partir da reserva de demo.

    Returns:
        Hash da transação EVM.

    Raises:
        ValueError: destino inválido, valor inválido ou reserva insuficiente.
    """
    if not CryptoUtils.is_valid_evm_address(receiver):
        raise ValueError(f'Destino não é endereço EVM: {receiver!r}')
    wei = kur_to_wei(amount)
    if wei <= 0:
        raise ValueError('Valor do depósito deve ser positivo')
    reserve = engine.get_balance(engine.dev_address)
    if reserve < wei:
        raise ValueError(
            f'Reserva EVM insuficiente: {reserve / 10 ** 18:.4f} KUR '
            f'para creditar {amount:g} KUR'
        )
    evm_tx_hash = engine.send(
        EVM_DEV_PRIVATE_KEY, receiver, b'', value=wei, gas=TRANSFER_GAS,
    )
    if native_tx_id:
        record_deposit(native_tx_id, evm_tx_hash, receiver, amount)
    return evm_tx_hash


def reconcile_native_deposits(blockchain, engine) -> dict:
    """
    Recredita na EVM todos os depósitos nativos já minerados para endereços 0x.

    Roda uma vez por processo (o estado EVM é em memória e recomeça do
    gênesis a cada start; o ledger nativo é persistido). Transações que não
    couberem na reserva são puladas e reportadas, sem derrubar o nó.

    Returns:
        ``{'credited': int, 'failed': [transaction_id, ...]}``
    """
    report = {'credited': 0, 'failed': []}
    if getattr(engine, '_native_deposits_reconciled', False):
        return report
    engine._native_deposits_reconciled = True

    for block in getattr(blockchain, 'chain', []):
        for tx in block.transactions:
            data = tx.to_dict() if hasattr(tx, 'to_dict') else tx
            receiver = data.get('receiver') or ''
            if not CryptoUtils.is_valid_evm_address(receiver):
                continue
            native_tx_id = data.get('transaction_id') or data.get('hash')
            try:
                credit_native_deposit(
                    engine, receiver, float(data.get('amount') or 0),
                    native_tx_id,
                )
                report['credited'] += 1
            except Exception as exc:
                logger.warning('[EVM] depósito %s não recreditado: %s',
                               native_tx_id, exc)
                report['failed'].append(native_tx_id)

    if report['credited'] or report['failed']:
        logger.info('[EVM] reconciliação: %s depósito(s) creditado(s), '
                    '%s falha(s)', report['credited'], len(report['failed']))
    return report
