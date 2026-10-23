"""
Configurações globais da Blockchain.
Centraliza todas as constantes e parâmetros ajustáveis.
Suporta .env para override via variáveis de ambiente.
"""
import os

# ─── Carrega .env se existir ─────────────────────────────────────
def _load_env():
    """
    Carrega variáveis do arquivo .env se existir.
    Usa python-dotenv se disponível, senão faz parsing manual.
    Precedência: variável de ambiente real > .env > default.
    """
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_file):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        # Parsing manual simples (sem python-dotenv)
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, val = line.partition('=')
                    key = key.strip()
                    val = val.strip()
                    if not os.environ.get(key):  # Só seta se não existir
                        os.environ[key] = val

_load_env()

def _env(key: str, default):
    """Helper: lê variável de ambiente com fallback."""
    val = os.environ.get(key)
    if val is None:
        return default
    # Tenta converter para int/float/bool conforme default
    if isinstance(default, bool):
        return val.lower() in ('1', 'true', 'yes', 'on')
    if isinstance(default, int):
        try:
            return int(val)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(val)
        except ValueError:
            return default
    return val


def _env_list(key: str, default):
    """Helper: lê uma lista separada por vírgula (ex.: chaves/validadores)."""
    val = os.environ.get(key)
    if not val:
        return default
    items = [item.strip() for item in val.split(',') if item.strip()]
    return items or default

# ─── Token ───────────────────────────────────────────────────────
TOKEN_NAME = _env('TOKEN_NAME', 'Kurama')
TOKEN_SYMBOL = _env('TOKEN_SYMBOL', 'KUR')
TOTAL_SUPPLY_CAP = _env('TOTAL_SUPPLY_CAP', 1_000_000_000.0)
INITIAL_BLOCK_REWARD = _env('INITIAL_BLOCK_REWARD', 2_500.0)
HALVING_INTERVAL = _env('HALVING_INTERVAL', 200_000)

# ─── Blockchain ──────────────────────────────────────────────────
DEFAULT_DIFFICULTY = _env('DIFFICULTY', 4)
COINBASE_SENDER = '0'
GENESIS_PREV_HASH = '0' * 64

# ─── Rede / API ──────────────────────────────────────────────────
DEFAULT_PORT = _env('PORT', 5000)
API_HOST = _env('HOST', '0.0.0.0')
NODE_TIMEOUT = _env('NODE_TIMEOUT', 2.0)

# ─── Dados / Persistência ────────────────────────────────────────
DATA_DIR = _env('DATA_DIR', 'data')
CHAIN_FILE = _env('CHAIN_FILE', 'data/blockchain.json')
WALLET_FILE = _env('WALLET_FILE', 'data/wallet.json')

# ─── Ajuste de Dificuldade ───────────────────────────────────────
# Ritmo de blocos da rede, como o alvo de 10 minutos do Bitcoin.
# O minerador automático (miner.py) usa este valor como intervalo entre
# blocos e o ajuste de dificuldade usa como alvo da janela de retarget.
DIFFICULTY_ADJUST_INTERVAL = 10  # A cada quantos blocos ajustar
TARGET_BLOCK_TIME = 600.0      # Tempo alvo por bloco (segundos) — 10 minutos

# ─── Transações ──────────────────────────────────────────────────
MAX_PENDING_TX = 100           # Máx. transações pendentes por bloco
MIN_TRANSACTION_AMOUNT = 0.001 # Quantidade mínima por transação (KUR)
MIN_TRANSACTION_FEE = 0.001    # Taxa mínima por transação (KUR) — paga ao minerador

# ─── Frontend / Explorer ─────────────────────────────────────────
FRONTEND_PORT = 5173           # Porta padrão do Vite dev server
CORS_ORIGINS = [               # Origens permitidas para CORS
    'http://localhost:5173',
    'http://localhost:3000',
    'http://127.0.0.1:5173',
    'http://localhost:5174',
    # Render - adicionar URLs após o deploy
]

# ─── SSL / HTTPS ─────────────────────────────────────────────────
SSL_CERT_DIR = 'certs'              # Diretório dos certificados SSL
SSL_CERT_FILE = 'certs/cert.pem'   # Certificado do servidor
SSL_KEY_FILE = 'certs/key.pem'     # Chave privada do certificado
CA_CERT_FILE = 'certs/ca.pem'      # CA para verificação entre nós (mTLS)
USE_HTTPS = True                    # Forçar HTTPS (desabilitar com --no-ssl)

