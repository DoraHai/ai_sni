import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve(import.meta.dirname),
  base: '/deal-sniper/geo/',
  publicDir: false,
  plugins: [vue()],
  resolve: {
    dedupe: ['vue', 'vue-router', 'element-plus'],
  },
  build: {
    outDir: resolve(import.meta.dirname, 'dist'),
    emptyOutDir: true,
  },
  server: {
    port: 5175,
    fs: {
      allow: [resolve(import.meta.dirname, '..')],
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8011',
        changeOrigin: true,
      },
      '/health/geo': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8011',
        changeOrigin: true,
      },
    },
  },
})
