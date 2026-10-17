# KuramaChain — Arquitetura DeFi (EVM)

> Documento de arquitetura para transformar a KuramaChain numa rede
> **EVM-compatível com DeFi**: smart contracts (Solidity), DEX, pools de
> liquidez, oráculos, lending e interoperabilidade com outras redes.

---

## 1. Como a KuramaChain funciona hoje (diagnóstico)

| Camada | Implementação atual | Arquivo |
|--------|---------------------|---------|
| Execução | **Código próprio em Python**. Transação = objeto assinado (ECDSA secp256k1/DER) | `core/transaction.py`, `core/crypto_utils.py` |
| Endereços | **Base58Check** (estilo Bitcoin) + utilitário para derivar `0x...` (keccak) | `core/crypto_utils.py`, `core/wallet.py` |
| Consenso | **Proof of Work** (`SHA-256(bloco+nonce)`), dificuldade a cada 10 blocos, alvo 30s, maior cadeia válida | `core/blockchain.py`, `core/block.py` |
| Estado | Só saldos por endereço + coinbase automática (anti-inflação) | `core/blockchain.py` |
| Mempool / eventos | Fila de pendentes + SSE | `api/routes.py` |
| Persistência | JSON em disco (`data/blockchain.json`) | `config.py` |
| API | Flask REST (`/chain`, `/mine`, `/transactions/new`, ...) | `api/routes.py` |
| Lightning | Módulo separado (HTLC/canais) | `lightning/` |
| Frontend | Explorer React | `frontend/` |

**Conclusão:** a cadeia é uma **blockchain "de pagamentos"** (estilo Bitcoin
primitivo). Ela **não tem máquina de estado de contratos**, logo não existe
ERC-20/AMM/oráculo/lending nativos — todos dependem de uma **EVM**.

---

## 2. Decisão estrutural: onde roda a EVM

Foram avaliadas três estratégias:

| Estratégia | Prós | Contras |
|-----------|------|---------|
| **A. DeFi nativo em Python** (token, AMM, oráculo, lending escritos na mão) | Roda já na cadeia atual | **Não é EVM/Solidity**, sem ecossistema, sem MetaMask, sem bridges prontas |
| **B. Integrar uma EVM na própria chain** (mantendo PoW) | Roda Solidity, MetaMask, Uniswap/Aave forks, bridges prontas; reaproveita PoW/mempool/explorer | Reescreve a camada de estado/execução; finalidade PoW é problema para bridges |
| **C. Migrar para um framework EVM pronto** (Polygon Edge/Besu, Cosmos EVM/Evmos) | Compatibilidade máxima, tooling maduro | **Descarta a cadeia atual inteira** (PoW, explorer, core) |

**Escolha:** **Estratégia B** — integrar uma EVM como camada de execução da
KuramaChain, mantendo consenso PoW, mempool, explorer e Lightning.

> Motivo: preserva o que já existe e ainda dá compatibilidade EVM real.
> O custo é reescrever a camada de estado (de "saldos por endereço" para
> "state trie de contas + storage de contratos").

---

## 3. Arquitetura alvo

```
┌─────────────────────────────────────────────────────────────────────┐
│                      KURAMACHAIN (EVM-compatível)                   │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 6 — dApps / Wallets                                          │
│    MetaMask · WalletConnect · ethers.js/web3.js · frontend React     │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 5 — JSON-RPC (eth_*, net_*, web3_*)                          │
│    eth_chainId · eth_call · eth_sendRawTransaction · eth_getCode ... │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 4 — Contratos (Solidity)                                     │
│    ERC-20 · DEX (Uniswap V2) · LP/POOLS · Oráculo · Lending (Aave)   │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 3 — EVM (máquina de execução)                                │
│    Opcodes · gas · storage · logs/events · reverts                   │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 2 — Estado + contas                                          │
│    State trie (nonce, balance, code, storage) · account mapping       │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 1 — Consenso (PoW existente)                                 │
│    Minerador inclui txs EVM · reorg · mempool                        │
├─────────────────────────────────────────────────────────────────────┤
│  Camada 0 — Interop                                                │
│    Bridge lock/mint · mensageria cross-chain (LayerZero/Axelar)      │
└─────────────────────────────────────────────────────────────────────┘
```

