# 🔐 Relatório de Auditoria de Segurança — KuramaChain v2.0

**Data:** 26 de Julho de 2026
**Auditor:** Buffy (AI Security Analyst)
**Classificação:** Confidencial — Análise Interna

---

## Resumo Executivo

| Métrica | Valor |
|---|---|
| **Segurança Geral** | **7.5 / 10** |
| **Pronto para Produção?** | **Parcialmente** (com correções abaixo) |
| **Vulnerabilidades Críticas** | 1 |
| **Vulnerabilidades Altas** | 3 |
| **Vulnerabilidades Médias** | 4 |
| **Vulnerabilidades Baixas** | 3 |

### Melhorias desde v1.0

| # | Vulnerabilidade v1.0 | Status |
|---|---|---|
| 1 | P2P sem autenticação | ✅ Corrigido (HMAC-SHA256 + ECDSA) |
| 2 | Consenso sem cumulative work | ✅ Corrigido |
| 3 | verify=False em produção | ✅ Corrigido (fail-hard com CA) |
| 4 | Exposição de chave privada | ⚠️ Parcial (dev endpoint ainda expõe) |
| 5 | Rate limit básico | ✅ Corrigido (multi-camada) |
| 6 | Sem anti-replay | ✅ Corrigido (nonce + TTL) |
| 7 | Sem proteção eclipse | ✅ Corrigido (subnet diversity) |
| 8 | Sem peer scoring | ✅ Corrigido (exponential backoff) |

---

## 🔴 CRÍTICO

### C-01: Endpoint /wallet/new Ainda Retorna Chave Privada

**Descrição:** O endpoint `POST /wallet/new` retorna `private_key_pem` no corpo da resposta HTTP. Embora o código tenha comentários indicando "Dev only", isso é uma vulnerabilidade em produção.

**Impacto:** MITM pode capturar chaves privadas de todas as carteiras geradas.

**Localização:** `api/routes.py:684`

```python
# Código atual (VULNERÁVEL):
data['private_key_pem'] = wallet.private_key_pem
```

**Correção necessária:**
```python
# Em produção, NÃO retornar private_key_pem
import os
if not os.environ.get('KURAMA_PRODUCTION', '').lower() in ('1', 'true', 'yes'):
    data['private_key_pem'] = wallet.private_key_pem
```

---

## 🟠 ALTO

### A-01: Endpoint /api/transactions/create-signed Aceita Chave Privada pela Rede

**Descrição:** O endpoint `/api/transactions/create-signed` aceita `private_key_pem` no body da requisição para assinar transações. Isso expõe chaves privadas em trânsito.

**Impacto:** Mesmo com HTTPS, chaves privadas trafegam pela rede. Em produção, a assinatura deve ser feita exclusivamente no cliente.

**Localização:** `api/routes.py:1549-1560`

**Correção:** Desabilitar este endpoint em produção ou exigir autenticação adicional.

---

### A-02: /api/events (SSE) Sem Autenticação ou Rate Limit

**Descrição:** O endpoint SSE `/api/events` não tem autenticação nem rate limiting. Um atacante pode criar muitas conexões SSE e esgotar recursos do servidor.

**Impacto:** DoS via exaustão de conexões/threads.

**Localização:** `api/routes.py:1430-1460`

**Correção:**
```python
@app.route('/api/events', methods=['GET'])
@rate_limit  # Adicionar rate limit
def api_events():
    ...
```

---

### A-03: Chave Privada Parcialmente Logada no stdout

**Descrição:** A função `new_wallet()` imprime os primeiros 50 caracteres da chave privada no stdout.

**Impacto:** Logs podem ser acessados por atacantes com acesso ao servidor.

**Localização:** `api/routes.py:676`

```python
# Código atual:
print(f"   Chave Privada: {wallet.private_key_pem[:50]}...")
```

**Correção:** Remover ou mascarar completamente o log da chave privada.

---

## 🟡 MÉDIO

### M-01: Headers de Rate Limit Ausentes nas Respostas

**Descrição:** As respostas HTTP não incluem headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

**Impacto:** Clientes não sabem seus limites, causando erros 429 inesperados.

**Correção:**
```python
def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = _get_client_ip()
        # ... lógica atual ...
        response = f(*args, **kwargs)
        # Adiciona headers de rate limit
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(rate_limiter.max_requests)
            response.headers['X-RateLimit-Remaining'] = str(remaining)
        return response
    return decorated
```

---

### M-02: Rate Limiter Volátil (In-Memory)

**Descrição:** O rate limiter é baseado em memória. Se o servidor reiniciar, todos os limites são zerados.

**Impacto:** Ataque DoS pode ser repetido após restart.

**Correção para produção:** Usar Redis ou memcached para persistência.

---

