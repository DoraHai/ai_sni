<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchLatestGeoAudit,
  generateGeoAdvice,
  generateGeoAssets,
  runGeoAudit,
} from '../../api/geo'
import { session } from '../../store/session'

const tenantId = computed(() => session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null))
const url = ref('')
const audit = ref(null)
const loading = ref(false)
const adviceLoading = ref(false)
const assetsLoading = ref(false)
const error = ref('')
const activeAsset = ref('jsonld')

const scoreTone = computed(() => {
  const score = audit.value?.score ?? 0
  if (score >= 80) return 'good'
  if (score >= 60) return 'fair'
  return 'risk'
})
const problemCounts = computed(() => {
  const rows = audit.value?.problems || []
  return {
    critical: rows.filter((item) => item.severity === 'critical').length,
    high: rows.filter((item) => item.severity === 'high').length,
    medium: rows.filter((item) => item.severity === 'medium').length,
    low: rows.filter((item) => item.severity === 'low').length,
  }
})
const currentStep = computed(() => {
  if (!audit.value) return 1
  if (!audit.value.advice?.length) return 2
  if (!audit.value.json_ld || !audit.value.llms_text) return 3
  return 4
})
const jsonLdText = computed(() => audit.value?.json_ld ? JSON.stringify(audit.value.json_ld, null, 2) : '')

function normalizeUrl(value) {
  const input = String(value || '').trim()
  if (!input) return ''
  return /^https?:\/\//i.test(input) ? input : `https://${input}`
}

async function loadLatest() {
  if (!tenantId.value) return
  try {
    const result = await fetchLatestGeoAudit(tenantId.value)
    audit.value = result.audit
    if (result.audit?.url) url.value = result.audit.url
  } catch {
    // 首次进入没有历史结果不打扰用户。
  }
}

