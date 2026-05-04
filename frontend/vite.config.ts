import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:5000',
      '/chain': 'http://localhost:5000',
      '/mine': 'http://localhost:5000',
      '/transactions': 'http://localhost:5000',
      '/wallet': 'http://localhost:5000',
      '/balance': 'http://localhost:5000',
      '/nodes': 'http://localhost:5000',
      '/validate': 'http://localhost:5000',
      '/stats': 'http://localhost:5000',
    },
  },
})
