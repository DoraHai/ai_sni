import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  root: resolve(frontendRoot, 'seo'),
  envDir: frontendRoot,
  base: '/seo/',
  publicDir: false,
  plugins: [vue()],
  build: {
    outDir: resolve(frontendRoot, 'dist-seo'),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/seo-entry-[hash].js',
        chunkFileNames: 'assets/seo-[name]-[hash].js',
        assetFileNames: 'assets/seo-[name]-[hash][extname]',
      },
    },
  },
  server: {
    port: 5176,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