O que **fica** da KuramaChain: PoW, mempool, SSE, explorer, Lightning, API REST.
O que **muda**: a camada 2 (estado) passa a ser de contas EVM; a camada 3 (EVM) é nova.

### Mapeamento de endereços
A cadeia usa Base58Check; a EVM usa `0x...`. `core/crypto_utils.py` já tem
`public_key_to_evm_address()` e `is_valid_evm_address()`. A conta EVM passa a
ser a **fonte de verdade** para saldo/gas; o endereço Base58 vira um "alias"
opcional derivado da mesma chave.

---

## 4. Os 7 itens → componentes concretos

| # | Item | Como é implementado |
|---|------|---------------------|
| 1 | **Smart contracts (EVM/Solidity)** | VM de execução + JSON-RPC `eth_*`. Compila Solidity → bytecode → deploy/`eth_call`/`eth_sendRawTransaction`. |
| 2 | **DEX** | Fork do **Uniswap V2** em Solidity: `Factory`, `Pair` (AMM `x*y=k`), `Router`. Interface via `ethers.js`/frontend. |
| 3 | **Pools de liquidez** | Cada `Pair` emite **LP tokens (ERC-20)**; provedores recebem taxa de 0,3% por swap. Recompensas de farming opcionais (`MasterChef`). |
| 4 | **Bridges** | **Implementado** como bridge próprio **lock/mint**: `KurBridge` (trava/queima na origem, libera/cunha no destino) + `KurWrappedToken` + **relayer** Python (`evm/bridge.py`) com atestação **m-de-n** de validadores. Mensageria (LayerZero/Axelar) segue como opção de ecossistema. |
| 5 | **Oráculos** | Padrão **Chainlink aggregator**: contrato `AggregatorV3Interface` + **nó oráculo** (Python) que assina preços off-chain e publica on-chain (feed de preço KUR/USD etc.). TWAP da DEX como fallback. |
| 6 | **Lending/Borrowing** | Fork do **Aave V2** em Solidity: `LendingPool`, `aToken`, `debtToken`, colateralização + liquidação por oráculo. |
| 7 | **Wallets e dApps** | **MetaMask** (EIP-1193/JSON-RPC `eth_*`): o nó responde `eth_chainId`, `eth_getBalance`, `eth_call`, `eth_sendRawTransaction`, `eth_getTransactionReceipt` (com logs), `eth_getLogs`, `eth_getTransactionByHash`, `eth_getBlockBy*` e `eth_feeHistory`, com CORS. O frontend traz o card de conexão + `wallet_addEthereumChain` (`frontend/src/api/metamask.ts`). WalletConnect fica como próximo passo. |
| 8 | **Staking/Farming** | **Implementado**: `KurStaking` multi-pool (`accRewardPerShare`) com recompensa por segundo e orçamento de prêmio separado do principal (stake KUR → ganha KUR é suportado). |

### Interoperabilidade ("conversar com outras redes")
A camada 0 resolve isso via **duas peças**:
1. **Mensageria cross-chain** (LayerZero/Axelar/Wormhole): contratos "endpoint"
   na KuramaChain + nas redes externas (Ethereum, BNB Chain, Arbitrum...),
   permitindo enviar mensagens/ativos entre redes.
2. **Bridge lock/mint** (se preferir soberania): trava KUR nesta rede, emite
   wrapper na rede destino e vice-versa, com um **relayer** monitorando eventos.

> ⚠️ **Ponto crítico de consenso:** bridges exigem **finalidade**. PoW tem
> finalidade **probabilística** (reorg até 100 blocos). Para operar bridge com
> segurança é preciso: (a) exigir N confirmações antes de liberar, (b)
> **checkpointing**, ou (c) migrar para consenso com finalidade (PoS/BFT).
> Sem tratar isso, um bridge PoW é um vetor de ataque de reorg.

---

