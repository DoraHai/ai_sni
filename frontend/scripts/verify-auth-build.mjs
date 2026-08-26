import { readdir, readFile, stat } from 'node:fs/promises'
import { resolve } from 'node:path'

const buildDir = resolve(process.argv[2] || 'dist-auth')
const assetsDir = resolve(buildDir, 'assets')

async function collectJavaScriptFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) files.push(...await collectJavaScriptFiles(path))
    else if (entry.isFile() && entry.name.endsWith('.js')) files.push(path)
  }
  return files
}

const indexPath = resolve(buildDir, 'index.html')
await stat(indexPath)
const indexHtml = await readFile(indexPath, 'utf8')
if (!indexHtml.includes('/auth-assets/')) {
  throw new Error('Auth build contract failed (assets are not isolated under /auth-assets/)')
}

const files = await collectJavaScriptFiles(assetsDir)
if (!files.length) throw new Error(`No JavaScript assets found in ${assetsDir}`)

const requiredMarkers = [
  'AI 获客指挥台',
  '/api/v1/auth/login',
  '图形验证码',
  'G-Snipers',
]

const found = new Set()
for (const file of files) {
  const contents = await readFile(file, 'utf8')
  for (const marker of requiredMarkers) {
    if (contents.includes(marker)) found.add(marker)
  }
}

const missing = requiredMarkers.filter((marker) => !found.has(marker))
if (missing.length) {
  throw new Error(`Auth build contract failed (missing: ${missing.join(', ')})`)
}

console.log(`Auth build contract passed (${files.length} JavaScript assets checked)`)
