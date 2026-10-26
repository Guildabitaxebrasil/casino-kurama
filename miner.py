#!/usr/bin/env python3
"""
Minerador da KuramaChain — Proof of Work na CPU, como no Bitcoin/Monero.

O nó entrega o bloco candidato (`GET /mining/template`) e o minerador
procura o nonce aqui, na CPU, até o hash começar com o número de zeros
exigido pela dificuldade. Quando acha, entrega o bloco pronto
(`POST /mining/submit`) e recomeça no próximo bloco. O nó só valida —
quem faz o trabalho é este processo.

Não há intervalo nem "próximo bloco agendado": igual ao Bitcoin, você
mina sem parar e a dificuldade (que o nó reajusta mirando 10 minutos por
bloco) é quem controla o ritmo.

Uso:
    # Terminal 1 — o nó
    python run.py --load

    # Terminal 2 — o minerador (Ctrl+C para parar)
    python miner.py

    # A recompensa vai para um endereço específico
    python miner.py --address 15ZK...

    # Minerar N blocos e sair (teste)
    python miner.py --blocks 2

Opções:
    --url       URL do nó (padrão: detecta http/https em localhost:<port>)
    --port      porta do nó quando --url não é informado (padrão: 5000)
    --address   endereço que recebe a coinbase (padrão: endereço do nó)
    --blocks    minera N blocos e sai (padrão: 0 = infinito)
"""
import argparse
import hashlib
import json
import sys
import time

import requests
import urllib3

try:
    from config import DEFAULT_PORT
except ImportError:
    # Minerador baixado sozinho (sem o repositório): mesmo padrão de config.py.
    DEFAULT_PORT = 5000

# O nó local usa certificado auto-assinado; o minerador fala com ele em
# localhost. Para uma rede remota com CA própria, informe a URL em https.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Tempo de espera entre tentativas quando o nó cai ou está reiniciando.
RETRY_SECONDS = 15.0
# Timeout do probe de descoberta do nó.
PROBE_TIMEOUT = 3.0
REQUEST_TIMEOUT = 60.0

# Campos que entram no hash do bloco (mesma regra de Block.calculate_hash).
HASH_FIELDS = ('index', 'timestamp', 'transactions', 'proof',
               'previous_hash', 'merkle_root')

HEX_DIGITS = '0123456789abcdef'


class MinerError(RuntimeError):
    """Erro de comunicação ou de regra do nó."""

    def __init__(self, message: str, status: int = None):
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        """Falhas de rede, 429 (rate limit) e 5xx merecem nova tentativa."""
        if self.status is None:
            return True
        return self.status == 429 or self.status >= 500

    @property
    def stale(self) -> bool:
        """409 = o template ficou velho (outro bloco entrou); só pedir outro."""
        return self.status == 409


# ─── Proof of Work ────────────────────────────────────────────────

def hash_input(block: dict) -> str:
    """
    Serializa o bloco como o nó faz: JSON com chaves ordenadas e apenas
    os campos que entram no hash. É o que garante que o nonce achado
    aqui seja aceito lá.
    """
    return json.dumps({k: block[k] for k in HASH_FIELDS}, sort_keys=True)


def block_hash(block: dict) -> str:
    """Hash SHA-256 do bloco (hex), igual ao Block.calculate_hash do nó."""
    return hashlib.sha256(hash_input(block).encode('utf-8')).hexdigest()


def prepare_pow(block: dict) -> tuple:
    """
    Separa o JSON do bloco em prefixo e sufixo em volta do nonce.

    Assim o loop de mineração concatena só o número do nonce a cada
    tentativa, em vez de serializar o bloco inteiro — é o mesmo atalho
    que mineradores de verdade usam com o midstate do header.
    """
    encoded = hash_input({**block, 'proof': 0})
    marker = '"proof": 0'
    at = encoded.index(marker)
    prefix = encoded[:at + len('"proof": ')].encode('utf-8')
    suffix = encoded[at + len(marker):].encode('utf-8')
    return prefix, suffix


def difficulty_digits(difficulty: float) -> tuple:
    """
    Converte a dificuldade em (zeros, teto do dígito seguinte).

    Mesma regra do CryptoUtils.difficulty_digits do nó: o hash começa com
    `zeros` zeros hex e o dígito seguinte é <= teto (0-15). O teto permite
    dificuldade fracionária, que o nó usa para mirar 10 minutos por bloco
    (com zeros inteiros cada degrau é 16x — grosso demais).
    """
    value = max(0.0, float(difficulty))
    zeros = int(value)
    if zeros >= 64:
        return 64, 0
    frac = value - zeros
    cap = int(round(16 ** (1.0 - frac))) - 1
    return zeros, min(15, max(0, cap))


