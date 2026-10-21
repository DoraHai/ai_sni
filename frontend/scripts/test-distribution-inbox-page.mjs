import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'
import { parse, compileScript } from '@vue/compiler-sfc'
const dom = new JSDOM('<body></body>', { url: 'https://synthetic.invalid/' })
for (const key of ['window','document','Node','Element','HTMLElement','SVGElement','Event','localStorage','sessionStorage']) globalThis[key]=dom.window[key]
const { createApp, nextTick } = await import('vue')
const { session } = await import('../src/store/session.js')
const require = createRequire(import.meta.url)
const uri = code => 'data:text/javascript;base64,'+Buffer.from(code).toString('base64')
const jsurl = name => JSON.stringify(new URL(name,import.meta.url).href)
async function compiled(name) {
  const source = await readFile(new URL('../src/views/seo/'+name,import.meta.url),'utf8')
  return compileScript(parse(source).descriptor,{id:name,inlineTemplate:true}).content
    .replace(/from (['"])vue\1/g,'from '+JSON.stringify(pathToFileURL(require.resolve('vue')).href))
}
const child = uri((await compiled('DistributionInbox.vue')).replace("from './distributionInboxState.js'",'from '+jsurl('../src/views/seo/distributionInboxState.js')))
const page = (await compiled('DistributionInboxPage.vue'))
  .replace("from '../../store/session'",'from '+jsurl('../src/store/session.js'))
  .replace("from '../../api/distributionInbox.js'",'from '+jsurl('../src/api/distributionInbox.js'))
  .replace("from './DistributionInbox.vue'",'from '+JSON.stringify(child))
const Component = (await import(uri(page))).default
const rid='11111111-1111-4111-8111-111111111111'
const jwt = claims => 'synthetic.'+Buffer.from(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600,...claims})).toString('base64url')+'.synthetic'
const identity=jwt({scope_kind:'advisor_identity',aud:'advisor-session'})
const business=jwt({scope_kind:'advisor_tenant',aud:'advisor-business',tid:4,gid:10})
const user={id:7,tenant_id:null,is_advisor:true,permissions:{'geo.assets':'edit','geo.content':'edit'}}
const flush=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick()}
const click=async(el,text)=>{[...el.querySelectorAll('button')].find(b=>b.textContent===text).click();await flush()}

test('mounted page uses restored identity, per-target business exchange and no global customer switch',async()=>{
  session.setAuth(identity,user,false)
  session.replaceAuthForAdvisorTenant(business,4)
  const calls=[]
  globalThis.fetch=async(path,options)=>{
    calls.push({path,...options})
    const data=path.endsWith('/targets')?{items:[{tenantId:4,name:'合成客户',modules:['geo'],scopes:[]}],owners:[]}
      :path.endsWith('/select-tenant')?{access_token:business}
      :path.includes('/label?')?{id:rid}
      :path.endsWith('/count')?{count:1}
      :path.endsWith('/devices')?{items:[]}
      :{items:[{id:rid,revision:0,platform:'other',title:'synthetic',result:'unknown',assignment:null}]}
    return {ok:true,json:async()=>data}
  }
  const element=document.createElement('div');document.body.append(element)
  const app=createApp(Component);app.mount(element)
  try{
    await flush();await flush()
    assert(calls.filter(c=>c.path.includes('/inbox/')).every(c=>c.headers.Authorization==='Bearer '+identity))
    const selected=element.querySelector('article select')
    selected.value='4';selected.dispatchEvent(new dom.window.Event('change',{bubbles:true}));await flush()
    await click(element,'标注客户');await flush()
    const exchange=calls.find(c=>c.path.endsWith('/select-tenant'))
    assert.equal(exchange.headers.Authorization,'Bearer '+identity)
    assert.deepEqual(JSON.parse(exchange.body),{tenant_id:4})
    const label=calls.find(c=>c.path.includes('/geo/distribution/v2/')&&c.path.includes('/label?'))
    assert.equal(label.headers.Authorization,'Bearer '+business)
    assert.equal(label.credentials,'omit')
    assert.equal(session.token,business)
    assert.equal(session.tenantId,4)
    session.logout();await flush()
    assert(!element.textContent.includes('合成客户'))
    assert(!element.textContent.includes('synthetic'))
  }finally{app.unmount();element.remove();session.logout()}
})

test('unified route is outside the SEO business shell and external records are mounted',async()=>{
  const router=await readFile(new URL('../src/seo-router.js',import.meta.url),'utf8')
  assert(router.includes("path: '/seo/distribution-inbox', component:"))
  const distribution=await readFile(new URL('../src/views/seo/SeoDistributionView.vue',import.meta.url),'utf8')
  assert(distribution.includes('<DistributionExternalPublications :tenant-id="currentTenantId" :scope-id="siteId"'))
  assert(distribution.includes('旧版稿件派发（0.3.5 / 0.3.6 兼容区）'))
  const external=await readFile(new URL('../src/views/seo/DistributionExternalPublications.vue',import.meta.url),'utf8')
  assert.match(external, /<p v-else-if="!items.length">暂无外部回传记录<br \/>\s*<span>没选网站的回传不会出现在这里，请到多号通回传收件箱补选网站。<\/span>/)
})
