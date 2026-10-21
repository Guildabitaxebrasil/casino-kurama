"""
Camada de execução EVM da KuramaChain (Fase 0).

Integra uma EVM (py-evm) à blockchain existente, mantendo o consenso PoW:

- O **estado** deixa de ser "saldos por endereço" e passa a ser o state trie
  de contas EVM (nonce, balance, code, storage).
- Cada vez que a KuramaChain minera um bloco PoW, a EVM **sela** um bloco
  contendo as transações EVM pendentes (via o evento ``on_block_mined``).
- Contratos Solidity podem ser deployados e executados.

Usamos o fork **London** porque é o último fork com Proof of Work (o Paris
"Merge" força difficulty=0). O consenso é ``NoProofConsensus`` — o PoW é
responsabilidade da própria KuramaChain, não do ethash.
"""
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from eth.consensus import NoProofConsensus
from eth.consensus.applier import ConsensusApplier
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks import LondonVM
from eth.vm.forks.london.transactions import LondonTransactionBuilder
from eth.vm.message import Message
from eth_keys import keys
from eth_utils import to_checksum_address, to_wei
from eth._utils.address import generate_contract_address

from config import (
    EVM_CHAIN_ID, EVM_GAS_LIMIT, EVM_DEFAULT_GAS_PRICE,
    EVM_DEFAULT_GAS, EVM_GENESIS_BALANCE_ETH, EVM_GENESIS_ACCOUNTS,
    EVM_DEV_PRIVATE_KEY,
)

# Chave descartável usada apenas para simular ``eth_call`` (não precisa de
# saldo: as chamadas de leitura usam value=0 e o "costless state" da py-evm).
logger = logging.getLogger(__name__)

_CALL_KEY = bytes.fromhex('0f' * 32)
_CALL_SENDER = keys.PrivateKey(_CALL_KEY).public_key.to_canonical_address()


