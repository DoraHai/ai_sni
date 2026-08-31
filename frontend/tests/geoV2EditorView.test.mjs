import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const editor = readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url), 'utf8')

test('editor chrome keeps the drafting actions in the top bar', () => {
  for (const token of [
    'aria-label="在线编辑器"',
    '复制内容',
    'GEO评分',
    '保存',
    '生成渠道稿',
    '创作要求',
    '优化建议',
    '参考资料',
    '/geo/ai-settings',
  ]) {
    assert.ok(editor.includes(token), `GeoTaskEditorView.vue missing ${token}`)
  }
})

test('editor moves publishing into more actions and keeps the routing handlers', () => {
  assert.match(editor, /function goDistribution\(mode\)/)
  assert.match(editor, /<el-dropdown-item[^>]*command="publish-manual">手动发布<\/el-dropdown-item>/)
  assert.match(editor, /<el-dropdown-item[^>]*command="publish-auto">自动发布<\/el-dropdown-item>/)
  assert.match(editor, /query: \{ mode \}/)
})

test('editor opens channel selection before generating channel drafts', () => {
  assert.match(editor, /@click="openLeftTab\('channels'\)"\s*>\s*选择渠道稿\s*<\/el-button>/)
  assert.match(editor, /leftTab === 'channels'/)
  assert.match(editor, />\s*渠道稿\s*<\/button>/)
  assert.match(editor, />\s*生成所选渠道稿\s*<\/el-button>/)
  assert.match(editor, /\.ed-tabs \{[\s\S]*grid-template-columns: repeat\(auto-fit, minmax\(58px, 1fr\)\)/)
})

test('editor shows each configured channel type only once in the channel picker', () => {
  const picker = editor.slice(
    editor.indexOf('const enabledChannelOptions'),
    editor.indexOf('function toggleChannelPick'),
  )
  assert.ok(picker.startsWith('const enabledChannelOptions'), 'channel picker options are defined')
  assert.match(picker, /const seen = new Set\(\)/)
  assert.match(picker, /!seen\.has\(c\.key\) && \(seen\.add\(c\.key\) \|\| true\)/)
})

test('editor uses a wrap-safe hierarchy for suggestion actions', () => {
  assert.match(editor, /class="ed-suggestion-primary"/)
  assert.match(editor, /class="[^\"]*ed-suggestion-secondary[^\"]*"/)
  assert.match(editor, /class="[^\"]*ed-section-optimize-action[^\"]*"/)
  assert.match(editor, /\.ed-suggestion-actions \{[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(editor, /\.ed-suggestion-actions button \{[\s\S]*white-space: nowrap/)
})

test('editor scores, reviews, and optimizes only the current draft', () => {
  assert.match(editor, /async function runGeoScore\(\{ silent = false \} = \{\}\)/)
  assert.doesNotMatch(editor, /await runGeoScore\(\{ silent: true \}\)/)
  assert.match(editor, /getGeoChannelDraftGate/)
  assert.match(editor, /if \(!channelDraftGate\.value\.allowed\)/)
  assert.match(editor, /await checkGeoContentTask\(tenantId\.value, taskId\.value, false\)/)
  assert.match(editor, /await lintGeoContentTask\(tenantId\.value, taskId\.value\)/)
  assert.match(editor, /await aiReviewGeoContentTask\(tenantId\.value, taskId\.value, \{ persist: true \}\)/)
  assert.doesNotMatch(editor, /listGeoArticleVersions|restoreGeoArticleVersion/)
  assert.doesNotMatch(editor, /母稿版本历史|回滚/)
  assert.match(editor, /await optimizeGeoArticle\(taskId\.value, body\)/)
})

test('editing title or body immediately invalidates derived editor state', () => {
  assert.match(editor, /\(\) => \[article\.title, article\.body_markdown\]/)
  assert.match(editor, /scoredDraftSnapshot\.value = ''/)
  assert.match(editor, /checkResult\.value = null/)
  assert.match(editor, /docTab\.value = 'master'/)
})
