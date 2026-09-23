<script setup>
import { computed } from 'vue'
import { reportModel, reportDate } from './diagnosticReportModel.js'
import { statusLabel } from './diagnosticFindingState.js'
const props = defineProps({ audit: { type: Object, required: true }, brand: Object, pageSpeed: Object })
const report = computed(() => reportModel(props.audit, props.brand, props.pageSpeed))
const severity = value => ({ critical:'阻断', high:'高', medium:'中', low:'低' }[value] || '未分级')
</script>

<template>
  <article class="diagnostic-print-report" aria-label="网站诊断报告打印正文">
    <header class="dp-masthead"><b>G-SNIPERS<span>获客狙击手</span></b><span>WEBSITE DIAGNOSTIC / 网站诊断</span></header>
    <section class="dp-cover">
      <p class="dp-eyebrow">{{ report.competitor ? '竞品公开网站分析' : 'SEO + GEO / 网站基础与 AI 搜索准备度' }}</p>
      <h1>{{ report.name }}<br><span>网站诊断报告</span></h1>
      <p class="dp-url">{{ report.website }}</p>
      <div class="dp-meta"><span>检测时间<br><b>{{ report.date }}</b></span><span>检测范围<br><b>{{ report.scope }}</b></span><span>规则版本<br><b>{{ report.version }}</b></span></div>
      <div class="dp-summary">
        <div class="dp-score"><span>{{ report.legacy ? '历史记录评分' : '基础规则评分' }}</span><strong>{{ report.score ?? '—' }}<small v-if="report.score !== null">/100</small></strong><p>{{ report.scoreNote }}</p></div>
        <div class="dp-conclusion"><h2>本次诊断摘要</h2><p>已评估 <b>{{ report.evaluated.length }}</b> 项规则，其中 <b>{{ report.passed }}</b> 项通过、<b>{{ report.failed.length }}</b> 项未通过，另有 <b>{{ report.unavailable.length }}</b> 项未检测。</p><p v-if="report.failed.length">建议优先核查 {{ report.high }} 项高优先级问题，并依据后文列出的证据完成修复和复检。</p><p v-else>当前已评估规则未发现明确失败项；未检测部分仍需补充验证。</p><p class="dp-muted">{{ report.competitor ? '仅分析竞品公开页面，不推断内部经营表现。' : '结果仅反映记录时间与本次抽样范围内的检测证据。' }}</p></div>
      </div>
      <div class="dp-statline"><span>规则通过率 <b>{{ report.passRate === null ? '未检测' : `${report.passRate}%` }}</b></span><span>高优先级问题 <b>{{ report.high }}</b></span><span>待补充检测 <b>{{ report.unavailable.length }}</b></span></div>
      <h2 class="dp-section-title">阅读指引</h2>
      <p>先阅读问题与优化建议，再核对检测明细。外部搜索指标和模型抽样单独列示；未获得结果的维度均标记为“未检测”。</p>
      <p class="dp-note">通过率仅以已评估规则为分母。未检测既不通过也不失败，不计入本次评分扣分。全站抽样按首页 3、核心页 2、其他页 1 加权，未检测页面不进入对应规则的已评估分母。扣分表示规则评分变化，不表示流量或业务损失。</p>
    </section>

    <section class="dp-chapter">
      <p class="dp-eyebrow">FINDINGS & RECOMMENDATIONS</p><h2 class="dp-chapter-title">问题与优化建议</h2>
      <p class="dp-intro">按严重程度与评分扣分排序。每项建议对应本次检测证据。</p>
      <p v-if="!report.failed.length" class="dp-note">本次已评估规则没有明确失败项。</p>
      <article v-for="(item, index) in report.failed" :key="item.code" class="dp-issue">
        <header><span class="dp-number">{{ String(index + 1).padStart(2,'0') }}</span><h3>{{ item.title }}</h3><span>{{ severity(item.severity) }}优先级 · 评分扣分 {{ item.deduction ? `-${item.deduction}` : '0' }}</span></header>
        <dl><dt>检测证据</dt><dd>{{ item.evidence || '证据未记录' }}</dd><dt>优化建议</dt><dd>{{ item.recommendation || '根据检测规则核查页面，修复后重新检测。' }}</dd><dt>验收依据</dt><dd>{{ item.criterion || '修复后重新运行此项规则并核对证据。' }}</dd></dl>
      </article>
      <aside v-if="report.unavailable.length" class="dp-note"><h3>待补充检测</h3><p v-for="item in report.unavailable" :key="item.code"><b>{{ item.title }}</b>：{{ item.evidence || '尚未取得可用结果' }}。不作为确定问题。</p></aside>
    </section>

    <section class="dp-chapter">
      <p class="dp-eyebrow">RULE RESULTS</p><h2 class="dp-chapter-title">检测明细</h2>
      <p class="dp-intro">保留全部规则结果，使用技术规则名称，避免将已通过项写成问题结论。</p>
      <table class="dp-rules"><colgroup><col style="width:27%"><col style="width:15%"><col style="width:10%"><col></colgroup><thead><tr><th>检测项</th><th>结果</th><th>扣分</th><th>当前证据</th></tr></thead><tbody><tr v-for="item in report.findings" :key="item.code"><td><b>{{ item.title }}</b><small>{{ item.category }}</small></td><td :class="`dp-${item.status}`">{{ statusLabel(item) }}</td><td>{{ item.passed === false && item.deduction ? `-${item.deduction}` : '—' }}</td><td>{{ item.evidence || '证据未记录' }}</td></tr></tbody></table>
      <p class="dp-note">以上扣分仅指规则评分扣分。历史不可确认项不再列为失败；历史总分保持原值并提示复检。</p>
      <template v-if="report.pages.length"><h3 class="dp-section-title">抽样页面范围</h3><table><thead><tr><th>页面</th><th>类型 / 权重</th><th>记录评分</th></tr></thead><tbody><tr v-for="page in report.pages" :key="page.url"><td>{{ page.title }}<small>{{ page.url }}</small></td><td>{{ page.page_type }} / {{ page.weight }}</td><td>{{ page.score ?? '未检测' }}</td></tr></tbody></table></template>
      <div class="dp-data-panel"><h3 class="dp-section-title">外部搜索指标</h3>
      <p v-if="report.external.every(metric => metric.value === '未检测')" class="dp-note">未检测：{{ report.external.map(metric => metric.label).join('、') }}。本次未取得可用数据，不据此推断索引质量或关键词覆盖。</p>
      <table v-else><thead><tr><th>指标</th><th>结果</th><th>来源与状态</th></tr></thead><tbody><tr v-for="metric in report.external" :key="metric.label"><td>{{ metric.label }}</td><td>{{ metric.value }}</td><td>{{ metric.note }}<small v-if="metric.source">{{ metric.source }}</small><small v-if="metric.time">{{ reportDate(metric.time) }}</small></td></tr></tbody></table>
      </div><div class="dp-data-panel"><h3 class="dp-section-title">页面性能</h3>
      <p class="dp-muted">{{ report.performance.methodology || report.performance.reason || '本次报告未取得可用的页面性能结果。' }}</p>
      <p v-if="report.performanceRows.every(metric => metric.value === '未检测')" class="dp-note">未检测：Performance、LCP、CLS、INP。本次没有可用于评估页面性能的结果。</p>
      <table v-else><thead><tr><th>指标</th><th>结果</th><th>来源</th></tr></thead><tbody><tr v-for="metric in report.performanceRows" :key="metric.label"><td>{{ metric.label }}</td><td>{{ metric.value }}</td><td>{{ metric.source || report.performance.provider || '未记录' }}</td></tr></tbody></table></div>
    </section>

    <section class="dp-chapter">
      <p class="dp-eyebrow">AI MODEL SAMPLE</p><h2 class="dp-chapter-title">AI 品牌提及抽样</h2>
      <template v-if="report.sampleRows.length">
        <p>{{ report.sample.platform || '平台未记录' }} · {{ report.sample.model || '模型未记录' }} · {{ reportDate(report.sample.executed_at) }}</p>
        <div class="dp-statline"><span>品牌提及率 <b>{{ report.mentionRate === null ? '未检测' : `${report.mentionRate}%` }}</b></span><span>已判定回答 <b>{{ report.sampleCount }}</b></span><span>提及次数 <b>{{ report.mentionCount }}</b></span></div>
        <p class="dp-note">{{ report.sample.methodology || '按已保存回答中的品牌匹配结果汇总。' }}<br>{{ report.sample.limitations || '仅代表本次单平台、少量问题抽样，不代表全部 AI 平台或长期稳定表现。' }} 品牌提及不等于推荐或排名。</p>
        <article v-for="(item, index) in report.sampleRows" :key="index" class="dp-answer">
          <header><p class="dp-eyebrow">问题 {{ index + 1 }} · {{ item.mentioned === true ? '检测到匹配词' : item.mentioned === false ? '未检测到匹配词' : '提及状态未确认' }}</p><h3>{{ item.question }}</h3><p v-if="item.matched_terms?.length" class="dp-muted">匹配词：{{ item.matched_terms.join('、') }}</p></header>
          <p v-for="(paragraph, paragraphIndex) in item.response.split(/\n\s*\n/)" :key="paragraphIndex" class="dp-response">{{ paragraph }}</p>
          <p v-for="source in item.source_urls || []" :key="source" class="dp-source">回答中的链接：{{ source }}</p>
        </article>
      </template>
      <p v-else class="dp-note">未检测：本次报告尚无可用的模型回答，不展示品牌提及率。</p>
      <p class="dp-muted">未完成真实调用的其他模型不纳入本报告。</p>
    </section>

    <section class="dp-chapter dp-appendix">
      <p class="dp-eyebrow">EVIDENCE & SCOPE</p><h2 class="dp-chapter-title">证据附录与说明</h2>
      <template v-for="item in report.findings" :key="item.code"><div v-if="item.page_evidence?.length" class="dp-page-evidence"><h3>{{ item.title }} / 逐页证据</h3><p v-for="(page, index) in item.page_evidence" :key="index"><b>{{ statusLabel(page) }} · {{ page.title || page.url }}</b><br>{{ page.url }}<br>{{ page.evidence }}</p></div></template>
      <h3 class="dp-section-title">页面结构与来源</h3>
      <p><b>页面标题</b> {{ audit.page_title || '未记录' }}</p>
      <p><b>Schema 类型</b> {{ report.snapshot.schema_types?.join('、') || '未记录' }}</p>
      <p v-for="(heading, index) in report.snapshot.headings || []" :key="`heading-${index}`" class="dp-evidence-line">H{{ heading.level }} · {{ heading.text }}</p>
      <p v-for="(link, index) in report.snapshot.external_links || []" :key="`link-${index}`" class="dp-source">外部引用 {{ index + 1 }} · {{ link }}</p>
      <p class="dp-note">本报告基于公开页面与已保存检测结果。单页或有限页面抽样不能代表整个网站；第三方索引和关键词数据不等同于实际流量。未检测项不能用于推断通过、失败或业务损失。建议网站更新后重新检测，并以原始来源核验重要事实。</p>
      <footer class="dp-end">G-SNIPERS / 获客狙击手<span>{{ report.host }} · 报告结束</span></footer>
    </section>
  </article>
