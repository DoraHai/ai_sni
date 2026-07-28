import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

function sitesStaticWorker() {
  return {
    name: 'sites-static-worker',
    apply: 'build',
    async closeBundle() {
      const serverDir = resolve('dist-website/server')
      await mkdir(serverDir, { recursive: true })
      await copyFile(resolve('worker/index.js'), resolve(serverDir, 'index.js'))
    },
  }
}

export default defineConfig({
  root: resolve('website'),
  base: '/growth-sniper/',
  publicDir: resolve('public'),
  plugins: [vue(), sitesStaticWorker()],
  build: {
    outDir: resolve('dist-website'),
    emptyOutDir: true,
  },
})
