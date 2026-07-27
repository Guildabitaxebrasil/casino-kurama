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
      '/api': { target: 'http://localhost:5000', secure: false },
      '/chain': { target: 'http://localhost:5000', secure: false },
      '/mine': { target: 'http://localhost:5000', secure: false },
      '/transactions': { target: 'http://localhost:5000', secure: false },
      '/wallet': { target: 'http://localhost:5000', secure: false },
      '/balance': { target: 'http://localhost:5000', secure: false },
      '/nodes': { target: 'http://localhost:5000', secure: false },
      '/validate': { target: 'http://localhost:5000', secure: false },
      '/stats': { target: 'http://localhost:5000', secure: false },
    },
  },
})
