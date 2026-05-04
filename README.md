# ⛓️ KURAMACHIAN — Blockchain Explorer & Simulador de Rede P2P

**KURAMACHIAN** é uma implementação completa de blockchain com Proof of Work, assinaturas digitais ECDSA, árvore de Merkle, mecanismo de consenso, simulação de rede multi-nó e um **Blockchain Explorer** visual moderno.

Inspirado em sistemas reais como Bitcoin e Ethereum, com foco educacional e arquitetura profissional.

---

## 📦 Estrutura do Projeto

```
kuramachian/
├── backend/                     # Python Flask API
│   ├── core/
│   │   ├── crypto_utils.py     # SHA-256, ECDSA, Base58, Merkle, RIPEMD-160
│   │   ├── block.py            # Bloco com hash e Proof of Work
│   │   ├── transaction.py      # Transação com assinatura digital
│   │   ├── wallet.py           # Geração de carteiras (chave → endereço)
│   │   └── blockchain.py       # Blockchain: mineração, validação, persistência, eventos
│   ├── api/
│   │   └── routes.py           # API REST (25+ endpoints)
│   ├── node/
│   │   └── node_manager.py     # Simulação de rede multi-nó
│   ├── config.py               # Configurações
│   ├── run.py                  # Ponto de entrada
│   └── requirements.txt
├── frontend/                    # React + Vite + TailwindCSS
│   └── src/
│       ├── api/                # API client (Axios + TypeScript)
│       ├── components/         # Componentes reutilizáveis
│       ├── pages/              # 6 páginas do Explorer
│       └── hooks/              # Hooks customizados
├── tests/                      # 40+ testes com pytest
├── data/                       # Persistência em JSON
└── README.md
```

---

## 🚀 Como Executar

### 1. Backend (API)

```bash
# Instalar dependências
pip install -r requirements.txt

# Iniciar servidor (porta 5000)
python run.py --port 5000 --difficulty 4

# Rede multi-nó (3 nós simultâneos)
python run.py --network --nodes 3

# Demonstração automatizada completa
python run.py --demo
```

### 2. Frontend (Blockchain Explorer)

```bash
cd frontend
npm install
npm run dev
```

Acesse **http://localhost:5173** — o frontend faz proxy automático para o backend em `:5000`.

---

## 🌐 Blockchain Explorer — Páginas

| Página | Rota | Descrição |
|--------|------|-----------|
| **Dashboard** | `/` | Visão geral: blocos, transações, nós, gráfico de crescimento |
| **Explorer** | `/blocks` | Lista paginada de blocos em cards |
| **Block Details** | `/block/:id` | Hash, merkle, nonce, transações do bloco |
| **Transactions** | `/transactions` | Tabela de transações com filtros |
| **Network** | `/network` | Grafo interativo da rede P2P (D3.js) |
| **Wallet** | `/wallet` | Consulta de saldo e histórico |

### Destaques Visuais

- **ChainGrowthChart** — Gráfico de crescimento da blockchain (Recharts)
- **NetworkGraph** — Grafo force-directed dos nós P2P (D3.js)
- **BlockChainVis** — Visualização horizontal de blocos encadeados
- **MempoolWidget** — Painel da mempool em tempo real
- **Dark Theme** — Interface escura estilo Etherscan/GitHub Dark
- **Search** — Busca global por blocos, transações e endereços

---

## 🔬 Como a Blockchain Funciona

### 1. Blocos (Block)

Cada bloco contém índice, timestamp, transações, nonce (PoW), hash anterior, raiz de Merkle, hash próprio e dificuldade.

### 2. Proof of Work (Mineração)

O minerador busca um **nonce** tal que `SHA-256(bloco + nonce)` comece com N zeros:

- Dificuldade 4 ≈ 65.536 tentativas em média
- Dificuldade 5 ≈ 1.048.576 tentativas
- Ajuste dinâmico a cada 10 blocos

### 3. Assinaturas Digitais (ECDSA)

Usamos **ECDSA com curva secp256k1** (a mesma do Bitcoin):