### M-03: Balance Endpoint Expõe Histórico Completo

**Descrição:** `GET /balance/<address>` retorna até 20 transações com valores e endereços.

**Impacto:** Vazamento de metadados financeiros.

**Correção:** Retornar apenas saldo e contagem, sem detalhes de transações.

---

### M-04: Swagger UI Sem Restrição de Acesso

**Descrição:** O endpoint `/api/docs` (Swagger UI) está acessível publicamente.

**Impacto:** Documentação completa da API exposta a atacantes.

**Correção:** Restringir acesso em produção via autenticação.

---

## 🔵 BAIXO

### B-01: Nonce P2P Não Incluído em Todas as Requisições

**Descrição:** O nonce anti-replay nem sempre é enviado em requisições P2P internas.

**Impacto:** Potencial para replay attacks em cenários específicos.

---

### B-02: Timestamp do Sistema Não Sincronizado

**Descrição:** A validação de timestamp depende do relógio local quando `USE_NETWORK_TIME=False`.

**Impacto:** Nós com relógio desincronizado podem aceitar/rejeitar blocos incorretamente.

---

### B-03: Mensagens de Erro Detalhadas em Respostas 4xx

**Descrição:** Algumas respostas de erro incluem detalhes internos (ex: "Endereço de minerador inválido").

**Impacto:** Informação útil para atacantes reconhecerem o sistema.

---

## ✅ Controles de Segurança Implementados

| Controle | Status | Localização |
|---|---|---|
| HMAC-SHA256 P2P Auth | ✅ Ativo | `routes.py:_require_p2p_hmac` |
| ECDSA P2P Signatures | ✅ Ativo | `routes.py:receive_block` |
| Rate Limit Multi-Camada | ✅ Ativo | `routes.py:AdvancedRateLimiter` |
| Nonce Anti-Replay | ✅ Ativo | `routes.py:require_p2p_nonce` |
| Peer Scoring + Ban | ✅ Ativo | `p2p_security.py:PeerScoreManager` |
| Eclipse Protection | ✅ Ativo | `p2p_security.py:EclipseProtection` |
| Cumulative Work Consensus | ✅ Ativo | `blockchain.py:resolve_conflicts` |
| Difficulty Floor | ✅ Ativo | `config.py:MIN_ACCEPTABLE_DIFFICULTY=2` |
| DNS Rebinding Protection | ✅ Ativo | `routes.py:_validate_node_dns` |
| SSRF Protection | ✅ Ativo | `routes.py:register_nodes` |
| Security Headers | ✅ Ativo | `routes.py:add_security_headers` |
| Error Sanitization | ✅ Ativo | `routes.py:add_security_headers` |
| AES-256-GCM Wallet Encryption | ✅ Ativo | `wallet.py:encrypt_to_file` |
| Argon2 Key Derivation | ✅ Ativo | `crypto_utils.py:derive_key_argon2` |
| Mempool Concurrency Lock | ✅ Ativo | `blockchain.py:_mempool_lock` |
| Mining Race Condition Lock | ✅ Ativo | `blockchain.py:_mining_lock` |

---

## 🛡️ Recomendações para Produção

### Prioridade 1 (Antes do Deploy)
1. ✅ Desabilitar `/wallet/new` em produção (não retornar private_key)
2. ✅ Desabilitar `/api/transactions/create-signed` em produção
3. ✅ Adicionar rate limit ao `/api/events`
4. ✅ Remover log de chave privada

### Prioridade 2 (Manutenção Contínua)
1. Implementar Redis para rate limiting persistente
2. Adicionar headers `X-RateLimit-*` nas respostas
3. Configurar monitoramento de peer scores
4. Implementar alertas para tentativas de eclipse attack

### Prioridade 3 (Hardening)
1. Implementar certificate pinning para mTLS
2. Adicionar WAF (Web Application Firewall)
3. Implementar log aggregation e SIEM
4. Adicionar penetration testing periódico

---

## 📊 Score Final

| Área | Score | Notas |
|---|---|---|
| Criptografia | 9/10 | ECDSA, AES-256-GCM, Argon2 |
| Autenticação P2P | 8.5/10 | HMAC + ECDSA signatures |
| Rate Limiting | 7/10 | Multi-camada, mas volátil |
| Consenso | 8/10 | Cumulative work + difficulty floor |
| Anti-Replay | 8/10 | Nonce + TTL + LRU cache |
| Eclipse Protection | 8/10 | Subnet diversity + peer scoring |
| API Security | 6.5/10 | Headers OK, mas endpoints sensíveis expostos |
| **Geral** | **7.5/10** | **Pronto para staging, não para produção** |

---

**Próximos Passos:** Implementar correções de Prioridade 1 antes de qualquer deploy em produção.
