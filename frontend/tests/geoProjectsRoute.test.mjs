import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { parse as parseJs } from '@babel/parser'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-dom'
import * as Vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createRouter, createMemoryHistory } from 'vue-router'
import { GEO_WORKBENCH_NAV, GEO_WORKBENCH_START } from '../src/utils/geoPrototypeNavigation.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const routerSource = read('../src/router/index.js')
const projects = parseSfc(read('../src/views/geo/GeoProjectsView.vue')).descriptor
const execution = parseSfc(read('../src/components/GeoProjectExecution.vue')).descriptor
const sessionSource = read('../src/store/session.js')
const sessionAst = parseJs(sessionSource, { sourceType: 'module' })
const sessionObject = sessionAst.program.body.find((n) => n.type === 'ExportNamedDeclaration' && n.declaration?.declarations?.[0]?.id.name === 'session').declaration.declarations[0].init
const permissionMethod = (name, state) => {
  const method = sessionObject.properties.find((n) => n.key?.name === name)
  return vm.runInNewContext(`({ ${sessionSource.slice(method.start, method.end)} }).${name}`, { state })
}

function makeSession(permissions = {}, user = { id: 99, tenant_id: null }) {
  const state = { user: user && { ...user, permissions } }
  return { user: state.user, isLoggedIn: !!user?.id,
    canView: permissionMethod('canView', state), canEdit: permissionMethod('canEdit', state) }
}

function mainRouter(session) {
  // Run the actual route records and registered beforeEach; only browser history,
  // session and login navigation are injected. No Vite, .env or API requests.
  const ast = parseJs(routerSource, { sourceType: 'module' })
  let source = routerSource
  for (const node of [...ast.program.body].reverse()) {
    if (node.type === 'ImportDeclaration' || node.type === 'ExportDefaultDeclaration') {
      source = source.slice(0, node.start) + source.slice(node.end)
    }
  }
  source = source.replaceAll('import.meta.env', 'testEnv')
  let guard
  const redirects = []
  const context = vm.createContext({ session, GEO_WORKBENCH_START,
    testEnv: { DEV: false, VITE_API_KEY: '' }, createWebHistory: createMemoryHistory,
    createRouter: (options) => {
      const router = createRouter(options)
      const register = router.beforeEach.bind(router)
      router.beforeEach = (callback) => { guard = callback; return register(callback) }
      return router
    },
    loginUrl: (path) => `/login?redirect=${encodeURIComponent(path)}`,
    window: { location: { assign: (url) => redirects.push(url) } }, document: {} })
  const router = vm.runInContext(source + '\nrouter', context)
  return { router, redirects, visit: (path) => guard(router.resolve(path)) }
}

test('main app menu resolves to existing projects view with geo.assets overriding geo.content', () => {
  const session = makeSession({ 'geo.assets': 'view' })
  const { router, visit } = mainRouter(session)
  const menu = GEO_WORKBENCH_NAV.find((g) => g.label === '设置').children.find((x) => x.path === '/geo/projects')
  assert.equal(menu.key, 'geo.assets')
  assert.equal(session.canView(menu.key), true)
  const route = router.resolve(menu.path)
  assert.equal(route.matched.length, 2)
  assert.equal(route.matched[0].path, '/geo')
  assert.match(route.matched[1].components.default.toString(), /import\('\.\.\/views\/geo\/GeoProjectsView\.vue'\)/)
  assert.equal(route.meta.title, '项目管理')
  assert.equal(route.meta.perm, 'geo.assets')
  assert.equal(route.meta.public, undefined)
  assert.equal(visit(menu.path), undefined)
  assert.match(projects.scriptSetup.content, /import GeoProjectExecution from '..\/..\/components\/GeoProjectExecution.vue'/)
  assert.match(read('../src/views/geo/GeoWorkspaceShell.vue'), /children: group.children.filter\(\(item\) => session.canView\(item.key\)\)/)
})

test('anonymous direct navigation aborts and goes to login with return path', () => {
  const { visit, redirects } = mainRouter(makeSession({}, null))
  assert.equal(visit('/geo/projects?tenant_id=17'), false)
  assert.deepEqual(redirects, ['/login?redirect=%2Fgeo%2Fprojects%3Ftenant_id%3D17'])
})

