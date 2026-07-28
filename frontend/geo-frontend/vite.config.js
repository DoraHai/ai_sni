import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  root: resolve('../public/deal-sniper-prototype/geo'),
  base: '/deal-sniper/geo/',
  publicDir: false,
  server: {
    port: 5175,
  },
})
