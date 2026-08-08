import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig(({ command }) => ({
  root: resolve('auth'),
  base: command === 'build' ? '/auth-assets/' : '/',
  publicDir: false,
  plugins: [vue()],
  build: {
    outDir: resolve('dist-auth'),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
