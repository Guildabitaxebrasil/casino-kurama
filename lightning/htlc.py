"""
HTLC — Hashed TimeLock Contract.
Permite pagamentos condicionais com hash lock + time lock.
"""

import time
import json
from typing import Optional
from core.crypto_utils import CryptoUtils


class HTLCStatus:
    """Estados possíveis de um HTLC."""
    PENDING = "pending"
    CLAIMED = "claimed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class HTLC:
    """
    Hashed TimeLock Contract.

    Um HTLC permite que o remetente bloqueie fundos condicionados a:
    1. O destinatário revelar o PREIMAGE (hash lock) dentro do prazo, OU
    2. O remetente recuperar os fundos após o timelock expirar

    Isso permite roteamento confiável: Alice→Bob→Carol
    Alice promete pagar Bob se ele provar que pagou Carol (revelando o segredo).
    """

    def __init__(self, channel_id: str, sender: str, receiver: str,
                 amount: float, hash_lock: str, timelock: int,
                 htlc_id: str = None, preimage: str = None,
                 status: str = None, created_at: float = None):
        self.channel_id = channel_id
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.hash_lock = hash_lock     # SHA-256(preimage)
        self.timelock = timelock       # Block height para expirar
        self.htlc_id = htlc_id or self._generate_id()
        self.preimage = preimage       # Revelado quando o HTLC é claimed
        self.status = status or HTLCStatus.PENDING
        self.created_at = created_at or time.time()

    def _generate_id(self) -> str:
        """Gera ID único para este HTLC."""
        raw = f"{self.channel_id}{self.hash_lock}{self.amount}{time.time()}"
        return CryptoUtils.sha256(raw)

    def claim(self, preimage: str) -> bool:
        """
        Tenta reivindicar o HTLC revelando o preimage.
        O preimage deve corresponder ao hash_lock (SHA-256).
        """
        if self.status != HTLCStatus.PENDING:
            return False
        if CryptoUtils.sha256(preimage) != self.hash_lock:
            return False
        self.preimage = preimage
        self.status = HTLCStatus.CLAIMED
        return True

    def refund(self) -> bool:
        """Recupera os fundos do HTLC (após timelock expirar)."""
        if self.status != HTLCStatus.PENDING:
            return False
        self.status = HTLCStatus.REFUNDED
        return True

    def is_expired(self, current_height: int) -> bool:
        """Verifica se o timelock expirou (não pode mais ser claimed)."""
        return current_height >= self.timelock

    def to_dict(self) -> dict:
        return {
            'htlc_id': self.htlc_id,
            'channel_id': self.channel_id,
            'sender': self.sender,
            'receiver': self.receiver,
            'amount': self.amount,
            'hash_lock': self.hash_lock,
            'timelock': self.timelock,
            'preimage': self.preimage,
            'status': self.status,
            'created_at': self.created_at,
        }

    @classmethod
    def create(cls, channel_id: str, sender: str, receiver: str,
               amount: float, secret: str, timelock: int) -> 'HTLC':
        """
        Cria um novo HTLC a partir de um SEGREDO (não do hash).
        Automaticamente calcula o hash_lock = SHA-256(secret).
        O secret deve ser guardado em sigilo pelo receiver.
        """
        hash_lock = CryptoUtils.sha256(secret)
        return cls(
            channel_id=channel_id,
            sender=sender,
            receiver=receiver,
            amount=amount,
            hash_lock=hash_lock,
            timelock=timelock,
        )

    def __str__(self) -> str:
        return (f"HTLC({self.htlc_id[:12]}... | "
                f"{self.amount:.2f} KUR | {self.hash_lock[:12]}... | "
                f"TL: {self.timelock} | {self.status})")