# ─── Autenticação P2P ────────────────────────────────────────────
# Secret compartilhado entre nós para autenticação de requisições P2P.
# Em produção, gere um secret forte e distribua seguramente via vault.
# Se vazio, um UUID aleatório é gerado na inicialização.
NETWORK_SECRET = ''                  # Preencher ou deixar vazio para auto-gerar
NODE_AUTH_HEADER = 'X-Kurama-Auth'   # Header HTTP para autenticação P2P
MIN_P2P_AUTH_SECRET_LENGTH = 32      # Tamanho mínimo do secret

# ─── Segurança Criptográfica ──────────────────────────────────────
# AES-256-GCM wallet encryption
WALLET_ENCRYPTION_ITERATIONS = 100000   # PBKDF2 iterations (anti-bruteforce)
WALLET_ENCRYPTION_SALT_BYTES = 32       # Salt size for PBKDF2

# P2P HMAC authentication
P2P_HMAC_AUTH = True                     # Usar HMAC-SHA256 em vez de secret puro
P2P_ENCRYPTION = True                    # Criptografar payloads P2P com AES-256-GCM

# Consenso / Finality
REORG_LIMIT = 100                        # Profundidade máxima de reorganização (0 = ilimitado)
# Headers para assinatura criptográfica de mensagens P2P.
# Cada nó assina suas mensagens com sua chave privada ECDSA.
P2P_SIGNATURE_HEADER = 'X-Kurama-Signature'   # Assinatura Base64
P2P_PUBKEY_HEADER = 'X-Kurama-Public-Key'      # Chave pública PEM do remetente
P2P_REQUIRE_SIGNATURE = True                   # Exigir assinatura (True = produção)
P2P_RATE_LIMIT = 100                           # Máx requisições P2P por peer por janela
P2P_NONCE_TTL = 300                            # TTL do nonce anti-replay (5 min)
P2P_MAX_CLOCK_DRIFT = 30                       # Tolerância de clock drift (30s)
P2P_NONCE_CACHE_SIZE = 100000                  # Máx nonces no cache LRU
P2P_PEER_SCORE_BAN_THRESHOLD = -100            # Score mínimo antes de ban
P2P_PEER_SCORE_BAN_BASE = 3600                 # Ban inicial: 1h (exponential backoff)
P2P_PEER_SCORE_BAN_MAX = 86400                 # Ban máximo: 24h

# ─── Consenso ────────────────────────────────────────────────────
MIN_ACCEPTABLE_DIFFICULTY = 2    # Nenhum bloco externo com difficulty < 2
MAX_DIFFICULTY_JUMP = 1          # Salto máximo de difficulty entre blocos consecutivos

# ─── Tempo de Rede ───────────────────────────────────────────────
MAX_TIMESTAMP_DRIFT = 300         # 5 min tolerância para futuro
MIN_TIMESTAMP_AGE = 3600          # 1 hora máximo no passado
USE_NETWORK_TIME = False          # Usar NTP/média de peers para timestamps

# ─── Transações ──────────────────────────────────────────────────
TX_NONCE_BYTES = 16                  # Bytes de entropia no transaction_id
MAX_COINBASE_PER_BLOCK = 1           # Máx. transações coinbase por bloco

# ─── Argon2 (Key Derivation) ──────────────────────────────────────
ARGON2_TIME_COST = 3          # Número de iterações (OWASP minimum)
ARGON2_MEMORY_COST = 65536    # Memória em KB (64 MB) (OWASP minimum)
ARGON2_PARALLELISM = 4        # Threads paralelas
ARGON2_KEY_LENGTH = 32        # 32 bytes = AES-256
ARGON2_TYPE = 'Argon2id'      # Variante recomendada (resistente a side-channel + GPU)

# ─── Eclipse Attack Protection ────────────────────────────────────
ECLIPSE_MAX_PER_SUBNET = 3      # Máx peers por /24 subnet
ECLIPSE_MIN_DIVERSITY = 2       # Mínimo de /16 subnets diferentes
ECLIPSE_MAX_OUTGOING = 20       # Máx conexões ativas
ECLIPSE_SYNC_SAMPLE_SIZE = 5    # Peers consultados por sync cycle
ECLIPSE_SUSPICIOUS_SAME_CHAIN = 3   # Alerta se N peers consecutivos dão mesma chain

