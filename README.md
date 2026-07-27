<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Flask-2.0-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/Tailwind_CSS-3-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white" alt="Tailwind CSS">
  <img src="https://img.shields.io/badge/Polygon-8247E5?style=for-the-badge&logo=polygon&logoColor=white" alt="Polygon">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License">
</p>

<h1 align="center">⛓️ KuramaChain</h1>
<p align="center"><strong>Blockchain + Casino Descentralizado + Lightning Network</strong></p>
<p align="center">Uma implementação completa de blockchain com Proof of Work, carteiras ECDSA,<br>explorador visual, cassino integrado com USDT na Polygon e rede Lightning.</p>

<br>

<p align="center">
  <a href="#-visão-geral">Visão Geral</a> •
  <a href="#-arquitetura">Arquitetura</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-blockchain">Blockchain</a> •
  <a href="#-casino">Cassino</a> •
  <a href="#%EF%B8%8F-lightning-network">Lightning</a> •
  <a href="#-api-endpoints">API</a> •
  <a href="#-segurança">Segurança</a>
</p>

---

## 🎯 Visão Geral

O **KuramaChain** é um ecossistema blockchain completo que combina três grandes módulos:

| Módulo | Descrição | Stack |
|--------|-----------|-------|
| ⛓️ **Blockchain Core** | Blockchain PoW com ECDSA, Merkle Tree, consenso, carteiras e explorer visual | Python, Flask, React |
| 🎰 **Kurama Casino** | Cassino descentralizado com depósitos em USDT (Polygon) | Python, React, Web3 |
| ⚡ **Lightning Network** | Canais de pagamento off-chain para transações instantâneas | Python, Flask |

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                      KURAMACHAIN                            │
├─────────────────┬───────────────────┬──────────────────────┤
│   Blockchain    │     Casino        │   Lightning Network  │
│   Core          │                   │                      │
├─────────────────┼───────────────────┼──────────────────────┤
│ • Proof of Work │ • Roleta          │ • Canais bidirecionais│
│ • ECDSA/Wallets │ • Blackjack       │ • HTLCs              │
│ • Merkle Tree   │ • Slots           │ • Multi-hop routing  │
│ • Consenso P2P  │ • Dados           │ • Disputas on-chain  │
│ • Mempool/SSE   │ • USDT/Polygon    │ • Fee management     │
└─────────────────┴───────────────────┴──────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
    ┌────┴────┐         ┌────┴────┐          ┌────┴────┐
    │  Flask  │         │  React  │          │  React  │
    │  (API)  │         │(Frontend)│          │(Frontend)│
    └─────────┘         └─────────┘          └─────────┘
```

---

## 🚀 Quick Start

### Backend (Servidor Principal)

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Iniciar servidor com blockchain + cassino + lightning
python run.py --port 5000

# 3. Rede multi-nó (3 nós simultâneos)
python run.py --network --nodes 3

# 4. Demonstração automatizada
python run.py --demo
```

### Frontend (Blockchain Explorer)

```bash
cd frontend
npm install
npm run dev
# Acesse http://localhost:5173
```

### Frontend (Cassino)

```bash
cd casino/frontend
npm install
npm run dev
# Acesse http://localhost:5173/casino
```

---

## ⛓️ Blockchain

### 🔬 Como Funciona

**1. Proof of Work (Mineração)**
O minerador busca um **nonce** tal que `SHA-256(bloco + nonce)` comece com N zeros:
- Dificuldade 4 ≈ 65.536 tentativas em média
- Dificuldade 5 ≈ 1.048.576 tentativas
- Ajuste dinâmico a cada 10 blocos

**2. Assinaturas Digitais (ECDSA)**
Usamos **ECDSA com curva secp256k1** (a mesma do Bitcoin):
- Chave privada → assina transações
- Chave pública → verifica assinaturas
- Transações falsas são rejeitadas na validação

**3. Endereços (Base58Check)**
```
SHA-256(chave pública) → RIPEMD-160(digest) → prefixo 0x00 + checksum → Base58
```

**4. Árvore de Merkle**
Cada bloco contém uma raiz de Merkle que resume todas as transações, permitindo verificação eficiente de inclusão sem baixar o bloco inteiro.

**5. Consenso**
A cadeia válida **mais longa** é a correta. Nós substituem sua cadeia local ao receber uma cadeia mais longa e válida.

### 📊 Blockchain Explorer

O frontend em React oferece 6 páginas para explorar a blockchain:

| Página | Rota | Descrição |
|--------|------|-----------|
| **Dashboard** | `/` | Visão geral com gráficos e estatísticas |
| **Explorer** | `/blocks` | Blocos em cards com paginação |
| **Detalhes** | `/block/:id` | Hash, merkle, nonce, transações |
| **Transações** | `/transactions` | Tabela com filtros e busca |
| **Rede** | `/network` | Grafo interativo P2P (D3.js) |
| **Carteira** | `/wallet` | Saldo e histórico de endereço |