## 5. Roadmap em fases (cada fase é verificável)

| Fase | Entregável | Critério de aceite | Status |
|------|-----------|--------------------|--------|
| **0. EVM + JSON-RPC** | Camada EVM + `eth_chainId`, `eth_getBalance`, `eth_call`, `eth_getCode`, `eth_sendRawTransaction`; mapeamento de contas; gas | Deploy e execução de um contrato Solidity trivial via JSON-RPC | ✅ `evm/engine.py`, `evm/rpc.py` · `tests/test_evm.py` |
| **1. Token (ERC-20)** | Contrato ERC-20 + script de deploy + transferência via RPC | `balanceOf`/`transfer` corretos via `eth_call` | ✅ `evm/contracts/KurToken.sol` · `tests/test_evm.py` |
| **2. DEX + Pools** | Uniswap V2 fork (Factory/Pair/Router/LP) | Swap `x*y=k` e emissão de LP tokens | ✅ `KurFactory/KurPair/KurRouter` · `tests/test_dex.py` |
| **3. Oráculo** | Aggregator + nó oráculo Python publicando preço | Preço on-chain atualiza e é lido por contrato | ✅ `KurPriceFeed/KurOracle` + `evm/oracle_node.py` · `tests/test_oracle.py` |
| **4. Lending** | Aave V2 fork + liquidação por oráculo | Depósito, empréstimo e liquidação funcionando | ✅ `KurLendingPool/KurScaledToken/KurPriceOracle` · `tests/test_lending.py` |
| **5. Staking/Farming** | `KurStaking` (pools, taxa por segundo, orçamento de prêmio) + deploy/testes | `stake`/`claim`/`withdraw` corretos, prêmio para em `rewardEnd` e nunca consome o principal | ✅ `KurStaking.sol` · `tests/test_staking.py` |
| **5. Bridge/Interop** | `KurBridge` lock/mint + `KurWrappedToken` + relayer com atestação m-de-n | Depósito na origem → wrapped no destino; volta queima e libera; replay/assinatura inválida rejeitados | ✅ `KurBridge.sol`, `KurWrappedToken.sol`, `evm/bridge.py` · `tests/test_bridge.py` |
| **6. Wallets/dApps** | JSON-RPC completo (logs, blocos, storage) + CORS + card MetaMask + **swap do DEX assinado pela carteira** | Conectar carteira na chain 9090, ler saldo/blocos/logs, enviar tx assinada e trocar qualquer par ERC-20 do `KurFactory` | ✅ `evm/rpc.py`, `frontend/src/api/{metamask,evmAbi,dex}.ts`, `SwapCard.tsx` · `tests/test_rpc_evm.py` (WalletConnect ⏳) |

**Dependência:** as fases 1–6 **dependem da Fase 0**. Sem a camada EVM, nada
de Solidity funciona.

> Fases **0 a 6** estão implementadas e cobertas por testes
> (`python -m pytest tests/test_evm.py tests/test_dex.py tests/test_oracle.py
> tests/test_lending.py tests/test_staking.py tests/test_bridge.py
> tests/test_rpc_evm.py`). Ver o detalhamento em §7.
>
> Pendências conscientes da Fase 6: **WalletConnect** e um bridge **externo** de
> verdade (a transferência entre redes reais exige finalidade — ver §8).

---

## 6. Stack recomendada

- **EVM:** `py-evm` (EVM em Python, integra sem sair do stack) **ou**
  `revm`/`evm` (Rust) exposto por socket, se performance for crítica.
- **Contratos:** Solidity + Foundry/Hardhat para compilar e testar.
- **JSON-RPC:** implementação própria sobre Flask (`eth_*`) reusando `run.py`.
- **Oráculo:** nó Python (`web3`/`eth-account`) assinando feeds.
- **Bridge:** LayerZero/Axelar (se ecossistema) ou Lockbox+Mintbox (se soberania).
- **Frontend:** `ethers.js` + `wagmi`/`viem`.

---

## 7. Implementado até agora (Fases 0–6)

