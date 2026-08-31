import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { copyFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

function sitesStaticWorker() {
  return {
    name: 'sites-static-worker',
    apply: 'build',
    async closeBundle() {
      const serverDir = resolve('dist/server')
      await mkdir(serverDir, { recursive: true })
      await copyFile(resolve('worker/index.js'), resolve(serverDir, 'index.js'))
    },
  }
}

// 开发期 /api 反代到本地后端；生产构建后由 Nginx 同源反代，无需改代码
export default defineConfig({
  plugins: [
    vue(),
    Components({
      dirs: [],
      dts: false,
      resolvers: [ElementPlusResolver({ importStyle: false })],
    }),
    sitesStaticWorker(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
