import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')
const functions = source.slice(source.indexOf('export function previewGeoArticleImportFile'),
  source.indexOf('/** hard=false archive')).replaceAll('export function', 'function')

test('all import API calls send selected tenant in query and retain body/form', () => {
  const calls = []
  const ctx = vm.createContext({ client: { post: (...args) => calls.push(args) }, FormData })
  vm.runInContext(functions, ctx)
  const file = new Blob(['fixture article'])
  ctx.previewGeoArticleImportFile(10, file)
  ctx.previewGeoArticleImportUrl(10, 'https://example.test/article')
  const payload = { tenant_id: 10, source_type: 'paste', body_markdown: 'fixture article' }
  ctx.createGeoArticleImportTask(payload)
  for (const [, , options] of calls) assert.equal(options.params.tenant_id, 10)
  assert.equal(calls[0][1].get('file').size, file.size)
  assert.equal(calls[1][1].url, 'https://example.test/article')
  assert.equal(calls[1][1].tenant_id, 10)
  assert.equal(calls[2][1], payload)
})