async function startAudit() {
  error.value = ''
  const normalized = normalizeUrl(url.value)
  if (!normalized) {
    error.value = '请输入需要诊断的网站地址'
    return
  }
  loading.value = true
  audit.value = null
  try {
    audit.value = await runGeoAudit({ tenantId: tenantId.value, url: normalized })
    url.value = audit.value.final_url || normalized
    ElMessage.success('GEO 诊断完成')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function createAdvice() {
  if (!audit.value) return
  adviceLoading.value = true
  try {
    audit.value = await generateGeoAdvice({ tenantId: tenantId.value, auditId: audit.value.id })
    ElMessage.success(audit.value.advice_source === 'ai' ? 'AI 整改方案已生成' : '整改方案已生成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    adviceLoading.value = false
  }
}

async function createAssets() {
  if (!audit.value) return
  assetsLoading.value = true
  try {
    audit.value = await generateGeoAssets({ tenantId: tenantId.value, auditId: audit.value.id })
    ElMessage.success('JSON-LD 与 llms.txt 已生成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    assetsLoading.value = false
  }
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

function downloadText(text, filename, type = 'text/plain') {
  const blob = new Blob([text], { type: `${type};charset=utf-8` })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  URL.revokeObjectURL(href)
}

function severityLabel(value) {
  return { critical: '阻断', high: '高优先', medium: '中优先', low: '建议' }[value] || value
}

watch(tenantId, () => {
  audit.value = null
  url.value = ''
  loadLatest()
})
onMounted(loadLatest)
</script>

<template>
  <div class="geo-workbench">
    <section class="hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">GENERATIVE ENGINE READINESS</span>
        <h1>让官网成为<br><em>AI 愿意引用的答案</em></h1>
        <p>从技术可访问性、实体语义、内容结构和可信信号四个维度，找出影响品牌被 AI 理解与引用的问题。</p>
      </div>
      <form class="audit-form" @submit.prevent="startAudit">
        <label for="geo-url">网站地址</label>
        <div class="url-control" :class="{ busy: loading }">
          <span class="protocol-mark">↗</span>
          <input id="geo-url" v-model="url" type="text" inputmode="url" placeholder="example.com" :disabled="loading">
          <button type="submit" :disabled="loading || !tenantId">
            <span v-if="loading" class="spinner" />
            {{ loading ? '正在读取与诊断…' : '开始 GEO 诊断' }}
          </button>
        </div>
        <small v-if="error" class="form-error">{{ error }}</small>
        <small v-else>仅读取公开页面，不执行写入；通常在 20 秒内完成。</small>
      </form>
      <div class="signal-grid" aria-hidden="true">
        <span v-for="n in 28" :key="n" :style="{ '--n': n }" />
      </div>
    </section>

    <nav class="progress-rail" aria-label="诊断流程">
      <div v-for="(item, index) in ['输入网址', '问题清单', '整改建议', '生成资产']" :key="item" :class="{ active: currentStep >= index + 1, current: currentStep === index + 1 }">
        <b>{{ index + 1 }}</b><span>{{ item }}</span>
      </div>
    </nav>

    <section v-if="!audit && !loading" class="empty-state">
      <div class="radar">
        <i /><i /><i /><b />
      </div>
      <div>
        <span>READY TO SCAN</span>
        <h2>一次诊断，得到一份可以交付的 GEO 修复清单</h2>
        <p>系统会检查 16 项基础信号，并生成可直接交给技术、内容和运营团队的整改动作。</p>
      </div>
    </section>

    <template v-if="audit">
      <section class="result-overview">
        <div class="score-card" :class="scoreTone">
          <div class="score-orbit">
            <strong>{{ audit.score }}</strong>
            <span>/ 100</span>
          </div>
          <div>
            <small>GEO 基础健康度</small>
            <h2>{{ audit.score >= 80 ? '基础良好' : audit.score >= 60 ? '存在提升空间' : '需要优先整改' }}</h2>
            <p>{{ audit.snapshot?.passed || 0 }} / {{ audit.snapshot?.total || 0 }} 项检查通过</p>
          </div>
        </div>

        <div class="page-card">
          <span class="card-kicker">本次诊断页面</span>
          <h3>{{ audit.page_title || '页面未设置标题' }}</h3>
          <a :href="audit.final_url" target="_blank" rel="noopener">{{ audit.final_url }}</a>
          <p>{{ audit.page_description || '页面未设置 Meta Description。' }}</p>
          <div class="page-facts">
            <span>正文 {{ audit.snapshot?.content_units || 0 }} 单元</span>
            <span>Schema {{ audit.snapshot?.schema_types?.length || 0 }} 类</span>
            <span>外部信源 {{ audit.snapshot?.external_link_count || 0 }} 个</span>
          </div>
        </div>

        <div class="issue-card">
          <span class="card-kicker">待处理问题</span>
          <strong>{{ audit.problems.length }}</strong>
          <div class="issue-bars">
            <span class="critical" :style="{ '--value': problemCounts.critical }">阻断 {{ problemCounts.critical }}</span>
            <span class="high" :style="{ '--value': problemCounts.high }">高 {{ problemCounts.high }}</span>
            <span class="medium" :style="{ '--value': problemCounts.medium }">中 {{ problemCounts.medium }}</span>
            <span class="low" :style="{ '--value': problemCounts.low }">建议 {{ problemCounts.low }}</span>
          </div>
        </div>
      </section>

      <section class="work-section">
        <header class="section-head">
          <div><span>01 / FINDINGS</span><h2>问题清单</h2></div>
          <p>每项都附有现场证据、扣分和验收方向，可直接拆成整改任务。</p>
        </header>
        <div v-if="audit.problems.length" class="finding-list">
          <article v-for="(item, index) in audit.problems" :key="item.code">
            <div class="finding-index">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="finding-body">
              <div class="finding-title">
                <span class="severity" :class="item.severity">{{ severityLabel(item.severity) }}</span>
                <span class="category">{{ item.category }}</span>
                <em>-{{ item.deduction }}</em>
              </div>
              <h3>{{ item.title }}</h3>
              <p class="evidence">{{ item.evidence }}</p>
              <p class="recommendation">{{ item.recommendation }}</p>
            </div>
            <span v-if="item.automatable" class="auto-mark">可自动生成</span>
          </article>
        </div>
        <div v-else class="all-clear">所有基础检查均已通过，可以继续进行行业级内容深度评估。</div>
      </section>

      <section class="work-section advice-section">
        <header class="section-head">
          <div><span>02 / ACTION PLAN</span><h2>整改建议</h2></div>
          <button v-if="!audit.advice.length" class="section-action" :disabled="adviceLoading" @click="createAdvice">
            {{ adviceLoading ? '正在组织整改方案…' : audit.ai_enabled ? '生成 AI 整改方案' : '生成整改方案' }}
          </button>
          <span v-else class="source-chip">{{ audit.advice_source === 'ai' ? 'AI 生成 · 已按规则约束' : '规则引擎生成' }}</span>
        </header>
        <div v-if="audit.advice.length" class="advice-grid">
          <article v-for="(item, index) in audit.advice" :key="`${item.code}-${index}`">
            <span class="advice-no">{{ String(index + 1).padStart(2, '0') }}</span>
            <div><small>{{ severityLabel(item.priority) }}</small><h3>{{ item.title }}</h3></div>
            <p>{{ item.action }}</p>
            <dl><dt>预期作用</dt><dd>{{ item.expected_impact }}</dd><dt>验收标准</dt><dd>{{ item.acceptance }}</dd></dl>
          </article>
        </div>
        <div v-else class="locked-panel">
          <span>✦</span><p>基于上方问题清单生成按优先级排序的执行计划。</p>
        </div>
      </section>

      <section class="work-section asset-section">
        <header class="section-head">
          <div><span>03 / DELIVERABLES</span><h2>结构化资产</h2></div>
          <button v-if="!audit.json_ld" class="section-action" :disabled="assetsLoading" @click="createAssets">
            {{ assetsLoading ? '正在生成…' : '生成 JSON-LD 与 llms.txt' }}
          </button>
        </header>
        <div v-if="audit.json_ld" class="asset-console">
          <div class="asset-tabs">
            <button :class="{ active: activeAsset === 'jsonld' }" @click="activeAsset = 'jsonld'">JSON-LD</button>
            <button :class="{ active: activeAsset === 'llms' }" @click="activeAsset = 'llms'">llms.txt</button>
            <span />
            <button class="utility" @click="copyText(activeAsset === 'jsonld' ? jsonLdText : audit.llms_text, activeAsset === 'jsonld' ? 'JSON-LD' : 'llms.txt')">复制</button>
            <button class="utility" @click="downloadText(activeAsset === 'jsonld' ? jsonLdText : audit.llms_text, activeAsset === 'jsonld' ? 'schema.json' : 'llms.txt', activeAsset === 'jsonld' ? 'application/json' : 'text/plain')">下载</button>
          </div>
          <pre>{{ activeAsset === 'jsonld' ? jsonLdText : audit.llms_text }}</pre>
          <footer>
            <span>发布前请由网站负责人核验名称、描述和页面地址。</span>
            <span>{{ activeAsset === 'jsonld' ? '建议放入页面 <head> 的 application/ld+json 脚本中' : '建议发布到网站根目录 /llms.txt' }}</span>
          </footer>
        </div>
        <div v-else class="locked-panel">
          <span>{ }</span><p>生成不虚构事实的品牌实体 Schema 和站点 AI 导览文件。</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.geo-workbench {
  --ink: #142b32;
  --muted: #657980;
  --line: #dce5e2;
  --paper: #f7f8f3;
  --acid: #c8f169;
  --teal: #147d72;
  min-height: calc(100vh - 88px);
  color: var(--ink);
  font-family: "IBM Plex Sans", "Noto Sans SC", "PingFang SC", sans-serif;
}
.hero-panel {
  position: relative;
  min-height: 302px;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(360px, .82fr) minmax(460px, 1.18fr);
  align-items: end;
  gap: 58px;
  padding: 46px 52px 42px;
  color: #f4f8f2;
  background: #122b31;
  border-radius: 3px 3px 0 0;
}
.hero-panel:after { content:""; position:absolute; inset:0; pointer-events:none; background:linear-gradient(118deg,transparent 45%,rgba(200,241,105,.08)); }
.hero-copy,.audit-form { position:relative; z-index:2; }
.eyebrow,.section-head span,.empty-state>div>span { color:var(--acid); font:700 10px/1.2 "IBM Plex Mono",monospace; letter-spacing:.2em; }
.hero-copy h1 { margin:14px 0 16px; font:500 clamp(34px,3.4vw,52px)/1.03 Georgia,"Songti SC",serif; letter-spacing:-.035em; }
.hero-copy h1 em { color:var(--acid); font-style:normal; }
.hero-copy p { max-width:550px; margin:0; color:#afc0c0; font-size:14px; line-height:1.7; }
.audit-form { margin-bottom:8px; }
.audit-form label { display:block; margin-bottom:9px; color:#c7d4d2; font-size:12px; font-weight:700; }
.url-control { height:66px; display:grid; grid-template-columns:45px 1fr auto; align-items:center; padding:6px; border:1px solid #486066; background:#f7f8f3; box-shadow:0 18px 50px rgba(0,0,0,.2); }
.protocol-mark { color:var(--teal); text-align:center; font-size:22px; }
.url-control input { min-width:0; border:0; outline:0; padding:0 8px; color:#183239; background:transparent; font:600 16px/1 "IBM Plex Mono",monospace; }
.url-control button,.section-action { height:52px; border:0; padding:0 24px; color:#11282e; background:var(--acid); font-weight:800; cursor:pointer; }
.url-control button:disabled,.section-action:disabled { opacity:.55; cursor:wait; }
.audit-form>small { display:block; min-height:18px; margin-top:9px; color:#7f9698; font-size:11px; }
.audit-form .form-error { color:#ffb4a6; }
.spinner { display:inline-block; width:12px; height:12px; margin-right:7px; border:2px solid rgba(20,43,50,.25); border-top-color:#142b32; border-radius:50%; animation:spin .8s linear infinite; }
.signal-grid { position:absolute; right:-20px; top:-20px; width:360px; height:180px; opacity:.12; transform:rotate(-8deg); display:grid; grid-template-columns:repeat(7,1fr); place-items:center; }
.signal-grid span { width:3px; height:3px; border-radius:50%; background:var(--acid); box-shadow:0 0 0 1px var(--acid); }
@keyframes spin { to { transform:rotate(360deg); } }

.progress-rail { display:grid; grid-template-columns:repeat(4,1fr); border:1px solid var(--line); border-top:0; background:#fff; }
.progress-rail div { position:relative; display:flex; align-items:center; gap:10px; min-height:58px; padding:0 22px; color:#98a5a5; border-right:1px solid var(--line); font-size:12px; }
.progress-rail div:last-child { border:0; }
.progress-rail div:after { content:""; position:absolute; left:0; right:100%; bottom:-1px; height:3px; background:var(--teal); transition:right .35s; }
.progress-rail div.active { color:var(--ink); }
.progress-rail div.active:after { right:0; }
.progress-rail b { width:23px; height:23px; display:grid; place-items:center; border:1px solid currentColor; border-radius:50%; font:600 10px "IBM Plex Mono",monospace; }
.progress-rail .current b { color:#fff; background:var(--teal); border-color:var(--teal); }

.empty-state { min-height:330px; display:grid; grid-template-columns:220px minmax(0,620px); place-content:center; align-items:center; gap:55px; border:1px solid var(--line); border-top:0; background:var(--paper); }
.empty-state h2 { margin:10px 0 12px; font:500 30px/1.25 Georgia,"Songti SC",serif; }
.empty-state p { color:var(--muted); line-height:1.7; }
.radar { position:relative; width:170px; height:170px; border:1px solid #aebebb; border-radius:50%; background:repeating-radial-gradient(circle,transparent 0 27px,rgba(20,125,114,.13) 28px 29px); }
.radar:before,.radar:after { content:""; position:absolute; background:#b7c5c2; }.radar:before{left:50%;top:0;width:1px;height:100%}.radar:after{top:50%;left:0;width:100%;height:1px}.radar i{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--teal);box-shadow:0 0 0 5px rgba(20,125,114,.12)}.radar i:first-child{left:52px;top:43px}.radar i:nth-child(2){right:34px;top:76px}.radar i:nth-child(3){left:76px;bottom:28px}.radar b{position:absolute;inset:50%;transform-origin:0 0;width:76px;height:1px;background:linear-gradient(90deg,var(--teal),transparent);animation:sweep 4s linear infinite}@keyframes sweep{to{transform:rotate(360deg)}}

.result-overview { display:grid; grid-template-columns:1fr 1.45fr .72fr; gap:1px; margin-top:18px; border:1px solid var(--line); background:var(--line); }
.result-overview>div { min-height:190px; padding:27px; background:#fff; }
.score-card { display:flex; align-items:center; gap:22px; }
.score-orbit { width:108px; height:108px; display:grid; place-content:center; flex:none; border:7px solid #e1e8e5; border-top-color:var(--teal); border-radius:50%; text-align:center; }
.score-orbit strong { font:500 38px/1 Georgia,serif; }.score-orbit span{font-size:10px;color:var(--muted)}
.score-card small,.card-kicker { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.12em; }
.score-card h2 { margin:6px 0; font:500 20px Georgia,"Songti SC",serif; }.score-card p{margin:0;color:var(--muted);font-size:11px}
.score-card.good .score-orbit{border-top-color:#35a36f}.score-card.fair .score-orbit{border-top-color:#d49b35}.score-card.risk .score-orbit{border-top-color:#d76353}
.page-card h3 { margin:13px 0 5px; font-size:17px; }.page-card>a{display:block;overflow:hidden;color:var(--teal);font:500 11px "IBM Plex Mono",monospace;text-overflow:ellipsis;white-space:nowrap}.page-card>p{height:42px;overflow:hidden;margin:13px 0;color:var(--muted);font-size:12px;line-height:1.7}.page-facts{display:flex;gap:7px;flex-wrap:wrap}.page-facts span{padding:5px 8px;background:#eef4f1;color:#506b69;font-size:10px}
.issue-card>strong { display:block; margin:8px 0 15px; font:500 45px Georgia,serif; }.issue-bars{display:grid;gap:4px}.issue-bars span{display:block;padding:4px 7px;color:#536463;background:linear-gradient(90deg,var(--bar) calc(var(--value)*15%),#f0f3f1 0);font-size:9px}.issue-bars .critical{--bar:#ffd8d0}.issue-bars .high{--bar:#ffe4c2}.issue-bars .medium{--bar:#fff0bd}.issue-bars .low{--bar:#dfece8}

.work-section { margin-top:18px; border:1px solid var(--line); background:#fff; }
.section-head { min-height:94px; display:flex; align-items:center; justify-content:space-between; gap:30px; padding:20px 28px; border-bottom:1px solid var(--line); }
.section-head span { color:var(--teal); }.section-head h2{margin:5px 0 0;font:500 27px Georgia,"Songti SC",serif}.section-head>p{max-width:480px;margin:0;color:var(--muted);font-size:12px;line-height:1.65;text-align:right}
.section-action { height:42px; }.source-chip{padding:7px 11px;color:var(--teal)!important;background:#eaf4f1;font:600 10px/1 sans-serif!important;letter-spacing:0!important}
.finding-list article { position:relative; display:grid; grid-template-columns:58px 1fr auto; gap:20px; padding:23px 28px; border-bottom:1px solid #edf1ef; }
.finding-list article:last-child{border:0}.finding-index{padding-top:4px;color:#a4b1af;font:500 12px "IBM Plex Mono",monospace}.finding-title{display:flex;align-items:center;gap:8px}.severity,.category{padding:4px 7px;font-size:9px!important;letter-spacing:0!important}.severity{color:#73372f!important;background:#ffe0da}.severity.high{color:#805318!important;background:#ffebcb}.severity.medium{color:#6f641a!important;background:#fff4bd}.severity.low{color:#3d6861!important;background:#e0efeb}.category{color:#637573!important;background:#eff3f1}.finding-title em{color:#c7594d;font:600 10px "IBM Plex Mono",monospace;font-style:normal}.finding-body h3{margin:10px 0 6px;font-size:15px}.finding-body p{margin:5px 0;font-size:11px;line-height:1.6}.evidence{color:#7b8c8a}.recommendation{color:#334f4d}.auto-mark{align-self:start;padding:5px 8px!important;color:var(--teal)!important;border:1px solid #bcd8d2;font:600 9px/1 sans-serif!important;letter-spacing:0!important}
.all-clear{padding:42px;text-align:center;color:var(--teal)}

.advice-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:1px; background:var(--line); }
.advice-grid article { display:grid; grid-template-columns:45px 1fr; gap:8px 16px; padding:25px; background:#fff; }
.advice-no{grid-row:1/4;color:#b7c4c1;font:500 20px Georgia,serif}.advice-grid small{color:var(--teal);font-size:9px}.advice-grid h3{margin:5px 0;font-size:14px}.advice-grid p{grid-column:2;margin:3px 0;color:#304b49;font-size:12px;line-height:1.65}.advice-grid dl{grid-column:2;display:grid;grid-template-columns:58px 1fr;gap:5px;margin:8px 0 0;padding-top:10px;border-top:1px solid #edf1ef;font-size:10px}.advice-grid dt{color:#8b9a98}.advice-grid dd{margin:0;color:#536866}
.locked-panel { min-height:128px; display:flex; align-items:center; justify-content:center; gap:15px; color:#839390; background:repeating-linear-gradient(-45deg,#fafbf8,#fafbf8 8px,#f7f9f5 8px,#f7f9f5 16px); }.locked-panel span{color:var(--teal);font:500 22px Georgia,serif!important;letter-spacing:0!important}.locked-panel p{font-size:12px}
.asset-console{margin:24px;border:1px solid #223c42;background:#122b31}.asset-tabs{height:48px;display:flex;align-items:center;border-bottom:1px solid #344c51}.asset-tabs span{flex:1}.asset-tabs button{height:48px;padding:0 18px;border:0;border-right:1px solid #344c51;color:#91aaa9;background:transparent;cursor:pointer}.asset-tabs button.active{color:var(--acid);background:#1a373d}.asset-tabs .utility{height:30px;margin-right:8px;border:1px solid #4a6266;font-size:10px}.asset-console pre{min-height:260px;max-height:520px;overflow:auto;margin:0;padding:25px;color:#d6e6dd;font:11px/1.75 "IBM Plex Mono","SFMono-Regular",monospace;white-space:pre-wrap}.asset-console footer{display:flex;justify-content:space-between;gap:20px;padding:12px 20px;color:#78908f;border-top:1px solid #344c51;font-size:9px}
@media(max-width:1050px){.hero-panel{grid-template-columns:1fr;gap:30px}.result-overview{grid-template-columns:1fr 1fr}.issue-card{grid-column:1/-1}.advice-grid{grid-template-columns:1fr}}
@media(max-width:700px){.hero-panel{padding:34px 22px}.url-control{height:auto;grid-template-columns:36px 1fr}.url-control input{height:48px}.url-control button{grid-column:1/-1;width:100%}.progress-rail div{padding:0 9px}.progress-rail span{display:none}.result-overview{grid-template-columns:1fr}.issue-card{grid-column:auto}.section-head{align-items:flex-start;flex-direction:column}.section-head>p{text-align:left}.finding-list article{grid-template-columns:32px 1fr;padding:20px 16px}.auto-mark{display:none}.asset-console{margin:12px}.asset-console footer{flex-direction:column}}
</style>
