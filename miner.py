#!/usr/bin/env python3
"""
Minerador automático da KuramaChain — um bloco a cada 10 minutos.

O minerador não guarda uma cópia da cadeia: ele conversa com o nó que já
está rodando (`python run.py` ou `python start_dev.py`) pelo endpoint
`POST /mine`, que faz o Proof of Work e paga a recompensa. Assim a cadeia,
a mempool, a EVM e o explorer continuam com uma única fonte de verdade.

O ritmo é por "slot", como o alvo de 10 minutos do Bitcoin: o próximo
bloco só é minerado quando `timestamp_do_último_bloco + intervalo` chega.
Se o nó estiver atrasado (PoW demorou, nó reiniciou), o bloco sai na hora
e a contagem seguinte parte do bloco novo.

Uso:
    # Terminal 1 — o nó
    python run.py --load

    # Terminal 2 — o minerador (600s = 10 min por bloco)
    python miner.py

    # A recompensa vai para um endereço específico
    python miner.py --address 15ZK...

    # Outro ritmo, ou um teste rápido
    python miner.py --interval 30
    python miner.py --blocks 2 --interval 5

Opções:
    --url       URL do nó (padrão: detecta http/https em localhost:<port>)
    --port      porta do nó quando --url não é informado (padrão: 5000)
    --address   endereço que recebe a coinbase (padrão: endereço do nó)
    --interval  segundos entre blocos (padrão: config.TARGET_BLOCK_TIME = 600)
    --blocks    minera N blocos e sai (padrão: 0 = infinito)
"""
import argparse
import sys
import time

import requests
import urllib3

from config import DEFAULT_PORT, TARGET_BLOCK_TIME

# O nó local usa certificado auto-assinado; o minerador fala com ele em
# localhost. Para uma rede remota com CA própria, informe a URL em https.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Tempo de espera entre tentativas quando o nó cai ou está reiniciando.
RETRY_SECONDS = 15.0
# Timeout de leitura/probe do nó (o /mine pode demorar se a dificuldade subir).
PROBE_TIMEOUT = 3.0
REQUEST_TIMEOUT = 300.0


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

    def last_block(self) -> dict:
        """Último bloco da cadeia (vazio se a cadeia não existir)."""
        count = self.block_count()
        if count <= 0:
            return {}
        return self._request('GET', f'/api/blocks/{count - 1}')

    def mine(self, miner_address: str = None) -> dict:
        """Executa `POST /mine` e devolve a resposta do nó."""
        payload = {'miner_address': miner_address} if miner_address else {}
        return self._request('POST', '/mine', json=payload)


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


def seconds_until_next_slot(last_timestamp: float, interval: float,
                            now: float = None) -> float:
    """
    Segundos até o próximo bloco. Retorna 0 se o slot já passou.

    É o equivalente ao alvo de 10 minutos do Bitcoin: cada bloco abre um
    slot de `interval` segundos a partir do timestamp do bloco anterior.
    """
    if last_timestamp is None:
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, float(last_timestamp) + float(interval) - float(now))


def _clock(timestamp: float) -> str:
    return time.strftime('%H:%M:%S', time.localtime(timestamp))


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def mine_forever(client: NodeClient, address: str = None,
                 interval: float = TARGET_BLOCK_TIME, max_blocks: int = 0,
                 sleep=time.sleep, out=print) -> int:
    """
    Loop de mineração. Minera até `max_blocks` blocos (0 = infinito) e
    devolve quantos blocos foram minerados.

    Reconsulta o último bloco a cada volta para respeitar blocos que
    chegaram de fora (UI, P2P) e para se realinhar após uma queda do nó.
    """
    mined = 0
    last_timestamp = None

    while max_blocks <= 0 or mined < max_blocks:
        # Alinha com o último bloco conhecido pelo nó.
        try:
            latest = client.last_block()
            last_timestamp = latest.get('timestamp', last_timestamp)
        except MinerError as exc:
            if not exc.retryable:
                raise
            out(f'[WARN] {exc}')

        wait = seconds_until_next_slot(last_timestamp, interval)
        if wait > 0:
            out(f'[WAIT] Próximo bloco em {_duration(wait)} '
                f'(às {_clock(time.time() + wait)})')
            sleep(wait)

        try:
            result = client.mine(address)
        except MinerError as exc:
            if not exc.retryable:
                raise
            out(f'[WARN] {exc}')
            out(f'[WAIT] Nova tentativa em {int(RETRY_SECONDS)}s...')
            sleep(RETRY_SECONDS)
            continue

        block = result.get('block') or {}
        last_timestamp = block.get('timestamp', time.time())
        mined += 1

        out(f'[OK] Bloco #{block.get("index", "?")} minerado | '
            f'hash {str(block.get("hash", ""))[:16]}... | '
            f'recompensa {float(result.get("total_reward", 0)):.2f} KUR | '
            f'saldo {float(result.get("miner_balance", 0)):.2f} KUR | '
            f'dificuldade {result.get("difficulty", "?")}')

    return mined


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Minerador automático da KuramaChain (1 bloco a cada 10 min)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python miner.py                          # 10 min por bloco, recompensa do nó
  python miner.py --address 15ZK...        # recompensa para sua carteira
  python miner.py --interval 30            # 30 s por bloco
  python miner.py --blocks 2 --interval 5  # teste rápido: 2 blocos
        """,
    )
    parser.add_argument('--url', default=None,
                        help='URL do nó (ex.: http://localhost:5000)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'Porta do nó quando --url não é usado (default: {DEFAULT_PORT})')
    parser.add_argument('--address', default=None,
                        help='Endereço que recebe a recompensa (default: endereço do nó)')
    parser.add_argument('--interval', type=float, default=TARGET_BLOCK_TIME,
                        help=f'Segundos entre blocos (default: {TARGET_BLOCK_TIME:.0f})')
    parser.add_argument('--blocks', type=int, default=0,
                        help='Minera N blocos e sai (default: 0 = infinito)')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.interval <= 0:
        print('[ERR] --interval deve ser maior que zero.')
        return 2
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
    except MinerError as exc:
        print(f'[ERR] {exc}')
        return 2

    pace = (f'{args.interval / 60:.1f} min'.replace('.0 min', ' min')
            if args.interval >= 60 else f'{args.interval:.0f}s')
    print(f'\n[MINER] KuramaChain — um bloco a cada {pace}')
    print(f'   Nó:        {base_url}')
    print(f'   Blocos:    {height}')
    print(f'   Intervalo: {args.interval:.0f}s')
    print(f'   Recompensa: {args.address or "endereço do nó"}')
    if args.blocks:
        print(f'   Limite:    {args.blocks} bloco(s)')
    print('   Ctrl+C para parar.\n')

    try:
        mined = mine_forever(client, address=args.address,
                             interval=args.interval, max_blocks=args.blocks)
    except KeyboardInterrupt:
        print('\n[STOP] Minerador encerrado pelo usuário.')
        return 0
    except MinerError as exc:
        print(f'\n[ERR] {exc}')
        return 1

    print(f'\n[DONE] {mined} bloco(s) minerado(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