```
evm/
├── engine.py          # EVM (py-evm, fork London) integrada à chain + selagem no PoW
├── rpc.py             # JSON-RPC eth_* (POST /rpc) — MetaMask/ethers.js
├── compiler.py        # solc (py-solc-x): compile_source / compile_contracts / compile_all
├── oracle_node.py     # Nó oráculo (Fase 3): preço off-chain → KurPriceFeed
├── deploy.py          # Deploy do feed/oráculo/lending com os defaults EVM_*_*
└── contracts/
    ├── KurToken.sol       # ERC-20 (Fase 1)
    ├── UQ112x112.sol      # ponto fixo 112.112 (acumuladores de preço)
    ├── KurPair.sol        # par AMM x*y=k + LP token + cumulativos de preço (Fase 2)
    ├── KurFactory.sol     # fábrica de pares (Fase 2)
    ├── KurRouter.sol      # addLiquidity / swapExactTokensForTokens (Fase 2)
    ├── KurPriceFeed.sol   # feed AggregatorV3 com reporters + quórum + mediana (Fase 3)
    ├── KurOracle.sol      # TWAP da DEX + fallback quando o feed está obsoleto (Fase 3)
    ├── KurScaledToken.sol # aToken/debtToken com índice ray (saldo que rende/juros) (Fase 4)
    ├── KurPriceOracle.sol # registro asset → feed, preço em 18 decimais (Fase 4)
    ├── KurLendingPool.sol # mercado de empréstimos + liquidação (Fase 4)
    ├── KurStaking.sol     # pools de staking/farming (Fase 5)
    ├── KurBridge.sol      # bridge lock/mint com validadores m-de-n (Fase 5)
    └── KurWrappedToken.sol # ativo externo representado na chain (Fase 5)
```

### Oráculo (Fase 3) — como funciona

**1. Feed primário — `KurPriceFeed` (compatível com `AggregatorV3Interface`).**
Nós oráculo autorizados (`reporters`) enviam o preço em 8 decimais com
`submit(int256)`. Quando o número de envios da rodada atinge o `quorum`, a
rodada fecha com a **mediana** dos valores — um único reporter desonesto não
move o preço. Rodadas ficam consultáveis por `latestRoundData()` /
`getRoundData(roundId)`, exatamente como em um agregador Chainlink.

**2. Fallback — `KurOracle` (TWAP da DEX).** `KurPair` mantém acumuladores
`price0CumulativeLast` / `price1CumulativeLast` (preço × tempo em UQ112x112),
atualizados em cada `mint`/`burn`/`swap`. O `KurOracle` faz um snapshot e expõe:

```solidity
oracle.update();                       // atualiza a janela da TWAP (period)
oracle.consult(tokenIn, amountIn);     // converte usando a TWAP
oracle.getPrice();                     // (prego8, fromFeed)
```

`getPrice()` devolve o preço do feed enquanto ele estiver **fresco**
(`block.timestamp - updatedAt <= maxAge`) e cai automaticamente na TWAP
quando o feed fica obsoleto ou reverte — a DEX continua servindo como oráculo
de último recurso.

**3. Nó oráculo Python — `evm/oracle_node.py`.** Obtém o preço off-chain
(fontes plugáveis: `FixedPriceSource`, `RandomWalkSource`, `HttpJsonPriceSource`),
valida o **desvio máximo** contra o último preço on-chain (anti "fat finger") e
publica no feed; quando o quórum de reporters é atingido, a rodada fecha.

```python
from evm.engine import EVMEngine
from evm.oracle_node import KurOracleNode, HttpJsonPriceSource

node = KurOracleNode(
    engine=EVMEngine(),
    feed='0x<endereço do KurPriceFeed>',
    private_key='0x<chave do reporter>',
    source=HttpJsonPriceSource('https://api.coingecko.com/api/v3/simple/price'
                               '?ids=kusama&vs_currencies=usd', ['kusama', 'usd']),
)
node.publish_once()
node.run(interval=60)
```