- Chave privada → assina transações
- Chave pública → verifica assinaturas
- Transações falsas são rejeitadas na validação

### 4. Endereços (Base58Check)

```
SHA-256(chave pública) → RIPEMD-160(digest) → prefixo 0x00 + checksum → Base58
```

### 5. Consenso

A cadeia válida **mais longa** é a correta. Nós substituem sua cadeia local ao receber uma cadeia mais longa e válida.

### 6. Sistema de Eventos

A blockchain emite eventos (`on_block_mined`, `on_transaction_added`, `on_chain_replaced`, `on_transaction_expired`) que podem ser usados para notificações em tempo real.

---

## 🧪 Testes

```bash
python -m pytest tests/ -v
```

40+ testes cobrindo:

- **CryptoUtils**: SHA-256, ECDSA, assinaturas, Merkle, validação de hash
- **Transaction**: criação, assinatura, serialização, validação
- **Wallet**: geração, endereços, serialização, transações
- **Block**: criação, hash, serialização, efeito avalanche
- **Blockchain**: gênese, mineração, validação, saldos, persistência, consenso, adulteração
- **Integração**: cenário completo (carteiras → transações → mineração → saldos → validação)
- **Eventos**: callbacks, mempool, expiração, duplicatas

---

## 📡 API REST (25+ endpoints)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/chain` | Blockchain completa |
| GET | `/mine` | Minerar novo bloco |
| POST | `/transactions/new` | Criar transação |
| GET | `/transactions/pending` | Transações pendentes |
| GET | `/wallet/new` | Gerar carteira |
| GET | `/balance/<address>` | Saldo |
| POST | `/nodes/register` | Registrar nó vizinho |
| GET | `/nodes/resolve` | Consenso |
| GET | `/validate` | Validar cadeia |
| GET | `/stats` | Estatísticas |
| GET | `/api/health` | Health check |
| GET | `/api/chain/since/<index>` | Blocos desde índice |
| GET | `/api/blocks/<id>` | Bloco por index ou hash |
| GET | `/api/transactions` | Transações com paginação/filtros |
| GET | `/api/search?q=<term>` | Busca unificada |
| GET | `/api/nodes` | Lista de nós |
| POST | `/api/nodes/sync` | Sincronizar nós |
| GET | `/api/chart` | Dados para gráfico |
| GET | `/api/mempool` | Estatísticas da mempool |
| POST | `/blocks/new` | Receber bloco de outro nó |

---

## ⚠️ Limitações do Modelo

1. **Account-based** (como Ethereum) em vez de UTXO (como Bitcoin)
2. **Sem taxas de transação** — todas as transações têm a mesma prioridade
3. **Consenso simplificado** — apenas cadeia mais longa, sem validação completa de bloco
4. **Rede simulada via HTTP** — não é P2P real (sem Kademlia/gossip)
5. **Mineração sequencial** — sem paralelismo
6. **Sem contratos inteligentes** — apenas transferências de valor

---

## 🚀 Como Evoluir para Produção

### Layer 2 — Lightning Network
- Canais de pagamento bidirecionais off-chain
- Transações instantâneas com taxas mínimas
- Settlement on-chain apenas na abertura/fechamento

### Smart Contracts
- Implementar máquina de estado estilo Ethereum
- Linguagem de script (simplificada) para lógica de contratos
- Taxas de computação (gas) para prevenir loops infinitos

### Scaling
- **Sharding**: dividir o estado da blockchain em partições
- **Sidechains**: cadeias paralelas com pontes de comunicação
- **Rollups**: execução off-chain com proof on-chain (ZK / Optimistic)

### Rede P2P Real
- Descoberta de nós via DHT (Kademlia)
- Propagação de blocos via gossip protocol (libp2p)
- Conexões peer-to-peer diretas (WebSockets / TCP)

---

## 📄 Licença

Projeto educacional para demonstração dos conceitos fundamentais de blockchain.

---

> **KURAMACHIAN** — Construído com Python, Flask, React, TypeScript, TailwindCSS, Recharts e D3.js
