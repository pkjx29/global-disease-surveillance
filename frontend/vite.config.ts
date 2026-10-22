import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the API runs on :8000; in production nginx proxies /api to the API service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // the key is added here, server-side, so it never reaches the browser bundle
      '/api': {
        target: process.env.VITE_DEV_API ?? 'http://localhost:8000',
        changeOrigin: true,
        headers: { 'X-API-Key': process.env.API_KEY ?? '' },
      },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