> O nó publica **em processo** (a `EVMEngine` assina com a chave do reporter) —
é o mesmo caminho usado por `run.py`. Um nó externo que fale apenas JSON-RPC
precisa de um assinador próprio (`eth-account`) e de `eth_sendRawTransaction`.

**4. Deploy — `evm/deploy.py`.** Sobe o feed e o oráculo aplicando os defaults
de `config` (`EVM_ORACLE_QUORUM`, `EVM_ORACLE_PRIVATE_KEY`, `EVM_ORACLE_PERIOD`,
`EVM_ORACLE_MAX_AGE`) — é o caminho suportado fora dos testes:

```python
from evm.deploy import deploy_price_feed, deploy_oracle

_, feed = deploy_price_feed(engine)                          # descrição/quorum/reporter do config
_, oracle = deploy_oracle(engine, pair='0x<par>', feed=feed) # period/maxAge do config
```

### Lending (Fase 4) — como funciona

**1. Preço — `KurPriceOracle`.** Registra um feed `AggregatorV3` (os
`KurPriceFeed` da Fase 3) por ativo e normaliza tudo em **18 decimais**. Preço
**obsoleto reverte** (`maxAge`), então o pool nunca calcula colateral com preço
velho; `maxAge = 0` desativa a checagem.

**2. Mercado — `KurLendingPool` (fork do Aave V2).** Cada ativo tem uma
reserva com `aToken` (depósito que rende juros) e `debtToken` (dívida que
cresce com os juros), ambos instâncias de `KurScaledToken` (saldo **escalado**
por um índice em ray: `balanceOf = scaledBalance * index / 1e27`).

```solidity
pool.initReserve(asset, ltv, liquidationThreshold, liquidationBonus, reserveFactor);
pool.deposit(asset, amount, onBehalfOf);   // vira aToken (colateral)
pool.withdraw(asset, amount, to);          // amount = type(uint256).max → tudo
pool.borrow(asset, amount, onBehalfOf);    // taxa variável
pool.repay(asset, amount, onBehalfOf);     // amount > dívida → paga só a dívida
pool.liquidationCall(collateral, debt, user, debtToCover);
pool.getUserAccountData(user);             // colateral, dívida, LTV, healthFactor
```

Modelo de juros (taxa **por segundo**, em ray):

```
u             = dívida / (dívida + liquidez disponível)
borrowRate    = base + slope1*u/optimal                       (u <= optimal)
              = base + slope1 + slope2*(u-optimal)/(1-optimal) (u  > optimal)
liquidityRate = borrowRate * u * (1 - reserveFactor)
```

Os juros são capitalizados de forma **linear** no intervalo entre dois
`accrue` (não compostos como no Aave) e a fatia do `reserveFactor` vai para
`accruedTreasury` (resgatável pelo owner com `claimTreasury`).

**3. Liquidação por oráculo.** Quando o preço do colateral cai e o
`healthFactor` fica abaixo de `1e18`, qualquer conta chama `liquidationCall`:
o liquidante paga `debtToCover` do ativo da dívida (limitado pelo
`closeFactor`, ex.: 50%) e recebe o equivalente em colateral **mais o
`liquidationBonus`** (ex.: 5%). O `healthFactor` é
`Σ(colateral × liquidationThreshold) / dívida`.

**4. Deploy — `evm/deploy.py`.** Aplica os defaults de `config`
(`EVM_LENDING_*`) no caminho suportado fora dos testes:

```python
from evm.deploy import deploy_lending_pool, deploy_price_oracle, init_reserve

_, prices = deploy_price_oracle(engine)            # maxAge do config
_, pool = deploy_lending_pool(engine, prices)      # taxas + closeFactor do config
_, (aToken, debtToken) = init_reserve(engine, pool, asset)  # LTV/limiar/bônus do config
```

**5. Tempo determinístico — `engine.advance_time(seconds)`.** Sela um bloco
(possivelmente vazio) com o relógio avançado e, a partir daí, cada bloco
avança exatamente 1s — usado nos testes para medir juros de um ano sem
esperar em tempo real.