# ─── Seed Nodes ───────────────────────────────────────────────────
# Nós de bootstrap confiáveis para descoberta inicial da rede.
# Usados quando o nó não tem peers conhecidos ou após restart.
# Em ambiente local de teste, usar localhost com portas conhecidas.
SEED_NODES = [
    # Produção: adicionar URLs reais dos seed nodes
    # "https://seed1.kurama.network:5000",
    # "https://seed2.kurama.network:5000",
]
SEED_NODES_TIMEOUT = 2.0       # Timeout para requisições a seed nodes

# ─── Lightning Network ───────────────────────────────────────────
# Canais de pagamento off-chain (LN)
LN_DEFAULT_TIMELOCK = 144          # ~1 hora em blocos (assumindo 30s/bloco)
LN_MAX_HOPS = 10                   # Máximo de hops em um pagamento multi-hop
LN_DISPUTE_WINDOW = 60             # Janela de disputa em blocos (~30 min)
LN_MIN_CHANNEL_AMOUNT = 1.0        # Valor mínimo para abrir canal (KUR)
LN_MAX_CHANNEL_AMOUNT = 100000.0   # Valor máximo para abrir canal (KUR)
LN_FUNDING_PREFIX = 'ln_funding:' # Prefixo para tx de funding
LN_SETTLEMENT_PREFIX = 'ln_settlement:' # Prefixo para tx de settlement

# ─── Sincronização P2P ───────────────────────────────────────────
SYNC_INTERVAL = 5.0            # Intervalo entre sincronizações (s)
NODE_HEALTH_TIMEOUT = 1.0      # Timeout para health check (s)

# ─── EVM (Contratos Inteligentes / DeFi) ─────────────────────────
# Camada de execução EVM integrada à blockchain (ver evm/engine.py).
# Fork London = último fork com Proof of Work.
EVM_CHAIN_ID = _env('EVM_CHAIN_ID', 9090)
EVM_GAS_LIMIT = _env('EVM_GAS_LIMIT', 30_000_000)          # gas por bloco
EVM_DEFAULT_GAS = _env('EVM_DEFAULT_GAS', 3_000_000)       # gas por transação
EVM_DEFAULT_GAS_PRICE = _env('EVM_DEFAULT_GAS_PRICE', 10**9)  # 1 gwei
EVM_GENESIS_BALANCE_ETH = _env('EVM_GENESIS_BALANCE_ETH', 10_000.0)
# Chave privada de desenvolvimento (APENAS demo/testes). Em produção, use
# um cofre/KMS e NUNCA comite a chave real.
EVM_DEV_PRIVATE_KEY = _env('EVM_DEV_PRIVATE_KEY', '0x' + '11' * 32)
# Contas financiadas no gênese: {endereço_0x: saldo_em_ETH}. A conta de dev
# (EVM_DEV_PRIVATE_KEY) é adicionada automaticamente pela engine.
EVM_GENESIS_ACCOUNTS = {}
# Se True, cada transação EVM sela um bloco na hora (modo dev, estilo Ganache).
# Se False, as transações EVM só são seladas quando a KuramaChain minera um
# bloco PoW (integração via evento on_block_mined).
EVM_AUTO_MINE = _env('EVM_AUTO_MINE', True)

# ─── Oráculo (Fase 3) ────────────────────────────────────────────
# Nó oráculo: publica preços off-chain no feed on-chain (ver evm/oracle_node.py).
# Chave privada de um reporter (APENAS demo/testes — use KMS/cofre em produção).
EVM_ORACLE_PRIVATE_KEY = _env('EVM_ORACLE_PRIVATE_KEY', '0x' + '33' * 32)
# Nº mínimo de reporters que precisam concordar para fechar uma rodada.
EVM_ORACLE_QUORUM = _env('EVM_ORACLE_QUORUM', 1)
# Idade máxima (s) do preço do feed antes do consumidor cair no fallback TWAP.
EVM_ORACLE_MAX_AGE = _env('EVM_ORACLE_MAX_AGE', 3600)
# Janela mínima (s) entre duas atualizações da TWAP da DEX.
EVM_ORACLE_PERIOD = _env('EVM_ORACLE_PERIOD', 300)
# Intervalo (s) entre publicações do nó oráculo.
EVM_ORACLE_INTERVAL = _env('EVM_ORACLE_INTERVAL', 60)
# Desvio máximo (%) aceito em relação ao último preço on-chain (proteção
# contra "fat finger"). Desative com None/0.
EVM_ORACLE_MAX_DEVIATION_PCT = _env('EVM_ORACLE_MAX_DEVIATION_PCT', 20)

