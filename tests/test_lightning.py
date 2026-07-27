"""
Testes para a Lightning Network.
Cobre: canais, HTLCs, channel manager, router, lightning network,
e CASCADE MULTI-HOP completo.
"""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from lightning.channel import PaymentChannel, ChannelState, CommitmentTransaction
from lightning.htlc import HTLC, HTLCStatus
from lightning.channel_manager import ChannelManager
from lightning.router import PaymentRouter
from lightning.lightning_network import LightningNetwork
from core.crypto_utils import CryptoUtils


class TestPaymentChannel:
    """Testes do canal de pagamento."""

    def setup_method(self):
        self.party_a = "addr_a_" + CryptoUtils.generate_nonce()[:8]
        self.party_b = "addr_b_" + CryptoUtils.generate_nonce()[:8]

    def test_create_channel(self):
        """Criação básica de canal."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        assert channel.party_a == self.party_a
        assert channel.party_b == self.party_b
        assert channel.balance_a == 100.0
        assert channel.balance_b == 50.0
        assert channel.total_balance == 150.0
        assert channel.status == ChannelState.PENDING
        assert channel.sequence == 0

    def test_create_commitment(self):
        """Criação de commitment transaction."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        channel.status = ChannelState.OPEN

        comm = channel.create_commitment(80.0, 70.0)
        assert comm.sequence == 1
        assert comm.balance_a == 80.0
        assert comm.balance_b == 70.0
        assert channel.sequence == 1
        assert channel.balance_a == 80.0
        assert channel.balance_b == 70.0

    def test_commitment_invalid_total(self):
        """Commitment com saldo total inconsistente deve falhar."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        channel.status = ChannelState.OPEN
        with pytest.raises(ValueError, match="Saldo total inconsistente"):
            channel.create_commitment(200.0, 50.0)

    def test_multiple_commitments_increment_sequence(self):
        """Múltiplos commitments incrementam sequence."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        channel.status = ChannelState.OPEN

        c1 = channel.create_commitment(90.0, 60.0)
        assert c1.sequence == 1

        c2 = channel.create_commitment(80.0, 70.0)
        assert c2.sequence == 2

        c3 = channel.create_commitment(70.0, 80.0)
        assert c3.sequence == 3

        assert channel.latest_commitment.hash == c3.hash

    def test_commitment_hash_changes_with_balance(self):
        """Cada commitment tem hash único."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        channel.status = ChannelState.OPEN

        c1 = channel.create_commitment(90.0, 60.0)
        c2 = channel.create_commitment(80.0, 70.0)
        assert c1.hash != c2.hash

    def test_can_close_requires_signed_commitments(self):
        """Canal só pode fechar com commitments assinados."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        assert not channel.can_close()  # PENDING status

        channel.status = ChannelState.OPEN
        assert not channel.can_close()  # Sem commitments

        channel.create_commitment(90.0, 60.0)
        assert not channel.can_close()  # Sem assinaturas

    def test_settle_and_close(self):
        """Ciclo de fechamento do canal."""
        channel = PaymentChannel(self.party_a, self.party_b, 100.0, 50.0)
        channel.settle("tx_settlement_1", coop=True)
        assert channel.status == ChannelState.CLOSING_COOP
        assert channel.closing_tx_id == "tx_settlement_1"

        channel.close()
        assert channel.status == ChannelState.CLOSED

    def test_to_dict_roundtrip(self):
        """Serialização e desserialização."""
        channel = PaymentChannel(
            self.party_a, self.party_b, 100.0, 50.0,
            channel_id="test_id", funding_tx_id="funding_1"
        )
        channel.status = ChannelState.OPEN
        channel.create_commitment(80.0, 70.0)

        data = channel.to_dict()
        restored = PaymentChannel.from_dict(data)

        assert restored.channel_id == channel.channel_id
        assert restored.party_a == channel.party_a
        assert restored.party_b == channel.party_b
        assert restored.balance_a == channel.balance_a
        assert restored.balance_b == channel.balance_b
        assert restored.status == channel.status


