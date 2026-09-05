import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'

const source = await readFile(new URL('../src/views/seo/SeoTaskCenterView.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'task-center-test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const reads = [], recoveries = [], retries = [], confirmations = []
function deferred(args) { let resolve, reject; const promise = new Promise((r,j) => { resolve=r; reject=j }); return { args, promise, resolve, reject } }
const tenant = Vue.ref(1), site = Vue.ref(10), session = Vue.reactive({ user: { id: 7 } })
const bindings = { computed:Vue.computed, onMounted:Vue.onMounted, onUnmounted:Vue.onUnmounted,
  reactive:Vue.reactive, ref:Vue.ref, watch:Vue.watch, currentTenantId: tenant, currentSeoSiteId: site, session,
  useRouter: () => ({ push() {} }),
  ElMessage: { success(){},warning(){},error(){} },
  ElMessageBox: { confirm: (...args) => { const d=deferred(args);confirmations.push(d);return d.promise } },
  fetchSeoTaskCenter: args => { const d=deferred(args);reads.push(d);return d.promise },
  recoverSeoAiOperation: (...args) => { const d=deferred(args);recoveries.push(d);return d.promise },
  retrySeoTask: (...args) => { retries.push(args); return Promise.resolve({}) },
}
const Component = new Function('b', `const {${Object.keys(bindings).join(',')}}=b; ${code}; return component`)(bindings)
Component.render = () => null
const renderer = Vue.createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  setText(){},setElementText(){},patchProp(){},insert(){},remove(){},parentNode:()=>null,nextSibling:()=>null })
const app = renderer.createApp(Component)
const vm = app.mount({})
const state = vm.$.setupState
const response = label => ({items:[{id:label}],total:1,summary:{},schedules:[]})
try {
  assert.equal(reads.length,1)
  tenant.value=2;site.value=20;await Vue.nextTick()
  reads.at(-1).resolve(response('new-tenant'));await Vue.nextTick();await Vue.nextTick()
  reads[0].resolve(response('stale-tenant'));await Vue.nextTick();await Vue.nextTick()
  assert.equal(state.data.items[0].id,'new-tenant')
  const recovering=state.recover({id:'op-1',has_result:true})
  session.user={id:8};await Vue.nextTick()
  recoveries[0].resolve({title:'private previous-user result'});await recovering
  assert.equal(state.resultText,'');assert.equal(state.resultOpen,false)
  const pendingRetry=state.retry({id:'7',source:'automation',kind:'ranking',can_retry:true,retry_site_id:20})
  tenant.value=3;await Vue.nextTick()
  confirmations[0].resolve();await pendingRetry
  assert.equal(retries.length,0)
  await state.retry({id:'8',can_retry:false})
  assert.equal(confirmations.length,1)
  assert.ok(!source.includes('v-html'))
  console.log('Task center checks passed: stale tenant response, user-private recovery, scope switch before confirmation, read-only retry')
} finally { app.unmount() }