# ─── Lending (Fase 4) ────────────────────────────────────────────
# Mercado de empréstimos (ver evm/contracts/KurLendingPool.sol e evm/deploy.py).
# LTV inicial de uma reserva (bps): quanto do colateral pode ser emprestado.
EVM_LENDING_LTV_BPS = _env('EVM_LENDING_LTV_BPS', 7500)
# Limiar de liquidação (bps): acima da dívida/colateral a posição é liquidável.
EVM_LENDING_LIQ_THRESHOLD_BPS = _env('EVM_LENDING_LIQ_THRESHOLD_BPS', 8000)
# Bônus do liquidante (bps; 10500 = 5% sobre a dívida coberta).
EVM_LENDING_LIQ_BONUS_BPS = _env('EVM_LENDING_LIQ_BONUS_BPS', 10500)
# Fração máxima da dívida liquidável numa chamada (bps).
EVM_LENDING_CLOSE_FACTOR_BPS = _env('EVM_LENDING_CLOSE_FACTOR_BPS', 5000)
# Parte dos juros que fica com o protocolo (bps).
EVM_LENDING_RESERVE_FACTOR_BPS = _env('EVM_LENDING_RESERVE_FACTOR_BPS', 1000)
# Modelo de juros (APR em %): base + inclinação 1/2 conforme a utilização.
EVM_LENDING_BASE_RATE_APR = _env('EVM_LENDING_BASE_RATE_APR', 0.0)
EVM_LENDING_SLOPE1_APR = _env('EVM_LENDING_SLOPE1_APR', 4.0)
EVM_LENDING_SLOPE2_APR = _env('EVM_LENDING_SLOPE2_APR', 75.0)
# Utilização ótima (%): até aqui vale a inclinação 1, acima a inclinação 2.
EVM_LENDING_OPTIMAL_UTILIZATION_PCT = _env('EVM_LENDING_OPTIMAL_UTILIZATION_PCT', 80.0)
# Idade máxima (s) do preço usado pelo pool (0 = sem checagem).
EVM_LENDING_PRICE_MAX_AGE = _env('EVM_LENDING_PRICE_MAX_AGE', 3600)
# Chave usada para implantar/configurar o mercado (APENAS demo/testes).
EVM_LENDING_PRIVATE_KEY = _env('EVM_LENDING_PRIVATE_KEY', '0x' + '44' * 32)

# ─── Staking (Fase 5) ────────────────────────────────────────────
# Pools de staking/farming (ver evm/contracts/KurStaking.sol e evm/deploy.py).
# Chave que implanta/configura os pools (APENAS demo/testes).
EVM_STAKING_PRIVATE_KEY = _env('EVM_STAKING_PRIVATE_KEY', '0x' + '55' * 32)

# ─── Bridge / Interoperabilidade (Fase 5) ────────────────────────
# Bridge lock/mint com validadores m-de-n (ver evm/contracts/KurBridge.sol).
# Chave que implanta/configura o bridge (APENAS demo/testes).
EVM_BRIDGE_PRIVATE_KEY = _env('EVM_BRIDGE_PRIVATE_KEY', '0x' + '66' * 32)
# Chaves dos validadores que atestam depósitos (separadas por vírgula).
# APENAS demo/testes — em produção use chaves em KMS/HSM.
EVM_BRIDGE_VALIDATOR_KEYS = _env_list('EVM_BRIDGE_VALIDATOR_KEYS', [
    '0x' + '77' * 32, '0x' + '88' * 32, '0x' + '99' * 32,
])
# Nº mínimo de assinaturas de validadores distintos para liberar um saque.
EVM_BRIDGE_THRESHOLD = _env('EVM_BRIDGE_THRESHOLD', 2)

# ─── JSON-RPC (dApps / MetaMask) ─────────────────────────────────
# Origem permitida no CORS do endpoint POST /rpc ('*' em dev).
EVM_RPC_CORS_ORIGIN = _env('EVM_RPC_CORS_ORIGIN', '*')
