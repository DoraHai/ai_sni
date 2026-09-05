import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve('diagnostic-center'),
  envDir: resolve('.'),
  base: '/diagnostic-center/',
  publicDir: false,
  plugins: [vue()],
  build: {
    outDir: resolve('dist-diagnostic-center'),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api/v1/diagnostic': {
        target: process.env.DIAGNOSTIC_API_PROXY_TARGET || 'http://127.0.0.1:8012',
        changeOrigin: true,
      },
      '/api': {
        // GEO 独立进程（含 audits + content）；本机 8010 常被旧进程占用
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8011',
        changeOrigin: true,
      },
    },
  },
})