> **Quirk do engine (py-evm):** no fork London do py-evm a transação pendente é
> executada com o timestamp do bloco **anterior** e só depois o header do novo
> bloco é selado com `+1s`. Assim, qualquer accrual por tempo (juros, TWAP,
> prêmio de staking) pode aparecer com ~1s de "dust" logo após uma interação.
> Os testes toleram esse segundo; contratos não devem depender de precisão
> sub-segundo.

### Staking (Fase 5) — como funciona

**1. Contrato — `KurStaking` (farm multi-pool).** Cada pool guarda
`stakingToken`, `rewardToken`, `rewardRate` (por segundo), `rewardEnd`, o
acumulador `accRewardPerShare` (escala 1e18) e o `rewardBudget`. A recompensa de
um usuário é `amount * accRewardPerShare / 1e18 - rewardDebt` (+ `pending` já
consolidado) — o mesmo modelo do `MasterChef`.

```solidity
staking.createPool(stakingToken, rewardToken, rewardRate, rewardEnd); // owner
staking.fundPool(pid, amount);        // abastece o orçamento de prêmio
staking.stake(pid, amount);           // requer approve(staking, amount)
staking.withdraw(pid, amount);        // devolve principal (settle antes)
staking.claim(pid);                   // paga o prêmio acumulado
staking.emergencyWithdraw(pid);       // sai sem prêmio (se o reward travar)
staking.pendingReward(pid, user);     // prêmio disponível agora
```

**2. Por que `rewardBudget`.** Stake KUR → ganha KUR é um caso real (o token de
stake e o de prêmio podem ser o mesmo). Para o principal nunca virar prêmio, o
`claim` só paga enquanto houver orçamento abastecido via `fundPool`
(`REWARD_BUDGET_EXHAUSTED` caso contrário) — o `withdraw` do principal segue
funcionando.

**3. Emissão.** `_updatePool` credita `rate × (min(now, rewardEnd) - lastUpdate)`
proporcionalmente ao total em stake e para em `rewardEnd`; `setRewardRate`
consolida antes de mudar a taxa.

**4. Deploy — `evm/deploy.py`.** `deploy_staking`, `create_staking_pool`
(devolve o `pid`), `fund_staking_pool`, `stake_tokens`, `claim_rewards` e
`unstake_tokens` (todos verificam o status do recibo e levantam se reverterem).

### Bridge (Fase 5) — como funciona

**1. Contratos.** `KurBridge` (implantado **em cada rede**, com o `localChainId`
respectivo, validadores e `threshold`) e `KurWrappedToken` (ERC-20 que só o
bridge pode cunhar/queimar).

```solidity
// origem: trava o token nativo (ou queima o wrapped, na volta)
bridge.deposit(token, amount, destChain, recipient);   // → evento Deposit(depositId, ...)

// destino: comprova o depósito e libera/cunha
bridge.withdraw(srcChain, token, recipient, amount, nonce, depositId, signatures);

bridge.registerWrapped(remoteChain, remoteToken, wrappedToken);  // saque cunha
bridge.registerRelease(remoteChain, remoteToken, localToken);    // saque libera
```

**2. Atestação m-de-n.** Os validadores assinam o digest **EIP-191** de
`keccak256(abi.encode(srcChain, localChainId, token, recipient, amount, nonce,
depositId, bridge))`. `withdraw` exige `threshold` assinaturas de validadores
**distintos**, em **ordem crescente de endereço** (evita duplicata), rejeita
`high-s` (maleabilidade) e marca o `depositId` como processado (anti-replay).

**3. Relayer — `evm/bridge.py`.** `parse_deposit_log` decodifica o evento,
`withdrawal_digest` / `sign_withdrawal` montam as assinaturas (low-s, v=27/28) e
`BridgeRelayer.process()` lê `eth_getLogs`, filtra os depósitos com destino a
esta chain, assina com as chaves dos validadores e envia o `withdraw` (o
`submitter_key` paga o gas e não precisa ser validador).

**4. Deploy — `evm/deploy.py`.** `deploy_bridge` (validadores/`threshold` do
config), `deploy_wrapped_token`, `register_wrapped`, `register_release` e
`bridge_deposit`.

