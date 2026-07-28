import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import { basename, dirname, resolve } from 'node:path'

const unitRoot = resolve(import.meta.dirname, '..')
const frontendRoot = resolve(unitRoot, '..')
const sourceDir = resolve(frontendRoot, 'public/deal-sniper-prototype/geo')
const outputDir = resolve(unitRoot, 'dist')
const requiredPages = [
  'dashboard.html',
  'visibility.html',
  'prompts.html',
  'competitors.html',
  'evaluation.html',
  'sources.html',
  'articles.html',
  'editor.html',
  'media.html',
  'channels.html',
  'engines.html',
]

async function exists(path) {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = resolve(dir, entry.name)
    if (entry.isDirectory()) files.push(...await walk(path))
    else files.push(path)
  }
  return files
}

for (const page of requiredPages) {
  if (!await exists(resolve(sourceDir, page))) {
    throw new Error(`GEO build is missing required page: ${page}`)
  }
}

const sourceFiles = await walk(sourceDir)
const missingReferences = []
for (const file of sourceFiles.filter((path) => path.endsWith('.html'))) {
  const html = await readFile(file, 'utf8')
  const refs = [...html.matchAll(/(?:src|href)=["']([^"'#]+)["']/g)].map((match) => match[1])
  for (const ref of refs) {
    if (/^(?:https?:|mailto:|tel:|javascript:|\/)/.test(ref)) continue
    const target = resolve(dirname(file), ref.split('?')[0])
    if (!await exists(target)) missingReferences.push(`${basename(file)} -> ${ref}`)
  }
}
if (missingReferences.length) {
  throw new Error(`Broken GEO references:\n${missingReferences.join('\n')}`)
}

for (const file of sourceFiles.filter((path) => path.endsWith('.js'))) {
  execFileSync(process.execPath, ['--check', file], { stdio: 'inherit' })
}

await rm(outputDir, { recursive: true, force: true })
await mkdir(outputDir, { recursive: true })
await cp(sourceDir, outputDir, { recursive: true })

let sourceRevision = 'working-tree'
try {
  sourceRevision = execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], {
    cwd: frontendRoot,
    encoding: 'utf8',
  }).trim()
} catch {
  // A source archive without Git metadata is still deployable.
}

await writeFile(
  resolve(outputDir, 'release.json'),
  `${JSON.stringify({
    unit: 'geo-frontend',
    source_revision: sourceRevision,
    pages: requiredPages,
  }, null, 2)}\n`,
)

console.log(`GEO build ready: ${requiredPages.length} pages, ${sourceFiles.length} files`)