class TestHTLC:
    """Testes dos Hashed TimeLock Contracts."""

    def test_create_htlc(self):
        """Criação básica de HTLC."""
        htlc = HTLC.create(
            channel_id="chan_1",
            sender="alice",
            receiver="bob",
            amount=10.0,
            secret="segredo_super_secreto",
            timelock=100,
        )
        assert htlc.sender == "alice"
        assert htlc.receiver == "bob"
        assert htlc.amount == 10.0
        assert htlc.status == HTLCStatus.PENDING
        assert len(htlc.hash_lock) == 64  # SHA-256 hex

    def test_hash_lock_matches_secret(self):
        """hash_lock deve ser SHA-256 do secret."""
        secret = "segredo_123"
        expected_hash = CryptoUtils.sha256(secret)

        htlc = HTLC.create("c1", "alice", "bob", 5.0, secret, 50)
        assert htlc.hash_lock == expected_hash

    def test_claim_with_correct_preimage(self):
        """Claim com preimage correto deve funcionar."""
        secret = "segredo_correto"
        htlc = HTLC.create("c1", "alice", "bob", 5.0, secret, 50)

        assert htlc.status == HTLCStatus.PENDING
        assert htlc.claim(secret) == True
        assert htlc.status == HTLCStatus.CLAIMED
        assert htlc.preimage == secret

    def test_claim_with_wrong_preimage(self):
        """Claim com preimage errado deve falhar."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)

        assert htlc.claim("preimage_errado") == False
        assert htlc.status == HTLCStatus.PENDING  # Status inalterado

    def test_claim_twice_fails(self):
        """Claim duplicado deve falhar."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)
        assert htlc.claim("segredo") == True
        assert htlc.claim("segredo") == False  # Já foi claimed

    def test_refund(self):
        """Refund (após timelock) deve funcionar."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)
        assert htlc.refund() == True
        assert htlc.status == HTLCStatus.REFUNDED

    def test_refund_after_claim_fails(self):
        """Refund após claim deve falhar."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)
        htlc.claim("segredo")
        assert htlc.refund() == False

    def test_is_expired(self):
        """Verificação de expiração por timelock."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)
        assert htlc.is_expired(30) == False  # Ainda não expirou
        assert htlc.is_expired(50) == True   # Expirado (block height >= timelock)
        assert htlc.is_expired(100) == True  # Muito expirado

    def test_to_dict(self):
        """Serialização do HTLC."""
        htlc = HTLC.create("c1", "alice", "bob", 5.0, "segredo", 50)
        data = htlc.to_dict()
        assert data['htlc_id'] == htlc.htlc_id
        assert data['amount'] == 5.0
        assert data['hash_lock'] == htlc.hash_lock


class TestChannelManager:
    """Testes do gerenciador de canais."""

    def setup_method(self):
        self.manager = ChannelManager()
        self.a = "alice_" + CryptoUtils.generate_nonce()[:6]
        self.b = "bob_" + CryptoUtils.generate_nonce()[:6]

    def test_create_channel(self):
        """Criação de canal via manager."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        assert channel.channel_id in self.manager.channels
        assert channel.status == ChannelState.OPEN
        assert channel.sequence == 1  # Commitment genèse criado

    def test_create_channel_same_party_fails(self):
        """Canal com mesma parte deve falhar."""
        with pytest.raises(ValueError, match="consigo mesmo"):
            self.manager.create_channel("addr1", "addr1", 100.0, 50.0)

    def test_update_balance(self):
        """Atualização de saldo no canal."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)

        self.manager.update_balance(channel.channel_id, 80.0, 70.0)
        assert channel.balance_a == 80.0
        assert channel.balance_b == 70.0
        assert channel.sequence == 2

    def test_update_balance_closed_channel_fails(self):
        """Atualizar canal fechado deve falhar."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        channel.status = ChannelState.CLOSED

        with pytest.raises(ValueError):
            self.manager.update_balance(channel.channel_id, 80.0, 70.0)

    def test_add_and_claim_htlc(self):
        """Adicionar HTLC e reivindicar com preimage.

        Fluxo realístico:
        1. add_htlc: HTLC pendente, saldos inalterados
        2. update_balance: cria commitment com HTLC, sender perde saldo disponível
        3. claim_htlc: receiver ganha, sender NÃO perde de novo (correção cascade)
        """
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        secret = "meu_segredo_123"

        htlc = HTLC.create(
            channel_id=channel.channel_id,
            sender=self.a,
            receiver=self.b,
            amount=10.0,
            secret=secret,
            timelock=1000,
        )
        self.manager.add_htlc(channel.channel_id, htlc)
        assert len(self.manager.get_channel_htlcs(channel.channel_id)) == 1

        # Cria commitment com o HTLC travado (simula fluxo real)
        pending = self.manager.get_channel_htlcs(channel.channel_id)
        self.manager.update_balance(channel.channel_id, 90.0, 50.0)
        assert channel.balance_a == 90.0  # -10 travado no HTLC
        assert channel.balance_b == 50.0  # inalterado

        # Claim: sender NÃO perde de novo (correção cascade!)
        assert self.manager.claim_htlc(channel.channel_id, htlc.htlc_id, secret)
        assert channel.balance_a == 90.0   # NÃO reduz de novo! (antes era 90, bug virava 80)
        assert channel.balance_b == 60.0   # +10 (correto!)

    def test_add_htlc_insufficient_balance(self):
        """HTLC com saldo insuficiente deve falhar."""
        channel = self.manager.create_channel(self.a, self.b, 10.0, 50.0)

        htlc = HTLC.create(
            channel_id=channel.channel_id,
            sender=self.a,
            receiver=self.b,
            amount=100.0,  # > balance_a (10)
            secret="secret",
            timelock=1000,
        )
        with pytest.raises(ValueError, match="Saldo insuficiente"):
            self.manager.add_htlc(channel.channel_id, htlc)

    def test_close_channel_coop(self):
        """Fechamento cooperativo."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        # Adiciona assinaturas para poder fechar
        channel.latest_commitment.signature_a = "sig_a"
        channel.latest_commitment.signature_b = "sig_b"

        self.manager.close_channel_coop(channel.channel_id, "settlement_1")
        assert channel.status == ChannelState.CLOSING_COOP
        assert channel.closing_tx_id == "settlement_1"

    def test_force_close(self):
        """Force close."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        self.manager.close_channel_force(channel.channel_id, "force_settle_1")
        assert channel.status == ChannelState.CLOSING_FORCE

    def test_dispute_with_newer_commitment(self):
        """Disputa com commitment mais recente (sequence > channel.sequence)."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        # channel.sequence = 1 após create_channel

        # Cria um commitment com sequence=3 (maior que o channel.sequence atual=1)
        # DISPUTA deve aceitar pois 3 > 1
        newer_commitment = CommitmentTransaction(
            channel_id=channel.channel_id,
            sequence=3,  # Maior que channel.sequence (1)
            balance_a=30.0,
            balance_b=120.0,
        )

        assert self.manager.dispute_channel(channel.channel_id, newer_commitment)
        assert channel.balance_a == 30.0
        assert channel.balance_b == 120.0
        assert channel.sequence == 3

    def test_dispute_with_older_commitment_ignored(self):
        """Disputa com commitment mais antigo (sequence <= channel.sequence) é ignorada."""
        channel = self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        # channel.sequence = 1

        # Cria um commitment com sequence=1 (igual ao atual)
        # DISPUTA deve rejeitar pois 1 não é > 1
        same_commitment = CommitmentTransaction(
            channel_id=channel.channel_id,
            sequence=1,
            balance_a=999.0,  # Valor fraudulento
            balance_b=50.0,
        )

        assert not self.manager.dispute_channel(channel.channel_id, same_commitment)
        assert channel.balance_a == 100.0  # Valores originais preservados
        assert channel.balance_b == 50.0

    def test_list_channels(self):
        """Listagem de canais."""
        self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        c2 = self.manager.create_channel(
            "carol_" + CryptoUtils.generate_nonce()[:6],
            "dave_" + CryptoUtils.generate_nonce()[:6],
            200.0, 100.0
        )
        assert len(self.manager.list_channels()) == 2

    def test_get_channels_for_address(self):
        """Canais por endereço."""
        self.manager.create_channel(self.a, self.b, 100.0, 50.0)
        channels = self.manager.get_channels_for_address(self.a)
        assert len(channels) == 1
        assert channels[0].party_b == self.b


class TestPaymentRouter:
    """Testes do roteador de pagamentos."""

    def setup_method(self):
        self.manager = ChannelManager()
        self.router = PaymentRouter(self.manager)

        # Cria uma rede de canais:
        # Alice(100) --50--> Bob(50) --30--> Carol(70)
        # Alice(100) --20--> Dave(80)
        self.alice = "alice_router"
        self.bob = "bob_router"
        self.carol = "carol_router"
        self.dave = "dave_router"

        ch1 = self.manager.create_channel(self.alice, self.bob, 50.0, 50.0)
        ch2 = self.manager.create_channel(self.bob, self.carol, 30.0, 70.0)
        ch3 = self.manager.create_channel(self.alice, self.dave, 20.0, 80.0)

    def test_find_path_direct(self):
        """Caminho direto entre dois nós."""
        path = self.router.find_path(self.alice, self.bob, 10.0)
        assert len(path) == 1  # Apenas 1 hop: Alice -> Bob

    def test_find_path_multi_hop(self):
        """Caminho multi-hop: Alice -> Bob -> Carol."""
        path = self.router.find_path(self.alice, self.carol, 10.0)
        assert len(path) >= 2  # Alice -> Bob -> Carol
        # Verifica que o caminho termina em Carol
        assert path[-1][2] == self.carol  # (from, channel_id, to)

    def test_find_path_insufficient_capacity(self):
        """Caminho com capacidade insuficiente."""
        # Tenta enviar 100 coins pela conexão Alice->Dave (só 20 disponível)
        path = self.router.find_path(self.alice, self.dave, 100.0)
        assert len(path) == 0  # Sem caminho viável

    def test_find_path_max_hops(self):
        """Respeita limite de hops."""
        path = self.router.find_path(self.alice, self.carol, 5.0, max_hops=1)
        assert len(path) == 0  # 1 hop não é suficiente (precisa de 2)

    def test_get_network_graph(self):
        """Grafo da rede."""
        graph = self.router.get_network_graph()
        assert graph['node_count'] >= 4
        assert graph['channel_count'] >= 3

    def test_no_path_to_unknown(self):
        """Endereço desconhecido não tem caminho."""
        path = self.router.find_path(self.alice, "unknown_addr", 10.0)
        assert len(path) == 0


class TestLightningNetwork:
    """Testes integrados da Lightning Network."""

    def setup_method(self):
        self.ln = LightningNetwork()
        self.a = "alice_ln_" + CryptoUtils.generate_nonce()[:6]
        self.b = "bob_ln_" + CryptoUtils.generate_nonce()[:6]
        self.c = "carol_ln_" + CryptoUtils.generate_nonce()[:6]

    def test_open_channel(self):
        """Abertura de canal via LN."""
        result = self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        assert result['channel_id'] is not None
        assert result['balance_a'] == 100.0
        assert result['balance_b'] == 50.0
        assert result['total_balance'] == 150.0

    def test_open_duplicate_channel_fails(self):
        """Canal duplicado deve falhar."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        with pytest.raises(ValueError, match="Canal já existe"):
            self.ln.open_channel(self.a, self.b, 50.0, 25.0)

    def test_update_channel_balance(self):
        """Atualização de saldo no canal."""
        result = self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        cid = result['channel_id']

        updated = self.ln.update_channel_balance(cid, 80.0, 70.0)
        assert updated['sequence'] == 2
        assert updated['balance_a'] == 80.0
        assert updated['balance_b'] == 70.0

    def test_close_channel_coop(self):
        """Fechamento cooperativo de canal."""
        # Passa assinaturas dummy para que can_close() retorne True
        result = self.ln.open_channel(self.a, self.b, 100.0, 50.0,
                                       sign_a='sig_a', sign_b='sig_b')
        cid = result['channel_id']

        close_result = self.ln.close_channel(cid, cooperative=True)
        assert close_result['success']
        assert close_result['cooperative']

    def test_send_payment_no_path(self):
        """Pagamento sem caminho disponível."""
        # Apenas Alice e Bob têm canal, Carol não
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        result = self.ln.send_payment(self.a, self.c, 10.0)
        assert not result['success']
        assert 'Caminho não encontrado' in result['error']

    def test_send_payment_direct(self):
        """Pagamento direto (1 hop)."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        result = self.ln.send_payment(self.a, self.b, 10.0)
        assert result['success'], f"Pagamento falhou: {result.get('error', '')}"
        assert result['amount'] == 10.0
        assert result['hops'] == 1

    def test_get_channel(self):
        """Consulta de canal."""
        result = self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        channel = self.ln.get_channel(result['channel_id'])
        assert channel is not None
        assert channel['party_a'] == self.a
        assert channel['party_b'] == self.b

    def test_list_channels(self):
        """Listagem de canais."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        self.ln.open_channel(
            "carol_list_" + CryptoUtils.generate_nonce()[:6],
            "dave_list_" + CryptoUtils.generate_nonce()[:6],
            50.0, 50.0,
        )
        channels = self.ln.list_channels()
        assert len(channels) == 2

    def test_get_channels_for_address(self):
        """Canais por endereço."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        channels = self.ln.get_channels_for(self.a)
        assert len(channels) == 1

    def test_network_stats(self):
        """Estatísticas da rede."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        stats = self.ln.get_network_stats()
        assert stats['total_channels'] >= 1
        assert stats['total_volume'] >= 150.0

    def test_lightning_balance(self):
        """Saldo lightning."""
        self.ln.open_channel(self.a, self.b, 100.0, 50.0)
        balance = self.ln.get_lightning_balance(self.a)
        assert balance['locked_in_channels'] >= 100.0


