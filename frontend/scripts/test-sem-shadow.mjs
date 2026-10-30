import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { shadowRoutes } from '../src/router/shadowRoutes.js'
import { createShadowApi, validateScreenshots, submissionPayload, shadowError, LAST_GRANT_NOTICE, REVOKE_CHECK_NOTICE, changeAndReloadGrants } from '../src/views/onboarding/shadowPlanning.js'

const storage = () => { const m = new Map(); return { getItem: k => m.get(k) || null, setItem: (k,v) => m.set(k,v), removeItem: k => m.delete(k) } }
globalThis.localStorage = storage(); globalThis.sessionStorage = storage()
const requests = []
const api = createShadowApi({ get: (...a) => { requests.push(['GET', ...a]); return Promise.resolve(new Blob(['xlsx'])) }, post: (...a) => { requests.push(['POST', ...a]); return Promise.resolve({ revision: 1 }) } })
await api.list(101,201)
assert.deepEqual(requests[0], ['GET','/api/v1/sem/phase1a/shadow/accounts/201/plans',{params:{tenant_id:101,offset:0,limit:50}}])
await api.excel('test-plan')
assert.equal(requests.at(-1)[2].responseType,'blob')
const file = new File(['image'], 'test.png', { type:'image/png' })
await api.submit({ tenant_id:101 }, [file])
assert.equal(requests.at(-1)[2].get('metadata'),JSON.stringify({tenant_id:101}))
assert.equal(requests.at(-1)[2].getAll('screenshots').length,1)
assert.throws(() => validateScreenshots(Array(11).fill(file)), /10/)
assert.throws(() => validateScreenshots([{type:'image/gif',size:1}]), /PNG/)
assert.throws(() => validateScreenshots([{type:'image/png',size:10*1024**2+1}]), /10MiB/)
assert.throws(() => validateScreenshots(Array(4).fill({type:'image/png',size:8*1024**2})), /30MiB/)
assert.equal(validateScreenshots(Array(3).fill({type:'image/png',size:10*1024**2})).length,3)
assert.match(shadowError({status:403}),/权限/)
assert.match(shadowError({status:503,code:'ATTACHMENT_STORAGE_UNAVAILABLE'}),/未成功/)
assert.match(shadowError({status:409}),/失效/)
assert.equal(shadowError({status:409,code:'LAST_GRANT_PROTECTED'}),LAST_GRANT_NOTICE)
assert.match(shadowError({code:'GRANT_ACCOUNT_NOT_INITIALIZED'}),/首次授权/)
const form = { product_line_id:'product',landing_page_id:'page',expected_revision:0,case_type:'new_account',account_ready:true,
  starts_at:'2026-10-30T12:00', ends_at:'', no_deadline_explicit:true, regions:'上海\n北京', days:[1],start_hour:9,end_hour:18,
  negative_keywords:'',budget_cents:100,bid_cap_cents:10 }
assert.equal(submissionPayload(form,101,201).starts_at,'2026-10-30T04:00:00.000Z')
assert.deepEqual(submissionPayload(form,101,201).regions,['上海','北京'])
assert.throws(() => submissionPayload({...form,account_ready:false},101,201),/账户/)
const committed = await changeAndReloadGrants(async () => ({changed:true}), async () => {throw new Error('offline')}, () => true)
assert.equal(committed.refreshFailed,true); assert.equal(committed.result.changed,true); assert.equal(committed.rows,null)
await assert.rejects(() => changeAndReloadGrants(async () => {throw new Error('denied')}, async () => assert.fail('must not reload'), () => true), /denied/)
assert.equal(await changeAndReloadGrants(async () => ({changed:true}), async () => assert.fail('stale context must not reload'), () => false),null)

// A writable advisor plus a read-only customer still cannot lose its advisor.
// Six-field rows do not prove current writability; both protections remain server decisions.
for (const code of ['LAST_GRANT_PROTECTED', 'LAST_WRITABLE_ADVISOR_PROTECTED']) {
  const sent = []
  const protectedApi = createShadowApi({ post: async (...args) => { sent.push(args); throw {status:409,code} } })
  await assert.rejects(() => changeAndReloadGrants(
    () => protectedApi.revoke(201,{tenant_id:101,user_id:1,advisor_grant_id:11}),
    () => assert.fail('a rejected revoke must not reload or announce success'), () => true),
    error => shadowError(error) === LAST_GRANT_NOTICE)
  assert.deepEqual(sent,[['/api/v1/sem/phase1a/account-grants/accounts/201/revoke',
    {tenant_id:101,user_id:1,advisor_grant_id:11}]])
}

// Compile and SSR-render the real Vue component with existing dependencies.
// No mounted lifecycle/network calls; routes use a memory history.
const server = await createServer({ server:{middlewareMode:true}, appType:'custom', configFile:false,
  plugins:[(await import('@vitejs/plugin-vue')).default()], logLevel:'error' })
try {
  const component = (await server.ssrLoadModule('/src/views/onboarding/ShadowPlanningView.vue')).default
  const { session } = await server.ssrLoadModule('/src/store/session.js')
  for (const role of ['advisor','customer','admin']) {
    session.setAuth('synthetic-test-session',{id:1,is_advisor:role==='advisor',tenant_id:role==='admin'?null:101,
      permissions:role==='admin'?{'settings.accounts':'edit'}:{}},false)
    const router=createRouter({history:createMemoryHistory(),routes:shadowRoutes.map(r=>({...r,component:{template:'<div />'}}))})
    for (const r of shadowRoutes) {
      const path=r.path.replace(':planId','synthetic-plan')
      await router.push(path)
      assert.equal(router.currentRoute.value.meta.shadowPage,r.meta.shadowPage)
      const app=createSSRApp(component); app.use(router); app.use(ElementPlus)
      const html=await renderToString(app)
      assert.match(html,/影子模式，不会改动百度投放/)
      const buttons=[...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map(m=>m[1].replace(/<[^>]+>/g,'')).join('|')
      assert.doesNotMatch(buttons,/执行投放|上传百度|启用计划|客户确认|自动暂停|立即上线/)
      if (r.meta.shadowPage==='submit') {
        assert.match(html,/页面内容（长文本）/);assert.match(html,/10MiB/);assert.match(html,/30MiB/)
        assert.match(html,/保存来源/)
        if(role!=='advisor') assert.match(html,/<fieldset[^>]*disabled/)
      }
      if (r.meta.shadowPage==='grants') {
        assert.match(html,/禁止撤掉最后一条有效授权/)
        assert.ok(html.includes(REVOKE_CHECK_NOTICE))
        if(role!=='admin') assert.match(html,/<fieldset[^>]*disabled/)
      }
    }
  }
} finally { await server.close() }
console.log('SEM shadow routes, rendered forms/buttons, role guards, limits and API contracts PASS')
