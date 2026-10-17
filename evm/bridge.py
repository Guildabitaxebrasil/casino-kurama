"""
Atestação e relay do bridge da KuramaChain (Fase 5).

O contrato ``KurBridge`` (``evm/contracts/KurBridge.sol``) só aceita um saque
com ``threshold`` assinaturas de validadores distintos sobre o **digest
EIP-191** do depósito. Este módulo monta esse digest, assina com chaves de
validador e traz um relayer pronto que:

1. lê os eventos ``Deposit`` da chain de origem (via ``engine.get_logs``);
2. assina o comprovante com as chaves dos validadores;
3. envia ``withdraw(...)`` na chain de destino (cunha o wrapped ou libera o
   token travado).

Assim os mesmos bytes são verificados no contrato:

    digest = keccak256("\x19Ethereum Signed Message:\n32" ||
             keccak256(abi.encode(srcChain, localChainId, token, recipient,
                                  amount, nonce, depositId, bridge)))

Uso::

    from evm.bridge import BridgeRelayer

    relayer = BridgeRelayer(
        source_engine=chain_a, dest_engine=chain_b,
        source_bridge='0x...', dest_bridge='0x...',
        validator_keys=[key1, key2, key3],       # threshold = 2, por exemplo
        submitter_key=dev_key,                   # paga o gas do saque
    )
    relayer.process()                            # devolve os hashes enviados
"""
import logging
from typing import Dict, List, Optional, Sequence

from eth_keys import keys
from eth_utils import keccak, to_checksum_address

from config import EVM_DEV_PRIVATE_KEY

logger = logging.getLogger(__name__)

# ─── Assinaturas ABI ─────────────────────────────────────────────

DEPOSIT_TOPIC = keccak(
    text='Deposit(bytes32,address,address,uint256,uint256,address,uint256)'
)
WITHDRAW_SELECTOR = keccak(
    text='withdraw(uint256,address,address,uint256,uint256,bytes32,bytes[])'
)[:4]
LOCAL_CHAIN_ID_SELECTOR = keccak(text='localChainId()')[:4]

# Ordem canônica de uma assinatura secp256k1 (low-s).
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


# ─── Helpers ABI (sem eth_abi no ambiente) ───────────────────────

def _strip_hex(value: str) -> str:
    return value[2:] if value.startswith('0x') else value


def address_of(private_key: str) -> str:
    """Endereço EVM (``0x...``) derivado de uma chave privada."""
    priv = keys.PrivateKey(bytes.fromhex(_strip_hex(private_key)))
    return '0x' + priv.public_key.to_address()[2:]


def _encode_address(address: str) -> bytes:
    return bytes.fromhex(_strip_hex(address)).rjust(32, b'\x00')


def _decode_address(word: bytes) -> str:
    return to_checksum_address(bytes(word)[-20:])


def _encode_bytes_array(items: Sequence[bytes]) -> bytes:
    """ABI-encoda ``bytes[]`` (usado no parâmetro de assinaturas)."""
    head = len(items).to_bytes(32, 'big')
    offsets = []
    tail = b''
    base = 32 * len(items)
    for item in items:
        offsets.append((base + len(tail)).to_bytes(32, 'big'))
        pad = (32 - len(item) % 32) % 32
        tail += len(item).to_bytes(32, 'big') + bytes(item) + b'\x00' * pad
    return head + b''.join(offsets) + tail


def _uint_word(data: bytes, slot: int = 0) -> int:
    data = bytes(data)
    return int.from_bytes(data[slot * 32: slot * 32 + 32], 'big')


# ─── Digest / assinatura ─────────────────────────────────────────

def withdrawal_hash(local_chain_id: int, src_chain: int, token: str, recipient: str,
                    amount: int, nonce: int, deposit_id, bridge: str) -> bytes:
    """Hash da mensagem (sem prefixo EIP-191) — igual ao do contrato."""
    encoded = (int(src_chain).to_bytes(32, 'big')
               + int(local_chain_id).to_bytes(32, 'big')
               + _encode_address(token)
               + _encode_address(recipient)
               + int(amount).to_bytes(32, 'big')
               + int(nonce).to_bytes(32, 'big')
               + bytes(deposit_id).rjust(32, b'\x00')
               + _encode_address(bridge))
    return keccak(encoded)


def withdrawal_digest(local_chain_id: int, src_chain: int, token: str, recipient: str,
                      amount: int, nonce: int, deposit_id, bridge: str) -> bytes:
    """Digest EIP-191 que os validadores assinam (mesmo que o contrato usa)."""
    message = withdrawal_hash(local_chain_id, src_chain, token, recipient,
                              amount, nonce, deposit_id, bridge)
    return keccak(b'\x19Ethereum Signed Message:\n32' + message)


def sign_withdrawal(private_key: str, digest: bytes) -> bytes:
    """
    Assina o digest e devolve a assinatura de 65 bytes (r || s || v, v = 27/28).

    A assinatura é normalizada para **low-s**, como o contrato exige
    (``KurBridge: BAD_SIGNATURE`` em assinaturas maleáveis).
    """
    priv = keys.PrivateKey(bytes.fromhex(_strip_hex(private_key)))
    signature = priv.sign_msg_hash(digest)
    v, r, s = signature.v, signature.r, signature.s
    if s > _SECP256K1_N // 2:
        s = _SECP256K1_N - s
        v ^= 1
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big') + bytes([27 + v])


