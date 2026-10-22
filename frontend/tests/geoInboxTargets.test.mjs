import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { compile, computed, createSSRApp, ref } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { parse } from '@vue/compiler-sfc'
import { createInboxState } from '../src/components/geoDistributionInboxState.js'

const source = readFileSync(new URL('../src/components/GeoDistributionInbox.vue', import.meta.url), 'utf8')
const render = compile(parse(source).descriptor.template.content, { onError: error => { throw error } })
const targets = [
  { tenantId: 7, name: '合成客户甲', modules: ['geo'], scopes: [{ module: 'geo', id: 5, name: '品牌项目' }] },
  { tenantId: 8, name: '合成客户乙', modules: ['seo', 'geo'], scopes: [
    { module: 'seo', id: 5, name: '品牌网站' },
    { module: 'geo', id: 6, name: '项目乙' },
    { module: 'geo', id: 9, name: '项目丙' },
  ] },
  { tenantId: 9, name: '合成客户丙', modules: ['geo'], scopes: [] },
]

function fixture(items = [], availableTargets = targets) {
  const writes = []
  const props = { identity: 'synthetic', targets: availableTargets, owners: [], api: {
    receipts: async () => ({ items }), devices: async () => ({ items: [] }), count: async () => ({ count: items.length }),
    label: async (...args) => { writes.push(args) },
  } }
  const context = vm.createContext({ defineProps: () => props, ref, computed, watch: () => {}, onBeforeUnmount: () => {}, createInboxState })
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  vm.runInContext(`${script}\nglobalThis.panel = { model, state, targetId, moduleId, scopeId, articleId, publishedAccount, results, safeLink, targetFor, targetChanged, moduleChanged, scopesFor, articlesFor, assignmentText, label, update }`, context)
  context.panel.model.state.items = items
  return { panel: context.panel, writes, html: () => renderToString(createSSRApp({ setup: () => ({ ...props, ...context.panel }), render })) }
}
const assigned = (id, tenantId, module, scopeId) => ({ id, assignment: { tenantId, module, scopeId } })

test('active cards show customer, module and module-specific scope names outside collapsed details', async () => {
  const f = fixture([assigned('geo', 7, 'geo', 5), assigned('seo', 8, 'seo', 5)])
  const html = await f.html()
  assert.match(html, /class="assignment-target">合成客户甲 · GEO · 品牌项目<\/p>/)
  assert.match(html, /class="assignment-target">合成客户乙 · SEO · 品牌网站<\/p>/)
  assert.ok(html.indexOf('合成客户甲 · GEO · 品牌项目') < html.indexOf('<details>'))
  assert.doesNotMatch(html, /class="assignment-target scope-missing"/)
})

test('missing projects and websites get a visible warning class without mistaking missing names for missing scope', async () => {
  const f = fixture([assigned('geo', 7, 'geo', null), assigned('seo', 8, 'seo', null), assigned('unknown', 99, 'geo', 42)])
  const html = await f.html()
  assert.match(html, /class="assignment-target scope-missing">合成客户甲 · GEO · 项目待补/)
  assert.match(html, /class="assignment-target scope-missing">合成客户乙 · SEO · 网站待补/)
  assert.match(html, /class="assignment-target">客户 #99 · GEO · 项目 #42/)
  assert.match(source, /\.scope-missing\s*\{[^}]*color:\s*#9a3412;[^}]*background:\s*#fff7ed/)
})

test('fallbacks respect module boundaries, absent names and hidden assignments', async () => {
  const f = fixture([
    assigned('wrong-module', 8, 'geo', 5),
    assigned('no-name', 10, 'seo', 11),
    { id: 'hidden', assignment: { hidden: true, tenantId: 7, module: 'geo', scopeId: 5 } },
  ], [...targets, { tenantId: 10, modules: ['seo'], scopes: [{ module: 'seo', id: 11 }] }])
  const html = await f.html()
  assert.match(html, /合成客户乙 · GEO · 项目 #5/)
  assert.match(html, /客户 #10 · SEO · 网站 #11/)
  assert.match(html, /客户归属不可查看/)
  assert.doesNotMatch(html, /合成客户甲|品牌项目/)
  assert.equal(f.panel.assignmentText({ assignment: { hidden: true, tenantId: 7 } }), '')
})

test('a sole module and project are selected together and submitted without another scope interaction', async () => {
  const row = { id: 'pending', revision: 3 }, f = fixture([row]), p = f.panel
  p.targetId.value[row.id] = 7
  p.articleId.value[row.id] = 999
  p.targetChanged(row)
  assert.equal(p.moduleId.value[row.id], 'geo')
  assert.equal(p.scopeId.value[row.id], 5)
  assert.equal(p.articleId.value[row.id], '')
  await p.label(row)
  assert.equal(f.writes.length, 1)
  assert.deepEqual(f.writes[0].slice(0, 3), ['geo', 7, 'pending'])
  assert.deepEqual(f.writes[0][3], { expectedRevision: 3, targetTenant: 7, scopeId: 5 })
})

test('customer and module switches recalculate scope and clear stale article choices', () => {
  const row = { id: 'pending' }, p = fixture([row]).panel
  p.targetId.value[row.id] = 7; p.targetChanged(row)
  p.targetId.value[row.id] = 8; p.targetChanged(row)
  assert.equal(p.moduleId.value[row.id], '')
  assert.equal(p.scopeId.value[row.id], '')
  p.moduleId.value[row.id] = 'seo'; p.moduleChanged(row)
  assert.equal(p.scopeId.value[row.id], 5)
  p.articleId.value[row.id] = 123
  p.moduleId.value[row.id] = 'geo'; p.moduleChanged(row)
  assert.equal(p.scopeId.value[row.id], '')
  assert.equal(p.articleId.value[row.id], '')
  p.targetId.value[row.id] = 9; p.targetChanged(row)
  assert.equal(p.moduleId.value[row.id], 'geo')
  assert.equal(p.scopeId.value[row.id], '')
  p.targetId.value[row.id] = ''; p.targetChanged(row)
  assert.equal(p.moduleId.value[row.id], '')
  assert.equal(p.scopeId.value[row.id], '')
  assert.match(source, /v-model="moduleId\[row.id\]"[^>]*@change="moduleChanged\(row\)"/)
})

test('scope choices are row-local and rendering never fills an existing unscoped assignment', async () => {
  const row = { id: 'pending' }, active = assigned('active', 7, 'geo', null), f = fixture([row, active]), p = f.panel
  p.targetId.value[row.id] = 7; p.targetChanged(row)
  assert.equal(p.scopeId.value[row.id], 5)
  assert.equal(p.scopeId.value[active.id], undefined)
  await f.html()
  assert.equal(active.assignment.scopeId, null)
  assert.equal(f.writes.length, 0)
})
