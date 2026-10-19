import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createDistributionInboxApi } from '../src/api/distributionInbox.js'
import { createInboxState } from '../src/components/geoDistributionInboxState.js'
import { inboxIdentity, canOpenInbox, createGeoInboxSession } from '../src/utils/geoInboxSession.js'
import { geoSessionRouteDecision } from '../geo-frontend/src/authRouteDecision.js'

const rid = '00000000-0000-4000-8000-000000000001'
const makeToken = claims => `synthetic.${Buffer.from(JSON.stringify({ sub: '11', exp: Math.floor(Date.now()/1000)+3600, ...claims })).toString('base64url')}.synthetic`
const identity = makeToken({ scope_kind: 'advisor_identity', aud: 'advisor-session' })
const business = makeToken({ scope_kind: 'advisor_tenant', aud: 'advisor-business', tid: 7, gid: 1 })
const sessionFor = token => ({ token, user: { id: 11, is_advisor: true }, tenantId: 7, isLoggedIn: true })
const storage = saved => ({ getItem: () => JSON.stringify(saved) })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const ok = data => ({ ok: true, json: async () => data })

test('independent inbox sends only identity bearer and no implicit tenant/project/key', async () => {
  const calls = []
  const api = createDistributionInboxApi({ getIdentity: () => ({token: identity, revision: 1, scopeKind:'advisor_identity'}),
    fetchImpl: async (...args) => { calls.push(args); return ok({ items: [] }) } })
  await api.createPairing(); await api.targets(); await api.receipts(); await api.devices()
  for (const [url, options] of calls) {
    assert.match(url, /^\/api\/v1\/seo\/distribution\/v2\/inbox\//)
    assert.ok(!url.includes('tenant') && !url.includes('project') && !url.includes('key='))
    assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error')
    assert.deepEqual(Object.keys(options.headers).filter(k => !['Authorization','Content-Type'].includes(k)), [])
  }
  assert.equal(calls[0][1].body, '{}')
  assert.throws(() => api.receipts({ tenant_id: 7 }), /INBOX_SELECTOR_FORBIDDEN/)
})

test('business JWT cannot replace the saved identity; other users and expired identity are rejected', () => {
  const session = sessionFor(business)
  assert.equal(inboxIdentity(session,storage({token:identity})).token, identity)
  assert.equal(inboxIdentity(session,storage({token:business})),null)
  assert.equal(inboxIdentity(session,storage({token:makeToken({scope_kind:'advisor_identity',aud:'advisor-session',sub:'12'})})),null)
  assert.equal(inboxIdentity(session,storage({token:makeToken({scope_kind:'advisor_identity',aud:'advisor-session',exp:1})})),null)
})

test('GEO-only and zero-grant advisors can enter the identity route without geo/seo menu permission', () => {
  const session={...sessionFor(identity),permissions:{},canView:()=>false}
  assert.equal(canOpenInbox(session),true)
  assert.equal(geoSessionRouteDecision({route:{meta:{inboxIdentity:true}},session,leaveWorkspace:()=>false}),true)
  assert.equal(canOpenInbox({...session,user:{id:11},token:'ordinary',isLoggedIn:true}),false)
})

test('business prepare validates exact tenant, user and audience without mutating shell session', async () => {
  const session=sessionFor(identity), before={...session}
  const auth=createGeoInboxSession({session,storage:storage(null),fetchImpl:async (url,options)=>{
    assert.equal(url,'/api/v1/auth/select-tenant'); assert.deepEqual(JSON.parse(options.body),{tenant_id:7})
    return ok({tenant_id:7,access_token:business})
  }})
  assert.equal(auth.business('geo',7),null)
  await auth.prepare(7)
  assert.equal(auth.business('geo',7).token,business)
  assert.deepEqual(session,before)
  auth.clear(); assert.equal(auth.business('geo',7),null)
})

test('late business selection and receipt responses cannot restore data after identity or tenant changes', async () => {
  const session=sessionFor(identity), delay=deferred()
  const auth=createGeoInboxSession({session,storage:storage(null),fetchImpl:()=>delay.promise})
  const pending=auth.prepare(7)
  session.tenantId=8
  delay.resolve(ok({tenant_id:7,access_token:business}))
  await assert.rejects(pending,/身份已变化/)
  assert.equal(auth.business('geo',7),null)
  const wait=deferred(); let context={token:identity,revision:1}
  const api=createDistributionInboxApi({getIdentity:()=>context,fetchImpl:()=>wait.promise})
  const list=api.receipts(); context={token:identity,revision:2}; wait.resolve(ok({items:[{id:rid}]}))
  await assert.rejects(list,e=>e.code==='AUTH_CONTEXT_CHANGED')
})

test('unlabel has exactly the original target business context and cannot auto-relabel', async () => {
  const calls=[]
  const api={ unlabel:async (...args)=>calls.push(args), receipts:async()=>({items:[]}), devices:async()=>({items:[]}), count:async()=>({count:0}) }
  const model=createInboxState(api)
  await model.unlabel({id:rid,revision:3,assignment:{module:'seo',tenantId:8}})
  assert.deepEqual(calls[0].slice(0,4),['seo',8,rid,{expectedRevision:3,reason:'人工撤销归属'}])
  assert.equal(calls.length,1)
})

test('clear removes pairing, devices and stale requests; failed unlabel never issues a label', async () => {
  const delay=deferred(); const calls=[]
  const api={ createPairing:()=>delay.promise, unlabel:async()=>{throw new Error('授权已撤销')}, label:()=>calls.push('label') }
  const model=createInboxState(api)
  const pending=model.pair(); model.clear(); delay.resolve({pairingCode:'synthetic'})
  await pending; assert.equal(model.state.pairing,null)
  await model.unlabel({id:rid,revision:0,assignment:{module:'geo',tenantId:7}})
  assert.equal(model.state.error,'授权已撤销'); assert.deepEqual(calls,[])
})

test('publications use selected GEO business JWT and only explicit tenant/scope selectors', async () => {
  const calls=[]
  const api=createDistributionInboxApi({getBusiness:(module,tenant)=>{
    assert.equal(module,'geo'); assert.equal(tenant,7); return {token:business,revision:1}
  },fetchImpl:async (...args)=>{calls.push(args);return ok({items:[]})}})
  await api.publications(7,5)
  assert.equal(calls[0][0],'/api/v1/geo/distribution/v2/publications?tenant_id=7&scope_id=5')
  assert.equal(calls[0][1].headers.Authorization,`Bearer ${business}`)
})

test('identity route is outside business shell and bootstrap, with plain-text and safe link rendering', () => {
  const read = path => readFileSync(new URL(path,import.meta.url),'utf8')
  const app=read('../geo-frontend/src/App.vue'), router=read('../geo-frontend/src/router.js')
  assert.match(app, /<router-view v-if="inboxRoute"/)
  assert.match(app, /if \(!inboxRoute.value\)/)
  assert.ok(router.indexOf("path: '/distribution-inbox'")<router.indexOf("path: '/geo'"))
  const view=read('../src/components/GeoDistributionInbox.vue')
  assert.ok(!view.includes('v-html'))
  assert.match(view,/rel="noopener noreferrer"/); assert.match(view,/暂无可标注的客户，请联系超管授权/)
  assert.match(view,/safeLink\(row.publicUrl\)/)
})