class TestMultiHopCascade:
    """
    Testes do CASCADE MULTI-HOP completo.

    Cenário: Alice →(1) Bob →(2) Carol →(3) Dave
    Alice paga 5 KUR para Dave via Bob e Carol.

    Cada hop intermediário deve:
    1. Receber o preimage do próximo hop (que reivindicou)
    2. Usar o preimage para reivindicar do hop anterior
    3. Terminar com saldo neutro (não perde nem ganha)
    """

    def setup_method(self):
        self.ln = LightningNetwork()
        self.alice = "alice_cascade_" + CryptoUtils.generate_nonce()[:6]
        self.bob = "bob_cascade_" + CryptoUtils.generate_nonce()[:6]
        self.carol = "carol_cascade_" + CryptoUtils.generate_nonce()[:6]
        self.dave = "dave_cascade_" + CryptoUtils.generate_nonce()[:6]

        # Rede: Alice(50)-Bob(50), Bob(30)-Carol(70), Carol(40)-Dave(60)
        self.ch_ab = self.ln.open_channel(self.alice, self.bob, 50.0, 50.0)
        self.ch_bc = self.ln.open_channel(self.bob, self.carol, 30.0, 70.0)
        self.ch_cd = self.ln.open_channel(self.carol, self.dave, 40.0, 60.0)

    def test_three_hop_cascade(self):
        """Cascade 3 hops: Alice→Bob→Carol→Dave."""
        amount = 5.0
        result = self.ln.send_payment(self.alice, self.dave, amount)
        assert result['success'], f"Falhou: {result.get('error', '')}"
        assert result['hops'] == 3

        # Verifica saldos finais nos canais
        ab = self.ln.get_channel(self.ch_ab['channel_id'])
        bc = self.ln.get_channel(self.ch_bc['channel_id'])
        cd = self.ln.get_channel(self.ch_cd['channel_id'])

        # Alice: 50 → 45 (-5)
        assert ab['balance_a'] == 45.0, f"Alice deveria ter 45, tem {ab['balance_a']}"

        # Bob: 50 + 30 = 80 (inalterado, intermediário neutro)
        bob_total = ab['balance_b'] + bc['balance_a']
        assert abs(bob_total - 80.0) < 0.001, f"Bob deveria ter 80, tem {bob_total}"

        # Carol: 70 + 40 = 110 (inalterado, intermediária neutra)
        carol_total = bc['balance_b'] + cd['balance_a']
        assert abs(carol_total - 110.0) < 0.001, f"Carol deveria ter 110, tem {carol_total}"

        # Dave: 60 → 65 (+5)
        assert cd['balance_b'] == 65.0, f"Dave deveria ter 65, tem {cd['balance_b']}"

    def test_two_hop_cascade(self):
        """Cascade 2 hops: Alice→Bob→Carol."""
        amount = 8.0
        result = self.ln.send_payment(self.alice, self.carol, amount)
        assert result['success'], f"Falhou: {result.get('error', '')}"
        assert result['hops'] == 2

        ab = self.ln.get_channel(self.ch_ab['channel_id'])
        bc = self.ln.get_channel(self.ch_bc['channel_id'])

        # Alice: 50 → 42 (-8)
        assert ab['balance_a'] == 42.0, f"Alice deveria ter 42, tem {ab['balance_a']}"

        # Bob: 50 + 30 = 80 (neutro)
        bob_total = ab['balance_b'] + bc['balance_a']
        assert abs(bob_total - 80.0) < 0.001, f"Bob deveria ter 80, tem {bob_total}"

        # Carol: 70 → 78 (+8)
        assert bc['balance_b'] == 78.0, f"Carol deveria ter 78, tem {bc['balance_b']}"

    def test_cascade_does_not_double_charge(self):
        """Verifica que o cascade NÃO dobra a cobrança (bug anterior)."""
        # Salva saldos iniciais
        ab_before = self.ln.get_channel(self.ch_ab['channel_id'])
        bc_before = self.ln.get_channel(self.ch_bc['channel_id'])
        cd_before = self.ln.get_channel(self.ch_cd['channel_id'])

        initial_alice = ab_before['balance_a']
        initial_bob_total = ab_before['balance_b'] + bc_before['balance_a']
        initial_carol_total = bc_before['balance_b'] + cd_before['balance_a']
        initial_dave = cd_before['balance_b']

        amount = 3.0
        self.ln.send_payment(self.alice, self.dave, amount)

        ab_after = self.ln.get_channel(self.ch_ab['channel_id'])
        bc_after = self.ln.get_channel(self.ch_bc['channel_id'])
        cd_after = self.ln.get_channel(self.ch_cd['channel_id'])

        # Alice perdeu exatamente {amount}
        assert abs(ab_after['balance_a'] - (initial_alice - amount)) < 0.001

        # Bob inalterado (neutro)
        bob_after_total = ab_after['balance_b'] + bc_after['balance_a']
        assert abs(bob_after_total - initial_bob_total) < 0.001

        # Carol inalterada (neutra)
        carol_after_total = bc_after['balance_b'] + cd_after['balance_a']
        assert abs(carol_after_total - initial_carol_total) < 0.001

        # Dave ganhou exatamente {amount}
        assert abs(cd_after['balance_b'] - (initial_dave + amount)) < 0.001

        # O total do sistema permanece o mesmo
        total_before = (initial_alice + initial_bob_total +
                        initial_carol_total + initial_dave)
        total_after = (ab_after['balance_a'] + bob_after_total +
                       carol_after_total + cd_after['balance_b'])
        assert abs(total_before - total_after) < 0.001

    def test_cascade_three_hop_multiple_payments(self):
        """Múltiplos pagamentos via cascade 3 hops."""
        # Alice envia 5 para Dave
        r1 = self.ln.send_payment(self.alice, self.dave, 5.0)
        assert r1['success']

        # Carol envia 3 para Alice
        r2 = self.ln.send_payment(self.carol, self.alice, 3.0)
        assert r2['success']

        # Dave envia 2 para Bob
        r3 = self.ln.send_payment(self.dave, self.bob, 2.0)
        assert r3['success']

        # Verifica estado final
        ab = self.ln.get_channel(self.ch_ab['channel_id'])
        bc = self.ln.get_channel(self.ch_bc['channel_id'])
        cd = self.ln.get_channel(self.ch_cd['channel_id'])

        # Alice: 50 - 5 (para Dave) + 3 (de Carol) = 48
        assert abs(ab['balance_a'] - 48.0) < 0.001, \
            f"Alice deveria 48, tem {ab['balance_a']}"

        # Dave: 60 + 5 (de Alice) - 2 (para Bob) = 63
        assert abs(cd['balance_b'] - 63.0) < 0.001, \
            f"Dave deveria 63, tem {cd['balance_b']}"

    def test_cascade_no_double_deduction_claim_direct(self):
        """Teste direto de que claim_htlc não deduz do sender duas vezes."""
        manager = ChannelManager()
        alice = "alice_claim_" + CryptoUtils.generate_nonce()[:6]
        bob = "bob_claim_" + CryptoUtils.generate_nonce()[:6]

        channel = manager.create_channel(alice, bob, 100.0, 50.0)
        secret = "segredo_cascade_test"

        # Cria HTLC e atualiza balance (lock de 10)
        htlc = HTLC.create(
            channel_id=channel.channel_id,
            sender=alice, receiver=bob,
            amount=10.0, secret=secret, timelock=1000,
        )
        manager.add_htlc(channel.channel_id, htlc)
        manager.update_balance(channel.channel_id, 90.0, 50.0)

        # Antes do claim: Alice=90, Bob=50
        assert channel.balance_a == 90.0
        assert channel.balance_b == 50.0

        # Claim: Alice NÃO perde de novo
        ok = manager.claim_htlc(channel.channel_id, htlc.htlc_id, secret)
        assert ok

        # Alice ainda tem 90 (NÃO 80 — que seria o bug de dupla contagem)
        assert channel.balance_a == 90.0, \
            f"Alice deveria 90 (não deduzir de novo), mas tem {channel.balance_a}"
        # Bob tem 60 (recebeu os 10)
        assert channel.balance_b == 60.0, \
            f"Bob deveria 60, mas tem {channel.balance_b}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
