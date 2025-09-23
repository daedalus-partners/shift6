import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/health': { target: 'http://backend:8000', changeOrigin: true },
      '/clients': { target: 'http://backend:8000', changeOrigin: true },
      '/knowledge': { target: 'http://backend:8000', changeOrigin: true },
      '/styles': { target: 'http://backend:8000', changeOrigin: true },
      '/samples': { target: 'http://backend:8000', changeOrigin: true },
      '/retrieval': { target: 'http://backend:8000', changeOrigin: true },
      '/generate': { target: 'http://backend:8000', changeOrigin: true },
      '/api/v1': { target: 'http://backend:8000', changeOrigin: true },
    },
  },
})