> ⚠️ O modelo de segurança do bridge é a **confiança no conjunto de
> validadores** (m-de-n). Em produção: chaves em KMS/HSM, N confirmações antes
> de atestar e monitoramento de reorg (§8).

### Wallets/dApps (Fase 6) — como funciona

**1. JSON-RPC de carteira.** Além dos métodos da Fase 0, o `POST /rpc` agora
responde `eth_getTransactionReceipt` **com logs/eventos**, `eth_getLogs`
(filtro de endereço/topics), `eth_getTransactionByHash`,
`eth_getBlockByNumber|ByHash` (com transações completas),
`eth_getBlockTransactionCountBy*`, `eth_getStorageAt` e `eth_feeHistory` — o
conjunto que ethers.js/web3.js/MetaMask usam para carregar saldo, histórico e
eventos.

**2. CORS.** O endpoint `/rpc` responde com `Access-Control-Allow-Origin`
(`EVM_RPC_CORS_ORIGIN`, default `*` em dev) para que uma dApp no browser fale
com o nó de outra origem.

**3. MetaMask.** A wallet assina localmente e envia a transação **crua**
(`eth_sendRawTransaction`) — o nó não custodia chave. O frontend
(`frontend/src/api/metamask.ts` + `MetaMaskCard.tsx`) pede contas
(`eth_requestAccounts`), adiciona/troca a rede (`wallet_addEthereumChain` /
`wallet_switchEthereumChain`, chain ID 9090) e mostra endereço, saldo e rede.

**4. Swap assinado pela carteira.** A aba **DeFi → Swap** (`SwapCard.tsx`) fecha o
ciclo do DEX sem trazer ethers.js/web3.js:

- `evmAbi.ts` guarda os **seletores/tópicos** (`keccak256`) e codifica/decodifica
  ABI à mão (`uint256`, `address`, `address[]`);
- `dex.ts` descobre o par em `router.factory()` → `getPair(tokenIn, tokenOut)`,
  lê `getReserves()`/`token0()`/`decimals()`/`balanceOf()`/`allowance()` por
  `eth_call` e cota com a **mesma fórmula** do contrato (0,3% de taxa);
- ao trocar, se a allowance for insuficiente a wallet assina um `approve` e, na
  sequência, `swapExactTokensForTokens(amountIn, amountOutMin, [in, out], conta)`;
  o `amountOut` vem do evento `SwapExecuted` no recibo;
- funciona para **qualquer par ERC-20** existente no factory (o par inexistente é
  detectado antes de assinar). O router pode vir de `VITE_KUR_ROUTER` ou ser
  colado na UI (persistido no `localStorage`).

**5. Gas estimado com o sender real.** `eth_estimateGas` simula a mensagem com o
`from` informado (num *costless state*), então `approve`/`swap` recebem gas
suficiente — um swap do DEX gasta ~134k e o valor fixo anterior (100k) faria a
tx reverter por falta de gas. Revert na simulação vira erro JSON-RPC (-32000),
para a wallet avisar antes de assinar.

```bash
# configure no MetaMask (ou clique em “Conectar MetaMask” na aba DeFi)
Rede:        KuramaChain
RPC URL:     http://localhost:5000/rpc   (o frontend usa <origem>/rpc)
Chain ID:    9090
Símbolo:     KUR
```

### Configuração (variáveis de ambiente)

