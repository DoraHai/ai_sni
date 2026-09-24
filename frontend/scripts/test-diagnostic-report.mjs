import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import { normalizeFinding } from '../src/views/diagnosis/diagnosticFindingState.js'
import { reportModel } from '../src/views/diagnosis/diagnosticReportModel.js'
import { slideReportModel, splitReportText } from '../src/views/diagnosis/diagnosticSlideModel.js'
const root = new URL('../src/views/diagnosis/', import.meta.url)
const source = readFileSync(new URL('DiagnosticPrintReport.vue', root), 'utf8')
const { descriptor } = parse(source)
let code = compileScript(descriptor, { id:'diagnostic-report-test', inlineTemplate:true }).content
code = code.replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`).replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
for (const file of ['diagnosticReportModel.js','diagnosticFindingState.js','diagnosticSlideModel.js']) code = code.replaceAll(`'./${file}'`, `'${new URL(file, root)}'`)
// Resolve the real logo in the standalone SSR harness (Vite handles this in production).
const logo = readFileSync(new URL('../../assets/g-snipers-purple-logo.png', root)).toString('base64')
code = code.replace("import brandLogo from '../../assets/g-snipers-purple-logo.png'", `const brandLogo = 'data:image/png;base64,${logo}'`)
const { default: PrintReport } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const crawler = { code:'ai_crawlers', title:'主流 AI 爬虫未被整站拦截', category:'AI 可访问性', severity:'high', passed:null, status:'unavailable', deduction:0, evidence:'robots.txt 不可读，无法审计 AI 爬虫 UA' }
const success = { code:'https', title:'HTTPS 安全访问', passed:true, status:'passed', weight:8, deduction:0, evidence:'https://example.com/' }
const failed = { code:'title', title:'页面标题清晰完整', passed:false, status:'failed', deduction:8, severity:'high', evidence:'当前标题：缺失', recommendation:'补充页面标题。' }
const base = { score:92, rule_version:'1.1.1', created_at:'2026-09-23T12:00:00Z', url:'https://example.com/', findings:[success,failed,crawler], snapshot:{} }
let count = 0
async function test(name, fn) { await fn(); console.log(`PASS ${++count}: ${name}`) }
await test('未检测从问题、分母和扣分中排除', () => {
  const model = reportModel(base)
  assert.equal(model.failed.length,1); assert.equal(model.evaluated.length,2)
  assert.equal(model.passRate,50); assert.equal(model.unavailable.length,1)
  assert.equal(model.findings[2].deduction,0)
})
await test('历史未知记录只作兼容说明，不重写原评分', () => {
  const old = {...crawler, passed:false, status:undefined, deduction:6}
  const raw = {...base, score:86, findings:[success,failed,old]}
  const model = reportModel(raw)
  assert.equal(model.legacy,true); assert.equal(model.score,86)
  assert.equal(model.failed.length,1); assert.equal(model.findings[2].deduction,0)
  assert.match(model.scoreNote,/历史/); assert.equal(old.deduction,6)
})
await test('新聚合结果中的未知页面不覆盖明确通过或失败', () => {
  for (const passed of [true,false]) {
    const item = normalizeFinding({...crawler, passed, status:passed?'passed':'failed', evidence:'已评估1页', page_evidence:[{passed:null,status:'unavailable',evidence:crawler.evidence}]})
    assert.equal(item.passed,passed); assert.equal(item.legacyIndeterminate,false)
  }
})
await test('全部未检测不显示 100 分或 0% 通过率', () => {
  const model = reportModel({...base, score:100, findings:[crawler]})
  assert.equal(model.score,null); assert.equal(model.passRate,null)
})
await test('缺失外部数据不转换为零；真实零值保留', () => {
  assert.ok(reportModel(base).external.every(x=>x.value==='未检测'))
  const model=reportModel({...base,snapshot:{external_metrics:{baidu_index:{status:'available',site_count:0},whois:{status:'available',domain_age_years:null}}}})
  assert.equal(model.external[0].value,'0页'); assert.equal(model.external[3].value,'未检测')
  assert.ok(model.performanceRows.every(x=>x.value==='未检测'))
})
await test('竞品报告不借用当前客户品牌', () => {
  const model=reportModel({...base,snapshot:{audit_mode:'competitor'}},{name:'其他客户'})
  assert.equal(model.name,'example.com')
})
await test('AI 统计只根据有原始回答且已判定的样本，不使用陈旧百分比', () => {
  const model=reportModel({...base,snapshot:{ai_sampling:{mention_rate:1,results:[{response:'有证据',mentioned:true},{response:'无命中',mentioned:false},{response:''},{response:'未判定'}]}}})
  assert.equal(model.mentionRate,50); assert.equal(model.sampleCount,2); assert.equal(model.sampleRows.length,3)
})
await test('实际打印组件不包含操作控件、流程阶段、演示评分或会员推广', async () => {
  const html=await renderToString(createSSRApp(PrintReport,{audit:base,brand:{name:'示例企业'}}))
  assert.ok(!/<(?:button|input|select|details|nav)\b/.test(html))
  for(const text of ['立即诊断','重新抽样','会员解锁','去处理','复制全部','百度索引规模充足']) assert.ok(!html.includes(text),text)
  for(const text of ['官网 AI 搜索诊断结果','问题清单与行动路线','检测明细','证据来源','未检测 / 无法确认','附录三']) assert.ok(html.includes(text),text)
})
await test('长回答生成续页且原文完整；外部内容作为文本转义', async () => {
  const response = '<script>alert("x")</script>唯一原始回答。'+'完整长回答内容。'.repeat(800)
  const html=await renderToString(createSSRApp(PrintReport,{audit:{...base,snapshot:{ai_sampling:{results:[{question:'样本问题',mentioned:true,response}]}}}}))
  assert.equal(html.split('唯一原始回答').length-1,2)
  const slides = slideReportModel({...base,snapshot:{ai_sampling:{results:[{question:'样本问题',response}]}}}).slides
  assert.equal(slides.filter(s=>s.kind==='answer').map(s=>s.text).join(''),response)
  assert.ok(slides.filter(s=>s.kind==='answer').length > 1)
  assert.ok(!html.includes('<script>')); assert.ok(html.includes('&lt;script&gt;'))
})
await test('横版章节顺序与附录三引用；所有规则只进入对应附录', () => {
  const m = slideReportModel({...base,findings:[{...success,category:'技术基础'},failed,crawler]})
  assert.deepEqual(m.slides.filter(s=>s.kind==='divider').map(s=>s.title), ['概览','SEO 诊断','GEO / AI 搜索诊断','附录'])
  assert.deepEqual(m.slides.filter(s=>s.kind==='rules').flatMap(s=>s.rows).filter(r=>!r.part).map(r=>r.item.code),['https','title','ai_crawlers'])
  assert.match(source,/完整原文见附录三/);assert.ok(!source.includes('完整原文见附录二'))
  assert.match(source,/size:1280px 720px/)
})
await test('通用产品词不能触发明确品牌命中；英文名称使用单词边界', () => {
  const audit = {...base,snapshot:{brand_profile:{name:'诺德',english_name:'NORD'},ai_sampling:{results:[
    {response:'推荐变频器',mentioned:true,matched_terms:['变频器']},
    {response:'NORD provides drives',mentioned:false}, {response:'nordic products',mentioned:true}, {response:'诺德驱动',mentioned:true},
  ]}}}
  const original = JSON.stringify(audit);const m=slideReportModel(audit)
  assert.equal(m.explicitCount,2);assert.equal(m.explicitRate,50);assert.equal(JSON.stringify(audit),original)
  const unknown=slideReportModel({...base,snapshot:{ai_sampling:{results:[{response:'变频器',mentioned:true}]}}})
  assert.equal(unknown.explicitRate,null)
})
await test('长证据、Unicode 和换行保留全部内容并分页', () => {
  const value=('长证据🙂 https://example.com/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n').repeat(120)
  assert.equal(splitReportText(value,225).join(''),value)
  const m=slideReportModel({...base,findings:[{...failed,evidence:value,recommendation:value}]})
  const body=m.slides.filter(s=>s.kind==='rules').flatMap(s=>s.rows).map(r=>r.text).join('')
  assert.ok(body.includes(value));assert.equal(body.split(value).length-1,2)
  assert.ok(m.slides.filter(s=>s.kind==='rules').length>1)
})
await test('未知维度和真实零值分别输出，不伪造雷达或综合评分', () => {
  const m=slideReportModel({...base,findings:[crawler]})
  assert.ok(m.dimensions.every(d=>d.score===null));assert.equal(m.score,null)
  const zero=slideReportModel({...base,findings:[{...failed,category:'技术基础',weight:8,deduction:8}]})
  assert.equal(zero.dimensions[0].score,0)
})
console.log(`${count} report test groups passed`)
