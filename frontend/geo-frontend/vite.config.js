import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve('../public/deal-sniper-prototype/geo'),
  base: '/deal-sniper/geo/',
  publicDir: false,
  server: {
    port: 5175,
    proxy: {
      // Local demo: frontend on :5175 → GEO API on :8010
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