def _word_bytes(value, size: int = 32) -> bytes:
    """Normaliza uma palavra ABI que o py-evm devolve como int ou bytes."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return int(value).to_bytes(size, 'big')


def _to_canonical(address) -> bytes:
    """Converte '0x...' (ou bytes) em endereço canônico de 20 bytes."""
    if isinstance(address, (bytes, bytearray)):
        return bytes(address)
    if not address:
        return b''
    if address.startswith('0x') or address.startswith('0X'):
        return bytes.fromhex(address[2:])
    raise ValueError(f'Endereço inválido (esperado 0x...): {address!r}')


class EVMEngine:
    """
    Motor EVM da KuramaChain.

    Thread-safe: um lock serializa o acesso à cadeia EVM (deploy, envio de
    transações e selagem de blocos).
    """

    def __init__(self, chain_id: int = None, auto_mine: bool = True,
                 genesis_accounts: Optional[Dict[str, float]] = None):
        """
        Args:
            chain_id: ID da cadeia EVM (default: config).
            auto_mine: se True, cada transação sela um bloco imediatamente
                (modo dev, estilo Hardhat/Ganache). Se False, as transações
                ficam pendentes até ``seal_block()`` (chamado no PoW).
            genesis_accounts: mapa ``{endereco_0x: saldo_em_ETH}`` para o gênese.
        """
        self.chain_id = chain_id or EVM_CHAIN_ID
        self.auto_mine = auto_mine
        self._lock = threading.RLock()

        genesis_state = {}
        accounts = dict(genesis_accounts if genesis_accounts is not None
                        else EVM_GENESIS_ACCOUNTS)
        # Financia a conta de desenvolvimento (para demo/testes sem precisar
        # de faucet). Derivada da chave EVM_DEV_PRIVATE_KEY.
        dev_priv = keys.PrivateKey(bytes.fromhex(
            EVM_DEV_PRIVATE_KEY[2:] if EVM_DEV_PRIVATE_KEY.startswith('0x')
            else EVM_DEV_PRIVATE_KEY))
        dev_address = '0x' + dev_priv.public_key.to_address()[2:]
        # Endereço da reserva de demo (usado por depósitos nativo → EVM).
        self.dev_address = to_checksum_address(dev_address)
        accounts.setdefault(dev_address, EVM_GENESIS_BALANCE_ETH)
        for address, balance_eth in accounts.items():
            genesis_state[_to_canonical(address)] = {
                'balance': to_wei(balance_eth, 'ether'),
                'nonce': 0, 'code': b'', 'storage': {},
            }

        genesis_params = {
            'difficulty': 1,
            'gas_limit': EVM_GAS_LIMIT,
            'timestamp': 0,
            'coinbase': b'\x00' * 20,
            'extra_data': b'KuramaChain-EVM',
        }

        vm_config = ConsensusApplier(NoProofConsensus).amend_vm_configuration(
            ((0, LondonVM),)
        )
        chain_class = MiningChain.configure(
            __name__='KuramaEVM',
            vm_configuration=vm_config,
            chain_id=self.chain_id,
        )
        self._chain = chain_class.from_genesis(
            AtomicDB(), genesis_params, genesis_state
        )
        self._pending: List = []
        # Índice hash → (tx, bloco, posição) para eth_getTransactionByHash.
        self._tx_index: Dict[bytes, Tuple[object, int, int]] = {}
        # Relógio determinístico (None = horário de parede). Ver `advance_time`.
        self._timestamp: Optional[int] = None

    # ─── Consultas de estado ─────────────────────────────────────

    def _state(self):
        return self._chain.get_vm(self._chain.get_canonical_head()).state

    def get_balance(self, address) -> int:
        return self._state().get_balance(_to_canonical(address))

    def get_nonce(self, address) -> int:
        return self._state().get_nonce(_to_canonical(address))

    def get_code(self, address) -> bytes:
        return self._state().get_code(_to_canonical(address))

    @property
    def block_number(self) -> int:
        return self._chain.get_canonical_head().block_number

    @property
    def block_timestamp(self) -> int:
        """Timestamp do bloco EVM canônico (segundos Unix)."""
        return self._chain.get_canonical_head().timestamp

    def advance_time(self, seconds: int) -> int:
        """
        Avança o relógio da EVM em ``seconds`` sem esperar em tempo real.

        Sela um bloco (possivelmente vazio — como um minerador faria) com o
        novo timestamp, então a partir daí os blocos seguintes usam esse
        relógio (+1s por bloco) em vez do horário de parede. Isso deixa juros
        (lending), TWAP e liquidações determinísticos.

        Args:
            seconds: segundos a avançar (0 apenas fixa o relógio).

        Returns:
            O timestamp do bloco recém-selado (o novo relógio da cadeia).
        """
        with self._lock:
            base = (self._timestamp if self._timestamp is not None
                    else max(self.block_timestamp, int(time.time())))
            self._timestamp = max(base + seconds, self.block_timestamp + 1)
            self._seal_locked(force=True)
            return self.block_timestamp

    def _next_timestamp(self) -> Optional[int]:
        """Timestamp explícito do próximo bloco (None = horário de parede)."""
        if self._timestamp is None:
            return None
        return max(self._timestamp, self.block_timestamp + 1)

    # ─── Execução ────────────────────────────────────────────────

    def _build_signed(self, private_key_hex: str, to: bytes, data: bytes,
                      value: int, gas: int, gas_price: int, nonce: int):
        priv = keys.PrivateKey(
            bytes.fromhex(private_key_hex[2:] if private_key_hex.startswith('0x')
                          else private_key_hex)
        )
        unsigned = self._chain.create_unsigned_transaction(
            nonce=nonce, gas_price=gas_price, gas=gas,
            to=to, value=value, data=data,
        )
        return unsigned.as_signed_transaction(private_key=priv,
                                              chain_id=self.chain_id)

    def send_raw_transaction(self, raw_hex: str) -> str:
        """
        Aceita uma transação assinada crua (formato MetaMask/wallets) e a
        enfileira. Se ``auto_mine``, sela um bloco imediatamente.

        Aceita os dois formatos usados por wallets:
        - **legado** (EIP-155): RLP de 9 campos, como as txs que a própria
          engine assina;
        - **tipado** (EIP-2718, tipo 2/London): envelope ``0x02 || rlp``.

        Returns:
            Hash da transação (0x...).
        """
        raw = raw_hex[2:] if raw_hex.startswith('0x') else raw_hex
        tx = LondonTransactionBuilder.decode(bytes.fromhex(raw))
        with self._lock:
            self._pending.append(tx)
            if self.auto_mine:
                self._seal_locked()
        return '0x' + tx.hash.hex()

    def send(self, private_key_hex: str, to, data: bytes,
             value: int = 0, gas: int = None, gas_price: int = None) -> str:
        """
        Assina e envia uma transação para um contrato (helper de conveniência).

        Returns:
            Hash da transação (0x...).
        """
        gas = gas or EVM_DEFAULT_GAS
        gas_price = gas_price or EVM_DEFAULT_GAS_PRICE
        priv = keys.PrivateKey(
            bytes.fromhex(private_key_hex[2:] if private_key_hex.startswith('0x')
                          else private_key_hex)
        )
        sender = priv.public_key.to_canonical_address()
        with self._lock:
            nonce = self.get_nonce(sender)
            tx = self._build_signed(private_key_hex, _to_canonical(to), data,
                                    value, gas, gas_price, nonce)
            self._pending.append(tx)
            if self.auto_mine:
                self._seal_locked()
        return '0x' + tx.hash.hex()

    def deploy(self, bytecode: bytes, private_key_hex: str,
               gas: int = None, gas_price: int = None,
               value: int = 0) -> Tuple[str, str]:
        """
        Deploya um contrato a partir do bytecode compilado.

        Returns:
            (tx_hash, contract_address)
        """
        gas = gas or EVM_DEFAULT_GAS
        gas_price = gas_price or EVM_DEFAULT_GAS_PRICE
        priv = keys.PrivateKey(
            bytes.fromhex(private_key_hex[2:] if private_key_hex.startswith('0x')
                          else private_key_hex)
        )
        sender = priv.public_key.to_canonical_address()
        with self._lock:
            nonce = self.get_nonce(sender)
            tx = self._build_signed(private_key_hex, b'', bytecode, value,
                                    gas, gas_price, nonce)
            self._pending.append(tx)
            if self.auto_mine:
                self._seal_locked()
        contract_address = generate_contract_address(sender, nonce)
        return '0x' + tx.hash.hex(), to_checksum_address(contract_address)

    def call(self, to, data: bytes, value: int = 0, gas: int = None) -> bytes:
        """
        Executa uma chamada de leitura (equivalente a ``eth_call``) sem
        alterar o estado.

        Returns:
            Bytes de saída da execução.
        """
        gas = gas or EVM_DEFAULT_GAS
        with self._lock:
            tx = self._build_signed(
                '0x' + _CALL_KEY.hex(), _to_canonical(to), data, value,
                gas, EVM_DEFAULT_GAS_PRICE, 0,
            )
            return self._chain.get_transaction_result(
                tx, self._chain.get_canonical_head()
            )

    def estimate_gas(self, to, data: bytes, value: int = 0,
                     sender: Optional[str] = None,
                     gas: int = None) -> int:
        """
        Estima o gas de uma transação **com o sender real** (``eth_estimateGas``).

        A estimativa roda a mensagem num *costless state* (execução sem cobrar
        gas, descartada no fim): diferente de ``call``, o ``msg.sender`` é quem
        vai assinar, então checagens de ``allowance``/saldo valem — é o que a
        wallet precisa para um ``approve`` seguido de swap.

        Args:
            to: endereço do contrato chamado.
            data: calldata (``bytes``).
            value: valor enviado em wei.
            sender: endereço de quem envia (default: a conta descartável de
                simulação, que não tem saldo/allowance).
            gas: teto de gas da simulação (default: ``EVM_GAS_LIMIT``).

        Returns:
            Gas estimado (intrínseco + execução), suficiente para a tx passar.

        Raises:
            ValueError: se a execução reverter (a wallet mostra o motivo em vez
                de mandar uma tx fadada a falhar).
        """
        target = _to_canonical(to) if to else b''
        if not target:
            raise ValueError('eth_estimateGas: criação de contrato não suportada')
        sender_bytes = _to_canonical(sender) if sender else _CALL_SENDER
        limit = gas or EVM_GAS_LIMIT
        payload = bytes(data)
        # O computation não cobra o gas intrínseco (21k + calldata).
        intrinsic = 21_000 + sum(16 if byte else 4 for byte in payload)
        with self._lock:
            vm = self._chain.get_vm()
            with vm.in_costless_state() as state:
                context = state.get_transaction_context_class()(
                    gas_price=0, origin=sender_bytes)
                message = Message(gas=limit, to=target, sender=sender_bytes,
                                  value=value, data=payload,
                                  code=state.get_code(target))
                computation = state.computation_class.apply_computation(
                    state, message, context)
        if computation.is_error:
            raise ValueError(f'execução reverteu: {computation.error}')
        return intrinsic + computation.get_gas_used()

    # ─── Selagem de blocos (integração com o PoW) ─────────────────

    def seal_block(self) -> Optional[int]:
        """Sela um bloco EVM com as transações pendentes."""
        with self._lock:
            return self._seal_locked()

    def on_pow_block(self, kurama_block) -> None:
        """
        Callback registrado no evento ``on_block_mined`` da KuramaChain.
        Cada bloco PoW sela um bloco EVM (as duas cadeias avançam juntas).
        """
        self.seal_block()

    def _seal_locked(self, force: bool = False) -> Optional[int]:
        if not self._pending and not force:
            return None
        # Esvazia a fila ANTES de aplicar: uma tx inválida (nonce, saldo, gas)
        # faz ``apply_transaction`` levantar e não pode ficar presa na fila
        # sendo reaplicada nos blocos seguintes.
        pending, self._pending = self._pending, []
        for tx in pending:
            try:
                self._chain.apply_transaction(tx)
            except Exception as exc:
                logger.warning('[EVM] transação descartada (%s): %s',
                               tx.hash.hex(), exc)
                raise
        timestamp = self._next_timestamp()
        if timestamp is None:
            self._chain.mine_block()
        else:
            self._chain.mine_block(timestamp=timestamp)
            self._timestamp = self.block_timestamp + 1

        # Indexa as transações do bloco recém-selado (para eth_getTransactionByHash).
        block = self._chain.get_canonical_block_by_number(self.block_number)
        for index, tx in enumerate(block.transactions):
            self._tx_index[tx.hash] = (tx, block.number, index)
        return self.block_number

    # ─── Recibos / blocos ────────────────────────────────────────

    def get_transaction_receipt(self, tx_hash) -> Optional[dict]:
        h = bytes.fromhex(tx_hash[2:] if isinstance(tx_hash, str) else tx_hash.hex())
        try:
            receipt = self._chain.get_transaction_receipt(h)
            block_number, index = self._chain.get_canonical_transaction_index(h)
            block_hash = self._chain.get_canonical_block_hash(block_number)
        except Exception:
            return None
        # No fork London o recibo do py-evm guarda o **status** (não a raiz de
        # estado) no campo ``state_root``: b'\x01' = sucesso, b'' = revert.
        status = int.from_bytes(receipt.state_root, 'big') if receipt.state_root else 0
        entry = self._tx_index.get(h)
        tx = entry[0] if entry else None
        contract_address = None
        sender = None
        to = None
        if tx is not None:
            to_bytes = getattr(tx, 'to', b'') or b''
            to = '0x' + to_bytes.hex() if to_bytes else None
            try:
                sender = '0x' + tx.sender.hex()
            except Exception:
                sender = None
            if not to_bytes:
                contract_address = to_checksum_address(
                    generate_contract_address(tx.sender, tx.nonce))

        logs = []
        for log_index, log in enumerate(receipt.logs):
            # No py-evm as palavras do log podem vir como int ou bytes.
            data = log.data
            data_bytes = (bytes(data) if isinstance(data, (bytes, bytearray))
                          else (int(data).to_bytes(32, 'big') if data else b''))
            logs.append({
                'address': to_checksum_address(log.address),
                'topics': ['0x' + _word_bytes(topic).hex() for topic in log.topics],
                'data': '0x' + data_bytes.hex(),
                'blockNumber': hex(block_number),
                'blockHash': '0x' + block_hash.hex(),
                'transactionHash': '0x' + h.hex(),
                'transactionIndex': hex(index),
                'logIndex': hex(log_index),
                'removed': False,
            })
        return {
            'transactionHash': '0x' + h.hex(),
            'blockNumber': hex(block_number),
            'blockHash': '0x' + block_hash.hex(),
            'transactionIndex': hex(index),
            'from': sender,
            'to': to,
            'contractAddress': contract_address,
            'cumulativeGasUsed': hex(receipt.gas_used),
            'gasUsed': hex(receipt.gas_used),
            'effectiveGasPrice': hex(getattr(tx, 'gas_price', 0) or 0) if tx else '0x0',
            'status': hex(status),
            'logsBloom': '0x' + '00' * 256,
            'logs': logs,
        }

    # ─── Transações / blocos / logs (eth_*) ─────────────────────

    def get_transaction(self, tx_hash) -> Optional[dict]:
        """Transação por hash (formato eth_getTransactionByHash)."""
        h = bytes.fromhex(tx_hash[2:] if isinstance(tx_hash, str) else tx_hash.hex())
        entry = self._tx_index.get(h)
        if entry is None:
            return None
        tx, block_number, index = entry
        return self._tx_dict(tx, block_number, index)

    def _tx_dict(self, tx, block_number=None, index=None) -> dict:
        to_bytes = getattr(tx, 'to', b'') or b''
        try:
            sender = '0x' + tx.sender.hex()
        except Exception:
            sender = None
        gas_price = getattr(tx, 'gas_price', None)
        if gas_price is None:
            gas_price = getattr(tx, 'max_fee_per_gas', 0)
        block_hash = None
        if block_number is not None:
            block_hash = '0x' + self._chain.get_canonical_block_hash(block_number).hex()
        return {
            'hash': '0x' + tx.hash.hex(),
            'nonce': hex(tx.nonce),
            'blockHash': block_hash,
            'blockNumber': hex(block_number) if block_number is not None else None,
            'transactionIndex': hex(index) if index is not None else None,
            'from': sender,
            'to': ('0x' + to_bytes.hex()) if to_bytes else None,
            'value': hex(tx.value),
            'gas': hex(tx.gas),
            'gasPrice': hex(gas_price or 0),
            'input': '0x' + bytes(tx.data).hex(),
            'type': hex(getattr(tx, 'type', 0) or 0),
            'chainId': hex(getattr(tx, 'chain_id', self.chain_id) or self.chain_id),
        }

    def get_block(self, identifier='latest', full_transactions: bool = False) -> Optional[dict]:
        """
        Bloco por número (int, hex) ou hash (0x + 64 hex), no formato
        ``eth_getBlockByNumber``/``eth_getBlockByHash``.
        """
        try:
            block = self._resolve_block(identifier)
        except Exception:
            return None
        if block is None:
            return None

        transactions = []
        for index, tx in enumerate(block.transactions):
            if full_transactions:
                transactions.append(self._tx_dict(tx, block.number, index))
            else:
                transactions.append('0x' + tx.hash.hex())

        header = block.header
        bloom = getattr(header, 'bloom', 0)
        if isinstance(bloom, (bytes, bytearray)):
            bloom_hex = '0x' + bytes(bloom).hex()
        else:
            bloom_hex = '0x' + format(int(bloom), '0512x')
        nonce = getattr(header, 'nonce', b'')
        return {
            'number': hex(block.number),
            'hash': '0x' + block.hash.hex(),
            'parentHash': '0x' + header.parent_hash.hex(),
            'nonce': '0x' + (nonce.hex() if isinstance(nonce, (bytes, bytearray)) else format(nonce, '016x')),
            'sha3Uncles': '0x' + header.uncles_hash.hex(),
            'logsBloom': bloom_hex,
            'transactionsRoot': '0x' + header.transaction_root.hex(),
            'stateRoot': '0x' + header.state_root.hex(),
            'receiptsRoot': '0x' + header.receipt_root.hex(),
            'baseFeePerGas': hex(getattr(header, 'base_fee_per_gas', 0) or 0),
            'miner': to_checksum_address(header.coinbase),
            'difficulty': hex(header.difficulty),
            'totalDifficulty': hex(header.difficulty),
            'extraData': '0x' + header.extra_data.hex(),
            'size': hex(len(block.__class__.serialize(block))),
            'gasLimit': hex(header.gas_limit),
            'gasUsed': hex(header.gas_used),
            'timestamp': hex(header.timestamp),
            'transactions': transactions,
            'uncles': [],
        }

    def _resolve_block(self, identifier):
        head = self.block_number
        if isinstance(identifier, int):
            number = identifier
        elif isinstance(identifier, str):
            value = identifier.lower()
            if value in ('latest', 'pending', 'safe', 'finalized'):
                number = head
            elif value == 'earliest':
                number = 0
            elif value.startswith('0x') and len(value) == 66:
                return self._chain.get_block_by_hash(bytes.fromhex(value[2:]))
            elif value.startswith('0x'):
                number = int(value, 16)
            else:
                number = int(value)
        else:
            raise ValueError(f'bloco inválido: {identifier!r}')
        if number < 0 or number > head:
            return None
        return self._chain.get_canonical_block_by_number(number)

    def get_storage_at(self, address, slot) -> bytes:
        """Valor de storage (32 bytes) de um contrato — ``eth_getStorageAt``."""
        slot_int = int(slot, 16) if isinstance(slot, str) else int(slot)
        value = self._state().get_storage(_to_canonical(address), slot_int)
        return int(value).to_bytes(32, 'big')

    def get_logs(self, filter_params: Optional[dict] = None) -> List[dict]:
        """
        Logs/eventos no formato ``eth_getLogs``.

        Suporta ``fromBlock``, ``toBlock``, ``address`` (string ou lista) e
        ``topics`` (lista com None como curinga). O range é limitado a 100k
        blocos para não varrer a cadeia inteira numa requisição.
        """
        params = filter_params or {}
        head = self.block_number
        from_block = self._block_number(params.get('fromBlock'), 0, head)
        to_block = self._block_number(params.get('toBlock'), head, head)
        from_block = max(0, min(from_block, head))
        to_block = max(0, min(to_block, head))
        if to_block < from_block:
            return []
        if to_block - from_block > 100_000:
            raise ValueError('eth_getLogs: range maior que 100000 blocos')

        addresses = params.get('address')
        if isinstance(addresses, str):
            addresses = [addresses]
        address_set = {a.lower() for a in addresses} if addresses else None

        topics_filter = params.get('topics') or []
        logs: List[dict] = []
        for number in range(from_block, to_block + 1):
            block = self._chain.get_canonical_block_by_number(number)
            for tx in block.transactions:
                receipt = self.get_transaction_receipt(tx.hash)
                if not receipt:
                    continue
                for log in receipt['logs']:
                    if address_set and log['address'].lower() not in address_set:
                        continue
                    if not self._topics_match(topics_filter, log['topics']):
                        continue
                    logs.append(log)
        return logs

    @staticmethod
    def _topics_match(filters, topics) -> bool:
        for i, expected in enumerate(filters):
            if expected is None:
                continue
            if i >= len(topics):
                return False
            if isinstance(expected, str):
                expected = [expected]
            if topics[i].lower() not in {e.lower() for e in expected}:
                return False
        return True

    @staticmethod
    def _block_number(value, default: int, head: int) -> int:
        if value is None:
            return default
        if isinstance(value, int):
            return value
        value = str(value).lower()
        if value in ('latest', 'pending', 'safe', 'finalized'):
            return head
        if value == 'earliest':
            return 0
        return int(value, 16) if value.startswith('0x') else int(value)

    def get_block_transaction_count(self, identifier='latest') -> int:
        block = self._resolve_block(identifier)
        return len(block.transactions) if block else 0

    def genesis_hash(self) -> str:
        return self._chain.get_canonical_block_header_by_number(0).hash.hex()
