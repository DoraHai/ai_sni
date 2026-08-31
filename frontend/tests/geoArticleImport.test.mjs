import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const frontendDir = resolve(import.meta.dirname, '..')
const readFrontend = (path) => readFileSync(resolve(frontendDir, path), 'utf8')

test('GEO article import route loads the dedicated import view', () => {
  const routerSource = readFrontend('src/router/index.js')
  assert.match(routerSource, /path: '\/geo\/import'/)
  assert.match(routerSource, /GeoArticleImportView\.vue/)
})

test('GEO article import API wrappers keep the server request contract', () => {
  const source = readFrontend('src/api/geoContent.js')
  assert.match(source, /export function previewGeoArticleImportFile\(tenantId, file\)/)
  assert.match(source, /content-imports\/preview-file/)
  assert.match(source, /params: \{ tenant_id: tenantId \}/)
  assert.match(source, /export function previewGeoArticleImportUrl\(tenantId, url\)/)
  assert.match(source, /content-imports\/preview-url/)
  assert.match(source, /\{ tenant_id: tenantId, url \}/)
  assert.match(source, /export function createGeoArticleImportTask\(payload\)/)
  assert.match(source, /content-imports\/create-task/)
})

test('GEO article import view supports preview, question selection, and task creation', () => {
  const source = readFrontend('src/views/geo/GeoArticleImportView.vue')
  for (const token of [
    '导入已有文章',
    '粘贴文章',
    '上传文档',
    'URL 导入',
    '关联目标问题',
    'previewGeoArticleImportFile',
    'previewGeoArticleImportUrl',
    'createGeoArticleImportTask',
  ]) {
    assert.ok(source.includes(token), `GeoArticleImportView.vue missing ${token}`)
  }
})