**Destaques visuais:**
- 📈 **ChainGrowthChart** — Gráfico de crescimento da blockchain (Recharts)
- 🔗 **NetworkGraph** — Grafo force-directed da rede P2P (D3.js)
- 🧱 **BlockChainVis** — Visualização horizontal de blocos encadeados
- 📋 **MempoolWidget** — Painel da mempool em tempo real
- 🌙 **Dark Theme** — Interface escura estilo Etherscan/GitHub Dark

---

## 🎰 Cassino

### Jogos Disponíveis

| Jogo | Descrição | Payout Máximo |
|------|-----------|---------------|
| 🎡 **Roleta Europeia** | Aposte em números (até 35x), cores (2x), dúzias (3x) | 35:1 |
| 🃏 **Blackjack 21** | Vença o dealer chegando perto de 21 sem estourar | 3:2 |
| 🎰 **Caça-níqueis** | Slots com tema crypto (BTC, ETH, USDT, SOL) | 100x |
| 🎲 **Dados** | Over/Under 7, Dupla, Par/Ímpar, Soma exata | 30x |

### 💰 Depósitos e Saques

O cassino aceita **apenas USDT (ERC-20)** na rede Polygon:

```
Depósito: 1 USDT → 1 Ficha do Cassino  (mín. 5 USDT)
  Saque:  1 Ficha → 1 USDT
```

### 🔒 Provably Fair

Todo resultado de jogo é verificável:
1. Server seed é gerado e seu **hash** é mostrado **antes** da rodada
2. Após a rodada, o server seed é revelado
3. Use `HMAC-SHA256(server_seed, client_seed:nonce)` para verificar

### 🏆 Sistema de Progressão

- **Bônus Diário** — 5 fichas grátis todo dia
- **Cashback Semanal** — 10% das perdas de volta
- **Conquistas** — 18 achievements para desbloquear
- **Leaderboard** — Ranking global de jogadores

### 🔐 Segurança do Cassino

- **2FA (TOTP)** para saques acima do limite
- **AES-256-GCM** para chaves privadas em repouso
- **Hot/Warm/Cold Wallets** com sweeps automáticos
- **Audit Trail** imutável com hash chain (SHA3-256)
- **Rate Limiting** multi-camada (IP + wallet)
- **Monitoramento on-chain** da Polygon

---

## ⚡ Lightning Network

Implementação de **Lightning Network** para pagamentos off-chain:

- **HTLCs** (Hashed Time-Locked Contracts) — contratos condicionais com timeout
- **Canais Bidirecionais** — múltiplos pagamentos sem abrir nova tx on-chain
- **Roteamento Multi-hop** — pagamentos através de múltiplos nós intermediários
- **Disputas On-Chain** — resolução de conflitos via blockchain
- **Fee Management** — taxas ajustáveis por canal

```python
# Exemplo: abrir canal e pagar
POST /api/lightning/channel/open    # Abrir canal
POST /api/lightning/invoice         # Criar invoice
POST /api/lightning/pay             # Pagar invoice via rede
```

---

## 📡 API Endpoints

### Blockchain Core

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/chain` | Blockchain completa |
| `POST` | `/mine` | Minerar novo bloco |
| `POST` | `/transactions/new` | Criar transação |
| `GET` | `/transactions/pending` | Transações pendentes |
| `POST` | `/wallet/new` | Gerar carteira |
| `GET` | `/balance/<address>` | Saldo |
| `POST` | `/nodes/register` | Registrar nó vizinho |
| `GET` | `/nodes/resolve` | Executar consenso |
| `GET` | `/validate` | Validar cadeia |
| `GET` | `/stats` | Estatísticas |
| `GET` | `/api/events` | Eventos em tempo real (SSE) |
| `GET` | `/api/docs` | Documentação Swagger |

### Cassino

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/casino/balance/<player>` | Saldo do jogador |
| `POST` | `/api/casino/deposit` | Depositar USDT |
| `POST` | `/api/casino/withdraw` | Sacar para USDT |
| `POST` | `/api/casino/roulette/play` | Jogar roleta |
| `POST` | `/api/casino/blackjack/start` | Iniciar blackjack |
| `POST` | `/api/casino/slots/play` | Jogar slots |
| `POST` | `/api/casino/dice/play` | Jogar dados |
| `GET` | `/api/casino/leaderboard` | Ranking |
| `GET` | `/api/casino/bonuses` | Bônus disponíveis |
| `GET` | `/api/casino/achievements` | Conquistas |

