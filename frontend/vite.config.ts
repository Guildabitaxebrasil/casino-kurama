import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `/wallet` e `/transactions` existem nos dois lados: são rotas do SPA e
// prefixos da API do nó. O navegador pede a página (Accept: text/html) e o
// axios pede dados (Accept: application/json...). Sem separar os dois, abrir
// ou recarregar essas rotas caía no proxy e voltava 404 do nó.
const spaFallback = (req: { headers: Record<string, string | string[] | undefined> }) => {
  const accept = req.headers.accept
  return typeof accept === 'string' && accept.includes('text/html')
    ? '/index.html'
    : undefined
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // ⚠️ Dev only: `secure: false` permite certificados auto-assinados.
      // Em produção, configure HTTPS real com CA confiável no servidor
      // backend e remova `secure: false` (ou aponte para o certificado CA).
      '/api': { target: 'https://localhost:5000', secure: false },
      '/chain': { target: 'https://localhost:5000', secure: false },
      '/mine': { target: 'https://localhost:5000', secure: false },
      '/transactions': { target: 'https://localhost:5000', secure: false, bypass: spaFallback },
      '/wallet': { target: 'https://localhost:5000', secure: false, bypass: spaFallback },
      '/balance': { target: 'https://localhost:5000', secure: false },
      '/nodes': { target: 'https://localhost:5000', secure: false },
      '/validate': { target: 'https://localhost:5000', secure: false },
      '/stats': { target: 'https://localhost:5000', secure: false },
      '/rpc': { target: 'https://localhost:5000', secure: false },
      '/api/transactions/create-signed': { target: 'https://localhost:5000', secure: false },
    },
  },
})