test('content editor without geo.assets is redirected by existing guard', () => {
  const { visit } = mainRouter(makeSession({ 'geo.content': 'edit', 'assistant': 'view' }))
  assert.equal(visit('/geo/projects').path, '/assistant')
})

test('missing geo.assets aborts even when the user has no fallback menu', () => {
  for (const permissions of [{}, { 'geo.content': 'edit' }, { 'geo.assets': 'none' }]) {
    const { visit } = mainRouter(makeSession(permissions))
    assert.equal(visit('/geo/projects'), false)
  }
})

const executionAst = parseJs(execution.scriptSetup.content, { sourceType: 'module' })
const assignNode = executionAst.program.body.flatMap((n) => n.declarations || []).find((n) => n.id.name === 'canAssignAdvisor').init
const render = new Function('Vue', compile(execution.template.content, { mode: 'function', prefixIdentifiers: true }).code)(Vue)
async function renderPlan(session) {
  const canAssignAdvisor = vm.runInNewContext(execution.scriptSetup.content.slice(assignNode.start, assignNode.end), { session })
  const state = { session, canAssignAdvisor, error: '', loading: false, saving: false,
    data: { service_plan: { revision: 3, enabled: false, status: 'paused', prompt_ids: [], interval_days: 7 },
      preparation: { status: 'not_ready', project_prompt_count: 0, reason_codes: [] }, items: [], prompts: [] },
    form: { enabled: false, status: 'paused', prompt_ids: [], interval_days: 7, advisor_user_id: null },
    candidates: [], load() {}, save() { throw new Error('No save may run in this read-only render test') } }
  const app = Vue.createSSRApp({ render, setup: () => state })
  app.config.warnHandler = (message) => { throw new Error(message) }
  app.component('GeoTicketExecution', { render: () => null })
  // Preserve slots and control tags so assertions cover the real form template.
  for (const name of ['el-alert', 'el-button', 'el-empty', 'el-form', 'el-form-item', 'el-switch', 'el-select', 'el-option', 'el-input-number']) {
    app.component(name, { setup: (_, { slots }) => () => Vue.h(name, {}, slots.default?.()) })
  }
  return renderToString(app)
}

const edits = { 'settings.accounts': 'edit', 'geo.assets': 'edit', 'geo.content': 'edit' }
test('platform configuration admin sees existing plan form, switch and save button', async () => {
  const html = await renderPlan(makeSession(edits))
  assert.match(html, /<el-form[ >]/)
  assert.match(html, /<el-switch[ >]/)
  assert.match(html, /保存服务计划/)
})

test('ordinary advisors with both GEO edits see plan status but no plan write controls', async () => {
  for (const user of [{ id: 7, tenant_id: 17 }, { id: 7, tenant_id: null }]) {
    const html = await renderPlan(makeSession({ 'geo.assets': 'edit', 'geo.content': 'edit' }, user))
    assert.match(html, /已保存版本 3/)
    assert.match(html, /周期待办尚未开启/)
    assert.doesNotMatch(html, /保存服务计划|<el-form[ >]|<el-switch[ >]/)
  }
  const html = await renderPlan(makeSession(edits, { id: 7, tenant_id: 17 }))
  assert.doesNotMatch(html, /保存服务计划|<el-switch[ >]/)
})

test('plan controls require login and all three edit permissions', async () => {
  for (const key of Object.keys(edits)) {
    const html = await renderPlan(makeSession({ ...edits, [key]: 'view' }))
    assert.doesNotMatch(html, /保存服务计划|<el-form[ >]|<el-switch[ >]/)
  }
  assert.doesNotMatch(await renderPlan(makeSession(edits, null)), /保存服务计划|<el-switch[ >]/)
})

test('projects page keeps plan-and-todo visibility under geo.content view permission', () => {
  assert.match(projects.template.content, /<el-table-column v-if="session.canView\('geo.content'\)"[^>]*>[\s\S]*?计划与待办[\s\S]*?<\/el-table-column>/)
  assert.match(projects.template.content, /<GeoProjectExecution v-if="executionProject" :project-id="executionProject.id" :tenant-id="tenantId"/)
})
