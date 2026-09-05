import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../../', import.meta.url))
const server = await createServer({
  configFile: false, root, envDir: false, envPrefix: 'LOCAL_GEO_SMOKE_UNUSED_',
  plugins: [vue()], publicDir: false,
  server: { host: '127.0.0.1', port: 5278, strictPort: true, fs: { allow: [root] } },
})
await server.listen()
console.log('Local mock-only GEO UI: http://127.0.0.1:5278/tests/local-geo-evidence/index.html')
