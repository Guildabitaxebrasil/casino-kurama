"""
Configurações globais da Blockchain.
Centraliza todas as constantes e parâmetros ajustáveis.
"""

# ─── Blockchain ──────────────────────────────────────────────────
DEFAULT_DIFFICULTY = 4        # Número de zeros no PoW (padrão)
MINING_REWARD = 50.0          # Recompensa por bloco minerado
COINBASE_SENDER = '0'         # Identificador do sistema (coinbase)
GENESIS_PREV_HASH = '0' * 64  # Hash do bloco anterior do gênese

# ─── Rede / API ──────────────────────────────────────────────────
DEFAULT_PORT = 5000           # Porta padrão do servidor Flask
API_HOST = '0.0.0.0'          # Host (0.0.0.0 = todas as interfaces)
NODE_TIMEOUT = 2.0            # Timeout para requisições entre nós (s)

# ─── Dados / Persistência ────────────────────────────────────────
DATA_DIR = 'data'
CHAIN_FILE = 'data/blockchain.json'
WALLET_FILE = 'data/wallet.json'

# ─── Ajuste de Dificuldade ───────────────────────────────────────
DIFFICULTY_ADJUST_INTERVAL = 10  # A cada quantos blocos ajustar
TARGET_BLOCK_TIME = 30.0       # Tempo alvo por bloco (segundos)

# ─── Transações ──────────────────────────────────────────────────
MAX_PENDING_TX = 100           # Máx. transações pendentes por bloco
MIN_TRANSACTION_AMOUNT = 0.001 # Quantidade mínima por transação

# ─── Frontend / Explorer ─────────────────────────────────────────
FRONTEND_PORT = 5173           # Porta padrão do Vite dev server
CORS_ORIGINS = [               # Origens permitidas para CORS
    'http://localhost:5173',
    'http://localhost:3000',
    'http://127.0.0.1:5173',
]

# ─── Sincronização P2P ───────────────────────────────────────────
SYNC_INTERVAL = 5.0            # Intervalo entre sincronizações (s)
NODE_HEALTH_TIMEOUT = 1.0      # Timeout para health check (s)