</template>

<style scoped>
.diagnostic-print-report { display:none; background:#fff; color:#22302f; font:10pt/1.65 "PingFang SC","Microsoft YaHei",sans-serif; text-align:left; }
.diagnostic-print-report * { box-sizing:border-box; }
.dp-masthead { display:flex; align-items:center; justify-content:space-between; padding-bottom:5mm; border-bottom:1.5pt solid #244f49; font-size:8pt; letter-spacing:.08em; }
.dp-masthead b { font-size:13pt; }.dp-masthead b span { margin-left:3mm; font-size:8pt; font-weight:400; letter-spacing:0; }
.dp-eyebrow { margin:7mm 0 3mm; color:#28635b; font-size:8pt; font-weight:600; letter-spacing:.1em; }
h1 { font:600 32pt/1.3 "Songti SC","SimSun",serif; margin:7mm 0 5mm; overflow-wrap:anywhere; }h1 span { font-size:25pt; font-weight:400; }
.dp-url { color:#536562; overflow-wrap:anywhere; }.dp-meta { display:flex; gap:12mm; padding:5mm 0 7mm; color:#64706e; font-size:8pt; }.dp-meta b { color:#22302f; font-weight:500; }
.dp-summary { display:grid; grid-template-columns:58mm 1fr; border-top:1pt solid #b9c9c5; border-bottom:1pt solid #b9c9c5; margin-top:2mm; }
.dp-score { padding:6mm 6mm 6mm 0; }.dp-score>span { font-size:9pt; }.dp-score strong { display:block; font:500 48pt/1.15 Georgia,serif; margin:3mm 0; color:#244f49; }.dp-score small { font:10pt sans-serif; margin-left:2mm; }.dp-score p { font-size:8pt; color:#64706e; margin:0; }
.dp-conclusion { border-left:1pt solid #dce3e1; padding:6mm 0 6mm 7mm; }.dp-conclusion h2 { font-size:14pt; margin:0 0 4mm; }
p { margin:2.5mm 0; overflow-wrap:anywhere; }h3 { font-size:11pt; margin:3mm 0; }h2,h3 { break-after:avoid; }
.dp-statline { display:flex; justify-content:space-between; padding:5mm 0; border-bottom:1pt solid #dce3e1; gap:5mm; }.dp-statline span { font-size:9pt; }.dp-statline b { margin-left:3mm; font-size:15pt; color:#244f49; }
.dp-section-title { margin:7mm 0 3mm; font-size:13pt; }.dp-note { padding:4mm 5mm; border-left:2pt solid #86aaa2; background:#f3f6f5; font-size:9pt; color:#4b5d59; margin:5mm 0; }.dp-note h3 { margin-top:0; }
.dp-chapter { margin-top:9mm; break-before:auto; }.dp-cover + .dp-chapter { break-before:page; }.dp-chapter>.dp-eyebrow,.dp-intro { break-after:avoid; }.dp-chapter-title { font:600 23pt/1.4 "Songti SC","SimSun",serif; margin:0 0 4mm; padding-bottom:4mm; border-bottom:1.5pt solid #244f49; }.dp-intro,.dp-muted { color:#64706e; font-size:9pt; }
.dp-issue { padding:5mm 0; border-bottom:1pt solid #dce3e1; break-inside:avoid; }.dp-issue header { display:flex; align-items:baseline; gap:3mm; }.dp-issue h3 { margin:0; flex:1; }.dp-number { color:#28635b; font:600 16pt Georgia,serif; }.dp-issue header>span:last-child { color:#64706e; font-size:8pt; white-space:nowrap; }
dl { display:grid; grid-template-columns:18mm 1fr; gap:2mm 3mm; margin:4mm 0 0; font-size:9pt; }dt { color:#64706e; }dd { margin:0; overflow-wrap:anywhere; }
table { width:100%; border-collapse:collapse; table-layout:fixed; font-size:8.5pt; margin:4mm 0; }thead { display:table-header-group; }tr { break-inside:avoid; }th { text-align:left; background:#eef3f1; font-weight:600; }td,th { padding:2mm 2.5mm; border-bottom:1pt solid #dce3e1; vertical-align:top; overflow-wrap:anywhere; }td small { display:block; color:#64706e; font-size:7.5pt; margin-top:1mm; }.dp-passed { color:#28635b; }.dp-failed { color:#a34c35; }.dp-unavailable { color:#64706e; }
.dp-data-panel { break-inside:avoid; }.dp-answer { margin-top:7mm; }.dp-answer header { break-inside:avoid; break-after:avoid; }.dp-answer h3 { font-size:12pt; }.dp-response { break-inside:avoid; white-space:pre-wrap; font-size:9pt; line-height:1.8; orphans:3; widows:3; }.dp-source { font-size:8pt; color:#64706e; overflow-wrap:anywhere; }.dp-page-evidence p { break-inside:avoid; font-size:8.5pt; }.dp-evidence-line { font-size:9pt; }.dp-end { display:flex; justify-content:space-between; border-top:1pt solid #244f49; margin-top:10mm; padding-top:4mm; font-size:8pt; color:#64706e; }
@media print {
  .diagnostic-print-report { display:block!important; width:100%; }
  .diagnostic-print-report { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  @page { size:A4 portrait; margin:16mm 15mm 18mm; @bottom-left { content:"G-SNIPERS · 网站诊断报告"; font:8pt sans-serif; color:#64706e; } @bottom-right { content:counter(page) " / " counter(pages); font:8pt sans-serif; color:#64706e; } }
}
</style>
