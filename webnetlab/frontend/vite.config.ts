import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // Forward all /api and /health requests to the backend container.
      // "backend" resolves inside Docker Compose; use localhost:8000 when
      // running Vite directly on the host.
      '/api': {
        target: process.env.VITE_API_URL ?? 'http://backend:8000',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.VITE_API_URL ?? 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
})