def is_valid_hash(hash_hex: str, difficulty: float) -> bool:
    """True se o hash atende à dificuldade (regra do nó)."""
    zeros, cap = difficulty_digits(difficulty)
    if len(hash_hex) <= zeros:
        return False
    # Hex minúsculo de tamanho fixo: comparar string = comparar número.
    return hash_hex[:zeros + 1] <= '0' * zeros + HEX_DIGITS[cap]


def format_hashrate(hashes_per_second: float) -> str:
    if hashes_per_second >= 1_000_000:
        return f'{hashes_per_second / 1_000_000:.2f} MH/s'
    if hashes_per_second >= 1_000:
        return f'{hashes_per_second / 1_000:.1f} kH/s'
    return f'{hashes_per_second:.0f} H/s'


def solve(block: dict, out=print, report_seconds: float = 10.0) -> int:
    """
    Procura o nonce que satisfaz a dificuldade do bloco (PoW na CPU).

    Args:
        block: Template do bloco (com index, timestamp, transactions,
               previous_hash, merkle_root e difficulty)
        out: função de saída (para testes)
        report_seconds: intervalo do relatório de hashrate

    Returns:
        O nonce encontrado
    """
    difficulty = float(block['difficulty'])
    zeros, cap = difficulty_digits(difficulty)
    prefix, suffix = prepare_pow(block)
    # Um único prefixo limite: os `zeros` zeros + o teto do próximo dígito.
    limit = '0' * zeros + HEX_DIGITS[cap]
    # Só os primeiros `zeros + 1` caracteres importam para o PoW.
    head = zeros + 1
    sha256 = hashlib.sha256

    nonce = 0
    attempts = 0
    started = time.time()
    last_report = started

    while True:
        digest = sha256(prefix + str(nonce).encode('utf-8') + suffix).hexdigest()
        attempts += 1

        if digest[:head] <= limit:
            elapsed = max(time.time() - started, 1e-9)
            out(f'[OK] Nonce encontrado em {attempts:,} tentativas '
                f'({format_hashrate(attempts / elapsed)}, {elapsed:.1f}s): '
                f'{digest[:20]}...')
            return nonce

        nonce += 1

        # Relatório periódico sem pesar no loop (a cada 65.536 hashes).
        if attempts % 65536 == 0:
            now = time.time()
            if now - last_report >= report_seconds:
                elapsed = max(now - started, 1e-9)
                out(f'[HASH] {attempts:,} tentativas | '
                    f'{format_hashrate(attempts / elapsed)} | '
                    f'dificuldade {difficulty:.2f}')
                last_report = now


# ─── Cliente do nó ────────────────────────────────────────────────