| Variável | Default | Descrição |
|----------|---------|-----------|
| `EVM_CHAIN_ID` | `9090` | Chain ID da EVM |
| `EVM_AUTO_MINE` | `True` | Sela um bloco EVM por transação (modo dev) |
| `EVM_GENESIS_BALANCE_ETH` | `10000` | Saldo da conta de desenvolvimento no gênese |
| `EVM_DEV_PRIVATE_KEY` | `0x11…` | Chave de dev (**apenas testes/demo**) |
| `EVM_ORACLE_PRIVATE_KEY` | `0x33…` | Chave do reporter do oráculo |
| `EVM_ORACLE_QUORUM` | `1` | Reporters necessários para fechar uma rodada |
| `EVM_ORACLE_MAX_AGE` | `3600` | Idade máxima (s) do preço do feed antes do fallback TWAP |
| `EVM_ORACLE_PERIOD` | `300` | Janela mínima (s) da TWAP |
| `EVM_ORACLE_INTERVAL` | `60` | Intervalo (s) de publicação do nó |
| `EVM_ORACLE_MAX_DEVIATION_PCT` | `20` | Desvio máximo (%) aceito pelo nó (0 desativa) |
| `EVM_LENDING_PRIVATE_KEY` | `0x44…` | Chave que implanta/configura o mercado |
| `EVM_LENDING_LTV_BPS` | `7500` | LTV inicial das reservas (bps) |
| `EVM_LENDING_LIQ_THRESHOLD_BPS` | `8000` | Limiar de liquidação (bps) |
| `EVM_LENDING_LIQ_BONUS_BPS` | `10500` | Bônus do liquidante (bps; 10500 = 5%) |
| `EVM_LENDING_CLOSE_FACTOR_BPS` | `5000` | Fração máxima da dívida liquidável (bps) |
| `EVM_LENDING_RESERVE_FACTOR_BPS` | `1000` | Parte dos juros que fica com o protocolo (bps) |
| `EVM_LENDING_BASE_RATE_APR` | `0` | Juros base (% a.a.) |
| `EVM_LENDING_SLOPE1_APR` | `4` | Inclinação 1 (% a.a.) — até a utilização ótima |
| `EVM_LENDING_SLOPE2_APR` | `75` | Inclinação 2 (% a.a.) — acima da utilização ótima |
| `EVM_LENDING_OPTIMAL_UTILIZATION_PCT` | `80` | Utilização ótima (%) |
| `EVM_LENDING_PRICE_MAX_AGE` | `3600` | Idade máxima (s) do preço usado pelo pool (0 desativa) |
| `EVM_STAKING_PRIVATE_KEY` | `0x55…` | Chave do owner dos pools de staking (precisa de saldo) |
| `EVM_BRIDGE_PRIVATE_KEY` | `0x66…` | Chave do owner do bridge (precisa de saldo) |
| `EVM_BRIDGE_VALIDATOR_KEYS` | `0x77…,0x88…,0x99…` | Chaves dos validadores que atestam depósitos (lista separada por vírgula) |
| `EVM_BRIDGE_THRESHOLD` | `2` | Assinaturas de validadores distintas para liberar um saque |
| `EVM_RPC_CORS_ORIGIN` | `*` | Origem permitida no CORS do `POST /rpc` (restrinja em produção) |

---

## 8. Riscos e decisões em aberto

1. **Finalidade PoW vs bridges** — exige N confirmações/checkpoint ou PoS. O
   `KurBridge` já implementa lock/mint + atestação, mas **ainda não aplica uma
   política de confirmações** por conta própria: o relayer deve esperar N
   blocos antes de atestar (ou a chain migrar para consenso com finalidade).
2. **Confiança nos validadores do bridge** — m-de-n é uma federação: as chaves
   precisam viver em KMS/HSM, com rotação, monitoramento e limites de valor.
3. **Modelo de endereço** — unificar Base58 ↔ EVM (`0x...`).
4. **Mempool/gas** — introduzir gas pago ao minerador (hoje a fee existe mas é simbólica).
5. **Storage** — sair de JSON para um state store eficiente (LevelDB/RocksDB/SQLite).
6. **Escopo das bridges** — mensageria pronta (rápido) vs bridge próprio (soberano, trabalhoso); hoje há o próprio (lock/mint).
7. **RPC em produção** — `EVM_RPC_CORS_ORIGIN=*` e a chave de dev no gênese são
   aceitáveis só em dev; restrinja o CORS, desligue `EVM_AUTO_MINE` e use faucet.
8. **Índice de logs em memória** — `eth_getLogs` varre os blocos sob demanda
   (limite de 100k por consulta) e o índice de txs vive na memória do processo;
   um índice persistente (SQLite) é o próximo passo de performance.
