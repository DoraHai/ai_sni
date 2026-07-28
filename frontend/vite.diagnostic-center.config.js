import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve('diagnostic-center'),
  base: '/diagnostic-center/',
  publicDir: false,
  plugins: [vue()],
  build: {
    outDir: resolve('dist-diagnostic-center'),
    emptyOutDir: true,
  },
  server: {
    port: 5175,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
