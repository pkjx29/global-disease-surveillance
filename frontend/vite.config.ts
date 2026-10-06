import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the API runs on :8000; in production nginx proxies /api to the API service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_DEV_API ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
