#!/usr/bin/env python3
"""
Mantém o minerador rodando em segundo plano (autostart do Windows).

É o que o `scripts/windows/install_miner_service.bat` coloca no autostart
do usuário. Roda sem console (pythonw), grava a saída em
`data/miner_service.log` e reinicia o minerador a cada 30s se ele sair
(nó fora do ar, por exemplo). Uma trava em `data/miner_service.lock`
impede duas instâncias minerando ao mesmo tempo.

Uso manual:

    pythonw miner_service.py

Parar: encerre o processo pythonw ou rode o uninstall (ver README).
"""
import os
import sys
import time
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

DATA_DIR = 'data'
LOG_FILE = os.path.join(DATA_DIR, 'miner_service.log')
LOCK_FILE = os.path.join(DATA_DIR, 'miner_service.lock')
PID_FILE = os.path.join(DATA_DIR, 'miner_service.pid')
RETRY_SECONDS = 30


def acquire_single_instance_lock():
    """Trava de instância única (Windows); None se já houver outra rodando."""
    os.makedirs(DATA_DIR, exist_ok=True)
    handle = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
    try:
        import msvcrt
    except ImportError:  # fora do Windows: sem trava
        return handle
    try:
        os.write(handle, b'0')
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
    except OSError:
        os.close(handle)
        return None
    return handle


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    log = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
    sys.stdout = log
    sys.stderr = log

    def now() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lock = acquire_single_instance_lock()
    if lock is None:
        print(f'[{now()}] já existe um minerador em execução; saindo')
        return 0

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    import miner

    while True:
        print(f'\n[{now()}] iniciando minerador')
        try:
            code = miner.main([])
        except KeyboardInterrupt:
            print(f'[{now()}] encerrado pelo usuário')
            return 0
        except Exception as exc:
            print(f'[{now()}] erro inesperado: {exc}')
            code = 1
        print(f'[{now()}] minerador saiu (código {code}); '
              f'nova tentativa em {RETRY_SECONDS}s')
        time.sleep(RETRY_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
