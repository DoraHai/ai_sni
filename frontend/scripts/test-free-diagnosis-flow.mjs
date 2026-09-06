import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { effectScope, ref, nextTick } from 'vue'
import { validWebsite, initialWebsite, diagnosisDestination } from '../src/views/diagnosis/diagnosisWebsite.js'
import { brandDraft, mergeBrandProfile } from '../src/views/diagnosis/brandProfileFields.js'

const root = new URL('../src/views/diagnosis/', import.meta.url)
const source = readFileSync(new URL('useFreeDiagnosisFlow.js', root), 'utf8')
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("import * as diagnosticApi from '../../api/diagnostic'", 'const diagnosticApi = {}')
  .replace("from './brandProfileFields'", `from '${new URL('brandProfileFields.js', root)}'`)
  .replace("from './diagnosisWebsite'", `from '${new URL('diagnosisWebsite.js', root)}'`)
const { useFreeDiagnosisFlow } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const flush = async () => { await nextTick(); await new Promise(r => setImmediate(r)); await nextTick() }
const deferred = () => { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b}); return {promise,resolve,reject} }
const brand = {name:'示例企业',website:'https://www.nord.cn/cn/home-cn.jsp',industry:'工业驱动技术',core_products:['减速机'],brand_terms:['旧品牌词'],proof_points:['旧证明'],business_desc:'旧介绍',competitors:[{name:'已有竞品',confirmed:true}]}
const record = (id=10) => ({id,score:67,ai_enabled:true,url:brand.website,final_url:brand.website,problems:[{severity:'high'},{severity:'medium'}],snapshot:{}})
function setup(overrides = {}, search = '') {
  const calls = {discover:0,profile:0,save:[],audit:0,sample:[],performance:0}
  const api = {
    async discoverGeoBrand(){calls.discover++;return {brand}},
    async fetchGeoAssetProfile(){calls.profile++;return {brand}},
    async saveGeoBrand(payload){calls.save.push(payload);return {brand:payload}},
    async runGeoAudit(){calls.audit++;return record()},
    async runDeepSeekSample(payload){calls.sample.push(payload);return {snapshot:{ai_sampling:{results:[{question:'默认问题'}]}}}},
    async fetchPageSpeedInsights(){calls.performance++;return {status:'available',metrics:{}}},
    ...overrides,
  }
  const state = {tenantId:ref(1),audit:ref(null),pageSpeed:ref(null),brandProfile:ref({}),brandReady:ref(false),url:ref(''),samplingLoading:ref(false),pageSpeedLoading:ref(false),sampleQuestions:ref(['','','']),ensureTenant:async()=>true}
  const scope = effectScope()
  const flow = scope.run(()=>useFreeDiagnosisFlow({...state,api,search}))
  return {flow,state,calls,scope}
}
let passed = 0
async function test(name, callback) { await callback(); console.log(`PASS ${++passed}: ${name}`) }
await test('营销 URL 在安全 redirect 编码/解码后完整保留，初始化不请求', async()=>{
  const target = diagnosisDestination(brand.website)
  const loginSource = readFileSync(new URL('../src/auth/loginRedirect.js',import.meta.url),'utf8').replaceAll('import.meta.env.VITE_AUTH_ORIGIN',"'https://auth.example.com'").replaceAll('import.meta.env.DEV','false')
  const {loginUrl} = await import(`data:text/javascript;base64,${Buffer.from(loginSource).toString('base64')}`)
  const returnPath = new URL(loginUrl(target)).searchParams.get('redirect')
  const t = setup({}, new URL(returnPath,'https://login.example.com').search)
  assert.equal(t.flow.website.value, brand.website); assert.equal(t.calls.discover,0);assert.equal(t.calls.audit,0); t.scope.stop()
})
await test('无参数直接进入入口',()=>{const t=setup();assert.equal(t.flow.stage.value,'entry');assert.equal(t.flow.website.value,'');t.scope.stop()})
await test('合法 URL 与路径保留',()=>{assert.equal(validWebsite('www.nord.cn/cn/home-cn.jsp'),brand.website)})
await test('非法 scheme、凭证、协议相对地址、空值拒绝',()=>{for(const s of ['javascript:alert(1)','file:///tmp/a','https://u:p@example.com','//evil.com','','abc','https://127.0.0.1'])assert.throws(()=>validWebsite(s));assert.equal(initialWebsite('?website=javascript:alert(1)').website,'')})
await test('识别完整资料后轻量确认，不自动诊断',async()=>{const t=setup();t.flow.website.value=brand.website;await t.flow.discover();assert.equal(t.flow.stage.value,'confirm');assert.equal(t.flow.missing.value.length,0);assert.equal(t.calls.audit,0);t.scope.stop()})
await test('识别缺项不编造、不保存',async()=>{const t=setup({discoverGeoBrand:async()=>({brand:{website:brand.website,name:'企业'}})});t.flow.website.value=brand.website;await t.flow.discover();assert.deepEqual(t.flow.missing.value.map(x=>x.key),['industry','core_products']);await t.flow.confirm();assert.equal(t.calls.save.length,0);t.scope.stop()})
await test('识别失败可重试',async()=>{let fail=true;const t=setup({discoverGeoBrand:async()=>{if(fail)throw Error('403');return {brand}}});t.flow.website.value=brand.website;await t.flow.discover();assert.equal(t.flow.stage.value,'recognition-error');fail=false;await t.flow.discover();assert.equal(t.flow.stage.value,'confirm');t.scope.stop()})
await test('保存合并保留隐藏字段和竞品，明确编辑才覆盖',()=>{const d=brandDraft({...brand,brand_terms:[],proof_points:[],business_desc:''});const merged=mergeBrandProfile(brand,d);assert.deepEqual(merged.competitors,brand.competitors);assert.deepEqual(merged.brand_terms,brand.brand_terms);assert.deepEqual(merged.proof_points,brand.proof_points);assert.equal(merged.business_desc,brand.business_desc);assert.deepEqual(mergeBrandProfile(brand,d,new Set(['proof_points'])).proof_points,[])})
await test('profile 读取失败不调用 PUT，保留草稿',async()=>{const t=setup({fetchGeoAssetProfile:async()=>{throw Error('网络故障')}});t.flow.website.value=brand.website;await t.flow.discover();await t.flow.confirm();assert.equal(t.calls.save.length,0);assert.equal(t.flow.draft.name,brand.name);assert.equal(t.flow.stage.value,'confirm');t.scope.stop()})
await test('audit 成功 → 直接进入报告，仅一份 audit，自动三问只请求一次',async()=>{const t=setup();t.flow.website.value=brand.website;await t.flow.discover();await t.flow.confirm();await flush();assert.equal(t.flow.stage.value,'report');assert.equal(t.state.audit.value.score,67);assert.equal(t.calls.sample.length,1);assert.deepEqual(t.calls.sample[0].questions,[]);await t.flow.sample({automatic:true});assert.equal(t.calls.sample.length,1);t.scope.stop()})
await test('audit 失败只重试诊断，不重复保存/识别',async()=>{let fail=true;const t=setup({runGeoAudit:async()=>{if(fail)throw Error('超时');return record()}});t.flow.website.value=brand.website;await t.flow.discover();await t.flow.confirm();assert.equal(t.flow.statuses.audit,'error');fail=false;await t.flow.runAudit();assert.equal(t.calls.discover,1);assert.equal(t.calls.save.length,1);assert.equal(t.flow.stage.value,'report');t.scope.stop()})
await test('AI 失败后单独重试成功',async()=>{let fail=true;const t=setup({runDeepSeekSample:async()=>{if(fail)throw Error('抽样失败');return {snapshot:{ai_sampling:{results:[]}}}}});t.state.audit.value=record();await flush();assert.equal(t.flow.statuses.sample,'error');fail=false;await t.flow.sample();assert.equal(t.flow.statuses.sample,'success');t.scope.stop()})
await test('PageSpeed 成功 / 失败 / 不可用分别呈现',async()=>{for(const status of ['available','error','unavailable']){const t=setup({fetchPageSpeedInsights:async()=>({status,reason:'测试'})});t.state.audit.value=record();await flush();assert.equal(t.flow.statuses.performance,status==='available'?'success':status);t.scope.stop()} const t=setup({fetchPageSpeedInsights:async()=>{throw Error('超时')}});t.state.audit.value=record();await flush();assert.equal(t.flow.statuses.performance,'error');t.scope.stop()})
await test('附加检测未完成可先看报告，后续仍更新同一 audit',async()=>{const pending=deferred();const t=setup({runDeepSeekSample:()=>pending.promise,fetchPageSpeedInsights:()=>new Promise(()=>{})});t.state.audit.value=record();await flush();assert.equal(t.flow.statuses.sample,'running');t.flow.showReport();assert.equal(t.flow.stage.value,'report');pending.resolve({snapshot:{ai_sampling:{results:[]}}});await flush();assert.ok(t.state.audit.value.snapshot.ai_sampling);t.scope.stop()})
await test('旧抽样和性能结果不能覆盖新诊断',async()=>{const sample=deferred(),perf=deferred();let n=0,m=0;const t=setup({runDeepSeekSample:()=>++n===1?sample.promise:Promise.resolve({snapshot:{ai_sampling:{results:[{question:'新'}]}}}),fetchPageSpeedInsights:()=>++m===1?perf.promise:Promise.resolve({status:'available',marker:'new'})});t.state.audit.value=record(1);await flush();t.flow.reset();t.state.audit.value=record(2);await flush();sample.resolve({snapshot:{ai_sampling:{results:[{question:'旧'}]}}});perf.resolve({status:'available',marker:'old'});await flush();assert.equal(t.state.audit.value.id,2);assert.equal(t.state.audit.value.snapshot.ai_sampling.results[0].question,'新');assert.equal(t.state.pageSpeed.value.marker,'new');t.scope.stop()})
await test('租户切换与旧识别/audit 响应隔离',async()=>{const pending=deferred();const t=setup({discoverGeoBrand:()=>pending.promise});t.flow.website.value=brand.website;const request=t.flow.discover();t.state.tenantId.value=2;await flush();pending.resolve({brand});await request;assert.equal(t.flow.stage.value,'entry');assert.equal(t.flow.draft.name,'');t.scope.stop()})
await test('未启用 AI 不调用模型，已有抽样不重复调用',async()=>{for(const r of [{...record(),ai_enabled:false},{...record(),snapshot:{ai_sampling:{results:[]}}}]){const t=setup();t.state.audit.value=r;await flush();assert.equal(t.calls.sample.length,0);t.scope.stop()}})
await test('正式导航仅报告状态显示，打印入口保留，假进度已移除',()=>{const view=readFileSync(new URL('DiagnosisCenterView.vue',root),'utf8');assert.ok(view.includes("flow.stage.value !== 'report'"));assert.ok(view.includes('v-else class="diagnosis-center"'));assert.ok(view.includes('window.print()'));assert.ok(view.includes('@click="printReport"'));assert.ok(!view.includes('2600'));assert.ok(!view.includes('loadingStage'));})
await test('旧 audit 响应不覆盖新一轮状态',async()=>{const old=deferred();const t=setup({runGeoAudit:()=>old.promise});t.state.url.value=brand.website;const task=t.flow.runAudit();t.flow.reset();old.resolve(record(99));await task;assert.equal(t.state.audit.value,null);assert.equal(t.flow.stage.value,'entry');t.scope.stop()})
await test('正式报告样式与打印方法逐字保持原版本',()=>{
  const path='frontend/src/views/diagnosis/DiagnosisCenterView.vue'
  const before=execFileSync('git',['show',`HEAD:${path}`],{encoding:'utf8'})
  const after=readFileSync(new URL('DiagnosisCenterView.vue',root),'utf8')
  assert.equal(after.slice(after.indexOf('<style scoped>')),before.slice(before.indexOf('<style scoped>')))
  const method=s=>s.slice(s.indexOf('async function printReport()'),s.indexOf('\nwatch(tenantId'))
  assert.equal(method(after),method(before))
})
await test('基础诊断完成立即进入报告，待完成的附加检测继续更新', async () => {
  const sample = deferred(), performance = deferred()
  const t = setup({runDeepSeekSample:()=>sample.promise, fetchPageSpeedInsights:()=>performance.promise})
  t.flow.website.value = brand.website
  await t.flow.discover(); await t.flow.confirm(); await flush()
  assert.equal(t.flow.stage.value, 'report')
  assert.equal(t.flow.statuses.sample, 'running')
  assert.equal(t.flow.statuses.performance, 'running')
  sample.resolve({snapshot:{ai_sampling:{results:[{question:'默认问题'}]}}})
  performance.resolve({status:'available',metrics:{}})
  await flush()
  assert.equal(t.flow.stage.value, 'report')
  assert.equal(t.flow.statuses.sample, 'success')
  assert.equal(t.flow.statuses.performance, 'success')
  assert.ok(t.state.audit.value.snapshot.ai_sampling)
  t.scope.stop()
})
console.log(`${passed} test groups passed`)
