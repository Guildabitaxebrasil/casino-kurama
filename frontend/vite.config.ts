import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
      '/transactions': { target: 'https://localhost:5000', secure: false },
      '/wallet': { target: 'https://localhost:5000', secure: false },
      '/balance': { target: 'https://localhost:5000', secure: false },
      '/nodes': { target: 'https://localhost:5000', secure: false },
      '/validate': { target: 'https://localhost:5000', secure: false },
      '/stats': { target: 'https://localhost:5000', secure: false },
      '/rpc': { target: 'https://localhost:5000', secure: false },
      '/api/transactions/create-signed': { target: 'https://localhost:5000', secure: false },
    },
  },
})
