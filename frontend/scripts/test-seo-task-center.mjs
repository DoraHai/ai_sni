import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'

const source = await readFile(new URL('../src/views/seo/SeoTaskCenterView.vue', import.meta.url), 'utf8')
const code = compileScript(parse(source).descriptor, { id: 'task-center-test', genDefaultAs: 'component' }).content.replace(/^import .* from .*$/gm, '')
const reads = [], recoveries = [], retries = [], audits = [], confirmations = [], detailReads = [], navigations = [], queueReads = []
function deferred(args) { let resolve, reject; const promise = new Promise((r,j) => { resolve=r; reject=j }); return { args, promise, resolve, reject } }
const tenant = Vue.ref(1), site = Vue.ref(10), session = Vue.reactive({ user: { id: 7 } })
const bindings = { computed:Vue.computed, onMounted:Vue.onMounted, onUnmounted:Vue.onUnmounted,
  reactive:Vue.reactive, ref:Vue.ref, watch:Vue.watch, currentTenantId: tenant, currentSeoSiteId: site, session,
  useRouter: () => ({ push(value) { navigations.push(value) } }),
  ElMessage: { success(){},warning(){},error(){} },
  ElMessageBox: { confirm: (...args) => { const d=deferred(args);confirmations.push(d);return d.promise } },
  fetchSeoTaskCenter: args => { const d=deferred(args);reads.push(d);return d.promise },
  fetchSeoSitePageDetail: args => { const d=deferred(args);detailReads.push(d);return d.promise },
  fetchSeoCustomerVerificationQueue: args => (queueReads.push(args), args.tenant_id === 4)
    ? Promise.reject(new Error('queue unavailable'))
    : Promise.resolve({ items: [], total: 0, summary: {} }),
  retrySeoImageVerification: () => Promise.resolve({}),
  auditSeoSitePage: args => { const d=deferred(args);audits.push(d);return d.promise },
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
  const pageRecheck=state.recheckPage({id:'page_recheck:31',kind:'page_recheck',state:'pending_system_check',can_recheck:true,
    recheck_action:{method:'POST',page_id:31,tenant_id:2,site_id:20}})
  confirmations[0].resolve();await Vue.nextTick()
  assert.deepEqual(audits[0].args,{pageId:31,tenantId:2,siteId:20})
  audits[0].resolve({status:'verified'});await Vue.nextTick();await Vue.nextTick()
  reads.at(-1).resolve(response('after-page-recheck'));await pageRecheck
  assert.equal(state.data.items[0].id,'after-page-recheck')
  await state.recheckPage({id:'page_recheck:32',kind:'page_recheck',state:'pending_system_check',can_recheck:true,
    recheck_action:{method:'POST',page_id:32,tenant_id:99,site_id:20}})
  assert.equal(audits.length,1)
  const recovering=state.recover({id:'op-1',has_result:true})
  session.user={id:8};await Vue.nextTick()
  recoveries[0].resolve({title:'private previous-user result'});await recovering
  assert.equal(state.resultText,'');assert.equal(state.resultOpen,false)
  const pendingRetry=state.retry({id:'7',source:'automation',kind:'ranking',can_retry:true,retry_site_id:20})
  tenant.value=3;await Vue.nextTick()
  confirmations[1].resolve();await pendingRetry
  assert.equal(retries.length,0)
  await state.retry({id:'8',can_retry:false})
  assert.equal(confirmations.length,2)
  tenant.value=4;await Vue.nextTick()
  reads.at(-1).resolve(response('task-history-survives'));await Vue.nextTick();await Vue.nextTick()
  assert.equal(state.data.items[0].id,'task-history-survives')
  assert.equal(state.verificationError,'queue unavailable')
  const attempt={id:42,action:'manual_complete',status:'succeeded',created_by:17,started_at:'2026-09-11T07:30:00Z'}
  assert.match(state.publicationAttemptLabel(attempt),/\u4eba\u5de5\u56de\u586b #42 · 成功 · 操作人 #17/)
  assert.equal(state.publicationAttempt({kind:'publication_url',evidence:{latest_attempt:attempt}}),attempt)
  assert.equal(state.publicationAttempt({kind:'page_recheck',evidence:{latest_attempt:attempt}}),null)
  tenant.value=2;await Vue.nextTick()
  const detailRow={id:'page_recheck:31',source_id:31,site_id:20,kind:'page_recheck',state:'pending_customer_action',action_url:'/seo/site?site_id=20'}
  const auditCount=audits.length, retryCount=retries.length
  const opening=state.openDetails(detailRow)
  assert.equal(state.detailOpen,true)
  assert.deepEqual(detailReads.at(-1).args,{pageId:31,tenantId:2})
  detailReads.at(-1).resolve({page:{id:31,site_id:20,url:'https://example.cn/a',title_suggestion:'新标题'},issue_details:[{code:'title_missing',label:'标题',guidance:'填写页面标题'}]})
  await opening
  assert.equal(state.pageDetail.page.title_suggestion,'新标题')
  assert.equal(state.detailLinks[0].url,'https://example.cn/a')
  assert.match(state.steps.join(' '),/优化记录.*已实施，待复检/)
  assert.equal(audits.length,auditCount);assert.equal(retries.length,retryCount)
  assert.equal(state.processingUrl(detailRow),'/seo/site?site_id=20&page_id=31')
  assert.equal(state.processingUrl({...detailRow,site_id:99}),'')
  assert.equal(state.processingUrl({...detailRow,action_url:'https://evil.invalid/seo/site'}),'')
  assert.equal(state.publicUrl('javascript:alert(1)'),'')
  assert.equal(state.publicUrl('https://user:secret@example.cn/'),'')
  const stale=state.openDetails(detailRow)
  state.detailOpen=false;await Vue.nextTick()
  detailReads.at(-1).resolve({page:{id:31,site_id:20,title:'closed secret'}});await stale
  assert.equal(state.pageDetail,null)
  const wrongSite=state.openDetails(detailRow)
  detailReads.at(-1).resolve({page:{id:31,site_id:99,title:'wrong site'}});await wrongSite
  assert.equal(state.pageDetail,null);assert.match(state.detailError,/页面范围已变化/)
  const failed=state.openDetails(detailRow);detailReads.at(-1).reject(new Error('无法读取页面'));await failed
  assert.equal(state.detailError,'无法读取页面')
  const switched=state.openDetails(detailRow);tenant.value=3;await Vue.nextTick()
  detailReads.at(-1).resolve({page:{id:31,site_id:20,title:'old tenant'}});await switched
  assert.equal(state.detailOpen,false);assert.equal(state.pageDetail,null)
  tenant.value=2;await Vue.nextTick()
  state.goToProcessing(detailRow);assert.equal(navigations.at(-1),'/seo/site?site_id=20&page_id=31')
  state.queueFilters.kind='page_recheck';state.queueFilters.state='pending_customer_action';await Vue.nextTick()
  assert.equal(queueReads.at(-1).kind,'page_recheck');assert.equal(queueReads.at(-1).state,'pending_customer_action')
  state.queueFilters.page=2;await Vue.nextTick();assert.equal(queueReads.at(-1).page,2)
  await state.openDetails({source:'automation',id:'run-1',kind:'ranking',detail:'抓取失败'})
  assert.equal(state.detailRow.detail,'抓取失败');assert.equal(state.steps.length,0)
  assert.ok(!source.includes('v-html'))
  console.log('Task center checks passed: detail guidance, scoped page reads, closed/stale/error responses, safe links, deep links, queue filters/pagination, page recheck and AI recovery')
} finally { app.unmount() }
