import { readdir, readFile, stat } from 'node:fs/promises'
import { basename, resolve } from 'node:path'

const buildDir = resolve(process.argv[2] || 'dist')
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

await stat(resolve(buildDir, 'index.html'))
const files = await collectJavaScriptFiles(assetsDir)
if (!files.length) throw new Error(`No JavaScript assets found in ${assetsDir}`)

const requiredMarkers = [
  '/api/v1/oauth/baidu/authorize',
  '/api/v1/sem/assets/accounts',
  '/api/v1/manage/campaign-schedule',
  '/api/v1/manage/campaign-region',
  'G-Snipers 获客指挥台',
  '授权新客户账号',
  '已切换到新客户',
]
const forbiddenMarkers = [
  '图形验证码',
  '服务商接入准备中',
  '百度推广授权准备中',
]
const forbiddenMarkerExclusions = new Map([
  ['图形验证码', /^LoginView-[\w-]+\.js$/],
])

const foundRequired = new Set()
const foundForbidden = new Set()
for (const file of files) {
  const contents = await readFile(file, 'utf8')
  for (const marker of requiredMarkers) {
    if (contents.includes(marker)) foundRequired.add(marker)
  }
  for (const marker of forbiddenMarkers) {
    const exclusion = forbiddenMarkerExclusions.get(marker)
    if (contents.includes(marker) && !exclusion?.test(basename(file))) {
      foundForbidden.add(marker)
    }
  }
}

const missing = requiredMarkers.filter((marker) => !foundRequired.has(marker))
if (missing.length || foundForbidden.size) {
  const details = []
  if (missing.length) details.push(`missing: ${missing.join(', ')}`)
  if (foundForbidden.size) details.push(`obsolete: ${[...foundForbidden].join(', ')}`)
  throw new Error(`SEM build contract failed (${details.join('; ')})`)
}

console.log(`SEM build contract passed (${files.length} JavaScript assets checked)`)