def encode_withdraw_calldata(src_chain: int, token: str, recipient: str,
                             amount: int, nonce: int, deposit_id,
                             signatures: Sequence[bytes]) -> bytes:
    """Calldata de ``withdraw(...)`` com o array de assinaturas."""
    return (WITHDRAW_SELECTOR
            + int(src_chain).to_bytes(32, 'big')
            + _encode_address(token)
            + _encode_address(recipient)
            + int(amount).to_bytes(32, 'big')
            + int(nonce).to_bytes(32, 'big')
            + bytes(deposit_id).rjust(32, b'\x00')
            + (7 * 32).to_bytes(32, 'big')
            + _encode_bytes_array(signatures))


# ─── Eventos ─────────────────────────────────────────────────────

def parse_deposit_log(log: dict, src_chain: int) -> Dict[str, object]:
    """
    Converte um log ``Deposit`` do ``eth_getLogs`` num dicionário do depósito.

    Args:
        log: log no formato retornado por ``EVMEngine.get_logs``.
        src_chain: chain ID da chain onde o depósito foi feito.
    """
    topics = log['topics']
    data = bytes.fromhex(_strip_hex(log['data']))
    return {
        'deposit_id': bytes.fromhex(_strip_hex(topics[1])),
        'token': _decode_address(bytes.fromhex(_strip_hex(topics[2]))),
        'sender': _decode_address(bytes.fromhex(_strip_hex(topics[3]))),
        'amount': _uint_word(data, 0),
        'dest_chain': _uint_word(data, 1),
        'recipient': _decode_address(data[64:96]),
        'nonce': _uint_word(data, 3),
        'src_chain': src_chain,
        'tx_hash': log.get('transactionHash'),
        'block_number': int(log.get('blockNumber', '0x0'), 16),
    }


# ─── Relayer ─────────────────────────────────────────────────────

class BridgeRelayer:
    """
    Relayer in-process: origem → destino, assinando com chaves de validador.

    O ``submitter_key`` paga o gas do saque (não precisa ser validador). Em
    produção este processo roda separado, um por chain, lendo eventos e
    enviando ``eth_sendRawTransaction`` (a lógica de digest/assinatura é a
    mesma).
    """

    def __init__(self, source_engine, dest_engine, source_bridge: str,
                 dest_bridge: str, validator_keys: Sequence[str],
                 submitter_key: Optional[str] = None, gas: int = 1_500_000):
        self.source = source_engine
        self.dest = dest_engine
        self.source_bridge = source_bridge
        self.dest_bridge = dest_bridge
        self.validator_keys = list(validator_keys)
        self.submitter_key = submitter_key or EVM_DEV_PRIVATE_KEY
        self.gas = gas
        self.source_chain_id = _uint_word(self.source.call(
            source_bridge, LOCAL_CHAIN_ID_SELECTOR))
        self.dest_chain_id = _uint_word(self.dest.call(
            dest_bridge, LOCAL_CHAIN_ID_SELECTOR))
        self.processed = set()

    def pending_deposits(self, from_block=0, to_block=None) -> List[Dict[str, object]]:
        """Depósitos com destino a esta chain ainda não processados."""
        logs = self.source.get_logs({
            'address': self.source_bridge,
            'fromBlock': from_block,
            'toBlock': to_block if to_block is not None else 'latest',
            'topics': ['0x' + DEPOSIT_TOPIC.hex()],
        })
        deposits = []
        for log in logs:
            deposit = parse_deposit_log(log, self.source_chain_id)
            if deposit['dest_chain'] != self.dest_chain_id:
                continue
            if deposit['deposit_id'] in self.processed:
                continue
            deposits.append(deposit)
        return deposits

    def attest(self, deposit: Dict[str, object]) -> List[bytes]:
        """Assinaturas dos validadores, ordenadas por endereço crescente."""
        digest = withdrawal_digest(
            self.dest_chain_id, deposit['src_chain'], deposit['token'],
            deposit['recipient'], deposit['amount'], deposit['nonce'],
            deposit['deposit_id'], self.dest_bridge,
        )
        signatures = []
        for key in self.validator_keys:
            signatures.append((address_of(key), sign_withdrawal(key, digest)))
        signatures.sort(key=lambda pair: pair[0].lower())
        return [sig for _, sig in signatures]

    def process(self, from_block=0, to_block=None) -> List[str]:
        """Processa todos os depósitos pendentes e devolve os hashes enviados."""
        tx_hashes = []
        for deposit in self.pending_deposits(from_block, to_block):
            tx_hashes.append(self.submit(deposit))
            self.processed.add(deposit['deposit_id'])
        return tx_hashes

    def submit(self, deposit: Dict[str, object]) -> str:
        """Assina e envia o ``withdraw`` de um depósito."""
        data = encode_withdraw_calldata(
            deposit['src_chain'], deposit['token'], deposit['recipient'],
            deposit['amount'], deposit['nonce'], deposit['deposit_id'],
            self.attest(deposit),
        )
        tx_hash = self.dest.send(self.submitter_key, self.dest_bridge, data,
                                 gas=self.gas)
        logger.info('[bridge] depósito %s liberado na chain %s (%s)',
                    bytes(deposit['deposit_id']).hex(), self.dest_chain_id, tx_hash)
        return tx_hash
