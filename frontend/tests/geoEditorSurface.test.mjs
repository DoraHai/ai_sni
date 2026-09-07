import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  getGeoPrototypeEditorSurface,
  getGeoPrototypePageSurface,
} from '../src/utils/geoEditorSurface.js'
import * as editorSurfaceModule from '../src/utils/geoEditorSurface.js'
import { canViewCockpit, COCKPIT_PERMISSION_KEYS } from '../src/utils/cockpitAccess.js'

const editorSource = readFileSync(
  fileURLToPath(new URL('../src/views/geo/GeoTaskEditorView.vue', import.meta.url)),
  'utf8',
)
const workspaceShellSource = readFileSync(
  fileURLToPath(new URL('../src/views/geo/GeoWorkspaceShell.vue', import.meta.url)),
  'utf8',
)

test('prototype editor exposes fact binding and prototype action sequence', () => {
  const surface = getGeoPrototypeEditorSurface()
  assert.equal(surface.showFactBinding, true)
  assert.equal(surface.showChannelVariants, true)
  assert.deepEqual(surface.actions, [
    'bind_facts',
    'generate_master',
    'save_master',
    'check',
    'suggest_brief',
    'save_brief',
    'generate_channels',
    'copy',
  ])
  assert.deepEqual(surface.briefFields, [
    'industry',
    'audience',
    'intent',
    'content_type',
    'cta',
    'banned_claims',
  ])
  assert.equal(surface.showProgressHint, false)
  assert.equal(surface.showBatchPush, false)
  assert.equal(surface.showImpact, false)
  assert.equal(surface.showAiReview, false)
})

test('prototype competitor and channel pages keep only their primary surfaces', () => {
  assert.deepEqual(getGeoPrototypePageSurface(), {
    showCompetitorAdvancedAnalysis: false,
    showChannelAutomationConsole: false,
    showChannelAccountConsole: true,
    showEvaluationRawMetrics: false,
    showCitationRawMetrics: false,
    showKnowledgeHealth: false,
    showLightweightOperations: false,
  })
})

test('channel drafts require a current GEO score at or above 60', () => {
  assert.equal(typeof editorSurfaceModule.getGeoChannelDraftGate, 'function')
  const gate = editorSurfaceModule.getGeoChannelDraftGate

  assert.deepEqual(gate({ hasMasterDraft: false, geoScore: null, scoreIsCurrent: false }), {
    allowed: false,
    reason: '请先生成母稿',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: null, scoreIsCurrent: false }), {
    allowed: false,
    reason: '请先完成 GEO 评分',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: 59, scoreIsCurrent: true }), {
    allowed: false,
    reason: 'GEO 评分需达到 60 分，当前 59 分',
  })
  assert.deepEqual(gate({ hasMasterDraft: true, geoScore: 60, scoreIsCurrent: true }), {
    allowed: true,
    reason: '',
  })
})

test('task editor keeps the complete editor-first interaction surface', () => {
  for (const marker of [
    'class="ed-shell"',
    "const leftTab = ref('brief')",
    'const showCheckDrawer = ref(false)',
    'const focusMode = ref(false)',
    "window.dispatchEvent(new CustomEvent('geo-editor-focus'",
    'saveArticleBody({ silent: true })',
    '可信材料',
    '标记已处理',
  ]) {
    assert.ok(editorSource.includes(marker), `missing editor interaction marker: ${marker}`)
  }
})

test('evidence fallback exposes an unresolved brand warning and recheck path', () => {
  for (const marker of [
    'const brandValidationWarning = computed',
    'const brandValidationRecheckPending = computed',
    'current_brand_validation',
    'generation_meta?.brand_validation',
    '品牌配置已更新，当前文章检查结果需要刷新',
    '现有检查仍使用品牌',
    '证据原文稿已保存，品牌标准仍待处理',
    '未通过前不会标记就绪',
    '按当前品牌重新检查',
    '@click="runCheck"',
  ]) {
    assert.ok(editorSource.includes(marker), `missing brand warning marker: ${marker}`)
  }
})

test('publishing checklist refresh is not confused with article readiness recheck', () => {
  const checklist = readFileSync(
    fileURLToPath(new URL('../src/components/GeoLaunchChecklist.vue', import.meta.url)),
    'utf8',
  )
  assert.ok(checklist.includes('刷新发布检查'))
  assert.ok(!checklist.includes('>刷新检查</'))
})

test('current-brand recheck remains visible for an existing master article without a warning payload', () => {
  assert.ok(editorSource.includes(`v-else-if="docTab === 'master' && task?.article"`))
  assert.ok(editorSource.includes('需要核对最新业务画像时，可重新运行当前母稿的品牌检查。'))
  assert.equal((editorSource.match(/>按当前品牌重新检查<\/el-button>/g) || []).length, 3)
})

test('GEO workspace links to the production acquisition cockpit', () => {
  assert.ok(workspaceShellSource.includes('href="/workspace/cockpit"'))
  assert.ok(workspaceShellSource.includes('G‑Snipers 获客工作台'))
  assert.ok(workspaceShellSource.includes('v-if="showCockpitShortcut"'))
  assert.ok(!workspaceShellSource.includes('href="/deal-sniper/portal"'))
  assert.ok(!workspaceShellSource.includes('返回平台门户'))
})

test('GEO cockpit shortcut follows the shared six-permission visibility contract', () => {
  assert.deepEqual(COCKPIT_PERMISSION_KEYS, [
    'monitor.dashboard',
    'optimize.keywords',
    'optimize.searchterms',
    'seo.content',
    'seo.site',
    'geo.content',
  ])

  assert.equal(canViewCockpit({ 'geo.assets': 'view' }), false)
  assert.equal(canViewCockpit({ 'geo.diagnosis': 'edit' }), false)
  assert.equal(canViewCockpit({ 'geo.content': 'view' }), true)
  for (const permission of COCKPIT_PERMISSION_KEYS.slice(0, -1)) {
    assert.equal(canViewCockpit({ [permission]: 'view' }), true, permission)
  }
  assert.equal(canViewCockpit({ 'monitor.dashboard': 'edit' }), true)
  assert.equal(canViewCockpit({ 'geo.content': 'none' }), false)
})