class NodeClient:
    """Cliente HTTP mínimo para o nó da KuramaChain."""

    def __init__(self, base_url: str, timeout: float = REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        if self.base_url.startswith('https://'):
            # Certificado auto-assinado do nó local (dev).
            self.session.verify = False

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f'{self.base_url}{path}'
        try:
            response = self.session.request(method, url, timeout=self.timeout,
                                            **kwargs)
        except requests.RequestException as exc:
            raise MinerError(f'falha ao falar com o nó em {url}: {exc}') from exc

        if response.status_code >= 400:
            detail = ''
            try:
                detail = response.json().get('error', '')
            except ValueError:
                detail = response.text[:200]
            raise MinerError(
                f'{method} {path} → HTTP {response.status_code}: {detail}',
                status=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise MinerError(f'resposta inválida do nó em {path}') from exc

    def block_count(self) -> int:
        """Altura atual da cadeia (nº de blocos incluindo o gênese)."""
        return int(self._request('GET', '/stats')['blocks'])

    def template(self, miner_address: str = None) -> dict:
        """Pede ao nó o bloco candidato para resolver o PoW."""
        params = {'address': miner_address} if miner_address else None
        return self._request('GET', '/mining/template', params=params)

    def submit(self, block: dict) -> dict:
        """Entrega ao nó o bloco com o nonce já resolvido."""
        return self._request('POST', '/mining/submit', json=block)


def resolve_base_url(explicit_url: str = None, port: int = DEFAULT_PORT) -> str:
    """
    Descobre a URL do nó. `--url` tem prioridade; sem ele, testa HTTP e
    HTTPS em localhost/127.0.0.1 (o run.py sobe HTTPS por padrão).
    """
    if explicit_url:
        return explicit_url.rstrip('/')

    # 127.0.0.1 antes de localhost: o servidor escuta em IPv4 e, no
    # Windows, tentar ::1 primeiro custa ~2s por requisição.
    candidates = [
        f'http://127.0.0.1:{port}',
        f'https://127.0.0.1:{port}',
        f'http://localhost:{port}',
        f'https://localhost:{port}',
    ]
    for url in candidates:
        try:
            requests.get(f'{url}/api/health', timeout=PROBE_TIMEOUT, verify=False)
            return url
        except requests.RequestException:
            continue

    raise MinerError(
        f'nenhum nó respondendo em localhost:{port}. '
        'Inicie o nó primeiro: python run.py --load'
    )


# ─── Loop de mineração ────────────────────────────────────────────

def mine_forever(client: NodeClient, address: str = None,
                 max_blocks: int = 0, out=print,
                 sleep=time.sleep) -> int:
    """
    Minera sem parar: pede o template, resolve o PoW e entrega o bloco.

    Devolve quantos blocos foram aceitos pelo nó. `max_blocks` = 0
    minera até ser interrompido.
    """
    mined = 0

    while max_blocks <= 0 or mined < max_blocks:
        try:
            template = client.template(address)
        except MinerError as exc:
            if not exc.retryable:
                raise
            out(f'[WARN] {exc}')
            out(f'[WAIT] Nova tentativa em {RETRY_SECONDS:.0f}s...')
            sleep(RETRY_SECONDS)
            continue

        pending = max(len(template.get('transactions', [])) - 1, 0)
        out(f'\n[MINE] Bloco #{template["index"]} | '
            f'dificuldade {float(template["difficulty"]):.2f} | '
            f'{pending} tx na mempool | '
            f'recompensa {float(template.get("reward", 0)):.2f} KUR')

        template['proof'] = solve(template, out=out)
        template['hash'] = block_hash(template)

        try:
            result = client.submit(template)
        except MinerError as exc:
            if exc.stale:
                # Outro bloco entrou na frente; o nó vai dar um novo template.
                out(f'[WARN] {exc}')
                continue
            if not exc.retryable:
                raise
            out(f'[WARN] {exc}')
            out(f'[WAIT] Nova tentativa em {RETRY_SECONDS:.0f}s...')
            sleep(RETRY_SECONDS)
            continue

        block = result.get('block') or {}
        mined += 1
        out(f'[OK] Bloco #{block.get("index", "?")} aceito pelo nó | '
            f'hash {str(block.get("hash", ""))[:16]}... | '
            f'recompensa {float(result.get("total_reward", 0)):.2f} KUR | '
            f'saldo {float(result.get("miner_balance", 0)):.2f} KUR')

    return mined


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Minerador da KuramaChain (Proof of Work na CPU)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python miner.py                       # minera sem parar, recompensa do nó
  python miner.py --address 15ZK...     # recompensa para sua carteira
  python miner.py --blocks 2            # minera 2 blocos e sai
        """,
    )
    parser.add_argument('--url', default=None,
                        help='URL do nó (ex.: http://localhost:5000)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'Porta do nó quando --url não é usado (default: {DEFAULT_PORT})')
    parser.add_argument('--address', default=None,
                        help='Endereço que recebe a recompensa (default: endereço do nó)')
    parser.add_argument('--blocks', type=int, default=0,
                        help='Minera N blocos e sai (default: 0 = infinito)')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.blocks < 0:
        print('[ERR] --blocks não pode ser negativo.')
        return 2

    try:
        base_url = resolve_base_url(args.url, args.port)
    except MinerError as exc:
        print(f'[ERR] {exc}')
        print('[TIP] Suba o nó em outro terminal: python run.py --load')
        return 2

    client = NodeClient(base_url)
    try:
        height = client.block_count()
        tip = client.template(args.address)
    except MinerError as exc:
        print(f'[ERR] {exc}')
        return 2

    print('\n[MINER] KuramaChain — Proof of Work na CPU')
    print(f'   Nó:         {base_url}')
    print(f'   Blocos:     {height}')
    print(f'   Dificuldade: {float(tip["difficulty"]):.2f} zeros')
    print(f'   Recompensa: {args.address or "endereço do nó"}')
    if args.blocks:
        print(f'   Limite:     {args.blocks} bloco(s)')
    print('   Ctrl+C para parar.\n')

    try:
        mined = mine_forever(client, address=args.address,
                             max_blocks=args.blocks)
    except KeyboardInterrupt:
        print('\n[STOP] Minerador encerrado pelo usuário.')
        return 0
    except MinerError as exc:
        print(f'\n[ERR] {exc}')
        return 1

    print(f'\n[DONE] {mined} bloco(s) aceito(s) pelo nó.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
