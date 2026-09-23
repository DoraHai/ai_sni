import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import { normalizeFinding } from '../src/views/diagnosis/diagnosticFindingState.js'
import { reportModel } from '../src/views/diagnosis/diagnosticReportModel.js'
const root = new URL('../src/views/diagnosis/', import.meta.url)
const source = readFileSync(new URL('DiagnosticPrintReport.vue', root), 'utf8')
const { descriptor } = parse(source)
let code = compileScript(descriptor, { id:'diagnostic-report-test', inlineTemplate:true }).content
code = code.replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`).replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
for (const file of ['diagnosticReportModel.js','diagnosticFindingState.js']) code = code.replaceAll(`'./${file}'`, `'${new URL(file, root)}'`)
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
  for(const text of ['立即诊断','重新抽样','会员解锁','去处理','复制全部','OVERVIEW','百度索引规模充足']) assert.ok(!html.includes(text),text)
  for(const text of ['本次诊断摘要','问题与优化建议','检测明细','证据附录','未检测 / 无法确认']) assert.ok(html.includes(text),text)
})
await test('长回答完整输出一次；外部内容作为文本转义', async () => {
  const response = '<script>alert("x")</script>唯一原始回答。'+'完整长回答内容。'.repeat(800)
  const html=await renderToString(createSSRApp(PrintReport,{audit:{...base,snapshot:{ai_sampling:{results:[{question:'样本问题',mentioned:true,response}]}}}}))
  assert.equal(html.split('唯一原始回答').length-1,1)
  assert.equal(html.split('完整长回答内容。').length-1,800)
  assert.ok(!html.includes('<script>')); assert.ok(html.includes('&lt;script&gt;'))
})
console.log(`${count} report test groups passed`)
