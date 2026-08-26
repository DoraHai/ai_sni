import { readFile, readdir, stat } from 'node:fs/promises'
import { resolve, relative } from 'node:path'

const root = resolve(process.argv[2] || 'dist-seo')

async function filesUnder(directory) {
  const found = []
  for (const name of await readdir(directory)) {
    const path = resolve(directory, name)
    if ((await stat(path)).isDirectory()) found.push(...await filesUnder(path))
    else found.push(relative(root, path).replaceAll('\\', '/'))
  }
  return found
}

const index = await readFile(resolve(root, 'index.html'), 'utf8')
if (!index.includes('/seo/assets/seo-entry-')) {
  throw new Error('SEO index does not reference the isolated /seo/ entry asset')
}

const manifest = JSON.parse(await readFile(resolve(root, '.vite/manifest.json'), 'utf8'))
const manifestText = JSON.stringify(manifest)
for (const forbidden of [
  'src/views/geo/',
  'src/views/monitor/',
  'src/views/diagnosis/',
  'src/views/LoginView.vue',
]) {
  if (manifestText.includes(forbidden)) {
    throw new Error(`Non-SEO view leaked into SEO build: ${forbidden}`)
  }
}

const files = await filesUnder(root)
for (const file of files) {
  if (file === 'index.html' || file === '.vite/manifest.json') continue
  if (!file.startsWith('assets/seo-')) {
    throw new Error(`Unexpected non-SEO build asset: ${file}`)
  }
}

console.log(`SEO build verified: ${files.length} files`)
