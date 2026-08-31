import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const editor = readFileSync(
  new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url),
  'utf8',
)
const api = readFileSync(new URL('../src/api/geoContent.js', import.meta.url), 'utf8')

test('GEO score action saves the draft then runs check and lint', () => {
  assert.match(editor, /async function runGeoScore\(\{ silent = false \} = \{\}\)/)
  assert.match(editor, /await saveArticleBody\(\{ silent: true \}\)/)
  assert.match(editor, /await checkGeoContentTask\(tenantId\.value, taskId\.value, false\)/)
  assert.match(editor, /await lintGeoContentTask\(tenantId\.value, taskId\.value\)/)
  assert.match(editor, /@click="runGeoScore"/)
})

test('optimization suggestions action persists the AI review and surfaces its failures', () => {
  assert.match(editor, /async function runAiReview\(\)/)
  assert.match(
    editor,
    /async function runAiReview\(\)[\s\S]*?await saveArticleBody\(\{ silent: true \}\)[\s\S]*?await aiReviewGeoContentTask[\s\S]*?scoredDraftSnapshot\.value = currentDraftSnapshot\(\)/,
  )
  assert.match(editor, /await aiReviewGeoContentTask\(tenantId\.value, taskId\.value, \{ persist: true \}\)/)
  assert.match(editor, /@click="runAiReview"/)
  assert.match(editor, /toastError\(e, '获取 AI 优化建议失败'\)/)
})

test('article editor API and UI do not expose draft history', () => {
  assert.doesNotMatch(api, /listGeoArticleVersions|restoreGeoArticleVersion|article-versions/)
  assert.doesNotMatch(editor, /articleVersions|recentArticleVersions|restoreArticleVersion/)
})

test('article optimization API preserves tenant, full, and section scopes', () => {
  assert.match(api, /export function optimizeGeoArticle\(taskId, body\)/)
  assert.match(api, /content-tasks\/\$\{taskId\}\/optimize/)
})

test('editor optimizes the full draft or a named Markdown section in place', () => {
  assert.match(editor, /const sectionHeading = ref\(''\)/)
  assert.match(editor, /async function runOptimize\(scope\)/)
  assert.match(editor, /await optimizeGeoArticle\(taskId\.value, body\)/)
  assert.match(editor, /checkResult\.value = res\.evaluation/)
  assert.match(editor, /已更新当前母稿/)
  assert.match(editor, /@click="runOptimize\('all'\)"/)
  assert.match(editor, /@click="runOptimize\('section'\)"/)
})