### Lightning Network

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/lightning/channel/open` | Abrir canal |
| `POST` | `/api/lightning/channel/close` | Fechar canal |
| `GET` | `/api/lightning/channels` | Listar canais |
| `POST` | `/api/lightning/invoice` | Criar invoice |
| `POST` | `/api/lightning/pay` | Pagar invoice |
| `GET` | `/api/lightning/network/graph` | Grafo da rede LN |

---

## 🛡️ Segurança

### Criptografia

| Algoritmo | Uso |
|-----------|-----|
| **SHA-256** | Hashing de blocos, Merkle tree |
| **ECDSA (secp256k1)** | Assinatura de transações |
| **RIPEMD-160** | Geração de endereços |
| **Base58Check** | Codificação de endereços |
| **AES-256-GCM** | Criptografia de chaves privadas |
| **PBKDF2-HMAC-SHA256** | Derivação de chave (100k iterações) |
| **HMAC-SHA256** | Autenticação P2P entre nós |

### Proteções de Rede

- **Rate Limiting** multi-camada (IP + wallet + adaptativo)
- **Anti-DNS Rebinding** — verificação de IP por requisição
- **Anti-Replay** — nonce + timestamp em mensagens P2P
- **Peer Scoring** — banimento progressivo de peers maliciosos
- **Content-Security-Policy** — headers restritivos no frontend

### Produção

- **PostgreSQL** para persistência de saldos
- **AES-256-GCM** para chaves privadas em repouso
- **Hot/Warm/Cold Wallets** com hierarquia de segurança
- **2FA (TOTP)** para saques
- **Audit Trail** imutável com hash chain
- **Sweeps Automáticos** entre wallets
- **Monitoramento on-chain** da Polygon

---

## 📁 Estrutura do Projeto

```
kuramachain/
├── api/                           # API REST (Flask)
│   ├── routes.py                  # Endpoints principais
│   ├── polygon_routes.py          # Endpoints Polygon
│   └── __init__.py
├── core/                          # Blockchain Core
│   ├── blockchain.py              # Blockchain, consenso, eventos
│   ├── block.py                   # Bloco com PoW
│   ├── transaction.py             # Transações e assinaturas
│   ├── wallet.py                  # Carteiras ECDSA
│   ├── crypto_utils.py            # SHA-256, ECDSA, Base58, Merkle
│   ├── identity.py                # Identidade persistente de nós
│   └── p2p_security.py            # Segurança P2P (nonce, scoring)
├── casino/
│   ├── backend/                   # Backend do cassino
│   │   ├── routes.py              # API do cassino
│   │   ├── deposit_manager.py     # Depósitos/saques USDT
│   │   ├── game_manager.py        # Gerenciamento de jogos
│   │   ├── roulette.py            # Roleta Europeia
│   │   ├── blackjack.py           # Blackjack 21
│   │   ├── slots.py               # Caça-níqueis
│   │   ├── dice.py                # Dados
│   │   ├── baccarat.py            # Baccarat
│   │   └── infrastructure/        # Produção (Polygon, 2FA, wallets)
│   └── frontend/                  # Frontend do cassino (React)
├── lightning/                     # Lightning Network
│   ├── lightning_network.py       # Rede LN
│   ├── channel.py                 # Canais de pagamento
│   ├── channel_manager.py         # Gerenciamento de canais
│   ├── htlc.py                    # HTLCs
│   ├── router.py                  # Roteamento multi-hop
│   └── api.py                     # API LN
├── node/                          # Gerenciamento de nós
│   └── node_manager.py            # Rede multi-nó
├── frontend/                      # Blockchain Explorer (React)
├── tests/                         # 40+ testes
├── config.py                      # Configurações centralizadas
├── run.py                         # Ponto de entrada
└── requirements.txt               # Dependências Python
```

---

## 🧪 Testes

```bash
# Todos os testes
python -m pytest tests/ -v

# Testes específicos
python -m pytest tests/test_blockchain.py -v    # Blockchain
python -m pytest tests/test_casino.py -v        # Cassino
python -m pytest tests/test_lightning.py -v     # Lightning Network
python -m pytest tests/test_api.py -v           # API
python -m pytest tests/test_repository.py -v    # Persistência
```

---

## 🛠️ Tecnologias

### Backend
| Tecnologia | Versão | Uso |
|------------|--------|-----|
| Python | 3.10+ | Linguagem principal |
| Flask | 2.x | API REST |
| SQLAlchemy | 2.x | ORM (PostgreSQL) |
| Web3.py | 6.x | Integração Polygon |
| Pytest | 7.x | Testes |

### Frontend
| Tecnologia | Versão | Uso |
|------------|--------|-----|
| React | 18 | UI |
| TypeScript | 5 | Tipagem |
| Vite | 5 | Build |
| TailwindCSS | 3 | Estilização |
| Recharts | 2 | Gráficos |
| D3.js | 7 | Network graph |
| Axios | 1 | HTTP client |
| Lucide React | - | Ícones |

---

## 📄 Licença

Todos os direitos reservados. KuramaChain é uma plataforma de cassino descentralizado com blockchain própria, desenvolvida para operação real com criptomoedas.

---

<p align="center">
  <strong>KuramaChain</strong> — Python · Flask · React · TypeScript · TailwindCSS · Polygon · Lightning Network
</p>
<p align="center">
  <sub>💰 Jogue com responsabilidade</sub>
</p>
