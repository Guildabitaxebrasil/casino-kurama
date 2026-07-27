# HTTPS Encryption for KURAMACHAIN

## Context

Toda comunicação no KURAMACHAIN atualmente usa HTTP puro — API REST, comunicação entre nós P2P, e proxy do frontend. Isso expõe chaves privadas, transações e dados sensíveis em texto puro na rede. Vamos adicionar HTTPS com certificados auto-assinados para criptografar toda a comunicação.

## Files to Modify

1. **`config.py`** — Adicionar constantes: `SSL_CERT_DIR`, `SSL_CERT_FILE`, `SSL_KEY_FILE`, `USE_HTTPS`
2. **`run.py`** — Adicionar:
   - Função `ensure_certificates()` que gera certificados auto-assinados via `openssl` se não existirem
   - Chamar antes de iniciar o servidor
   - Atualizar `app.run()` com `ssl_context`
   - Atualizar URLs de console para `https://`
3. **`api/routes.py`** — Adicionar:
   - Suprimir warnings `urllib3` para certs auto-assinados
4. **`node/node_manager.py`** — Mudar:
   - URLs de `http://` para `https://`
   - `requests.get/post()` com `verify=False` e `urllib3` warnings suprimidos
5. **`frontend/vite.config.ts`** — Mudar:
   - Proxy targets de `http://localhost:5000` para `https://localhost:5000`
   - Adicionar `secure: false` para aceitar certs auto-assinados

## New Files

6. **`certs/`** — Diretório para armazenar certificados (criado automaticamente)

## Implementation Details

### Certificate Generation (`ensure_certificates()` em `run.py`)

```python
def ensure_certificates():
    """Gera certificados SSL auto-assinados se não existirem."""
    from config import SSL_CERT_DIR, SSL_CERT_FILE, SSL_KEY_FILE
    import subprocess, os
    
    os.makedirs(SSL_CERT_DIR, exist_ok=True)
    
    if not os.path.exists(SSL_CERT_FILE) or not os.path.exists(SSL_KEY_FILE):
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', SSL_KEY_FILE, '-out', SSL_CERT_FILE,
            '-days', '3650', '-nodes',
            '-subj', '/CN=KuramaChain/O=KuramaNetwork/C=BR'
        ], check=True, capture_output=True)
        print(f"🔐 Certificados SSL gerados em {SSL_CERT_DIR}/")
```

### Flask Server (`run.py`)

```python
app.run(host='0.0.0.0', port=args.port, 
        ssl_context=('certs/cert.pem', 'certs/key.pem'),
        debug=False)
```

### Node Manager (`node_manager.py`)

```python
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# URLs passam a usar https
self.url = f'https://{host}:{port}'

# Todas as requests com verify=False
requests.get(f'{node_url}/chain', verify=False, timeout=NODE_TIMEOUT)
```

### Vite Proxy (`frontend/vite.config.ts`)

```typescript
proxy: {
  '/api': { target: 'https://localhost:5000', secure: false },
  '/chain': { target: 'https://localhost:5000', secure: false },
  // ... etc
}
```

## Fallback HTTP

Adicionar flag `--no-ssl` no CLI para rodar sem HTTPS quando necessário (ex: atrás de um reverse proxy que já termina SSL):

```python
parser.add_argument('--no-ssl', action='store_true',
                    help='Desabilitar HTTPS (usar HTTP puro)')
```

## Verification

1. Rodar `python run.py` — verificar mensagem "🔐 Certificados SSL gerados"
2. Verificar que server log mostra `https://localhost:5000`
3. Rodar `curl -k https://localhost:5000/chain` — deve funcionar com `-k` (insecure)
4. Rodar `python run.py --network --nodes 3` — verificar comunicação P2P via HTTPS
5. Rodar `python -m pytest tests/ -v` — todos os 40 testes passam
6. Iniciar frontend com `npm run dev` — verificar proxy funciona com HTTPS
