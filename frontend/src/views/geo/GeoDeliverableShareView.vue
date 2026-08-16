<script setup>
/**
 * 交付摘要公开分享页（bare + public）：只读展示 pack / Markdown。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import SampleCredibilityAlert from '../../components/SampleCredibilityAlert.vue'
import { getDeliverableByShareToken } from '../../api/geoContent'
import { fmtPct as fmtPctShared } from '../../utils/geoReportLabels'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const data = ref(null)

const pack = computed(() => data.value?.pack || null)
const hasSimulated = computed(
  () =>
    !!(
      data.value?.has_simulated_samples ||
      pack.value?.has_simulated_samples ||
      pack.value?.summary?.has_simulated_samples ||
      pack.value?.sample_composition?.has_simulated
    ),
)
const sampleLabel = computed(
  () =>
    pack.value?.sample_composition?.label ||
    pack.value?.summary?.sample_composition?.label ||
    '',
)

function fmtPct(v) {
  if (fmtPctShared) {
    try {
      return fmtPctShared(v)
    } catch {
      /* fallthrough */
    }
  }
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

async function load() {
  const token = String(route.params.shareToken || route.params.token || '').trim()
  if (!token) {
    error.value = '缺少分享令牌'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    data.value = await getDeliverableByShareToken(token)
  } catch (e) {
    error.value = e.message || '无法加载分享内容'
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="share-page" v-loading="loading">
    <header class="share-header">
      <div class="brand">GEO 交付摘要 · 只读分享</div>
      <div class="title">{{ data?.title || '加载中…' }}</div>
      <div v-if="data" class="meta">
        <span v-if="data.period_from || data.period_to">
          周期 {{ (data.period_from || '').slice(0, 10) }} ~
          {{ (data.period_to || '').slice(0, 10) }}
        </span>
        <span v-if="data.created_at"> · 存档于 {{ data.created_at }}</span>
      </div>
    </header>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      :closable="false"
      show-icon
      class="mb"
    />

    <SampleCredibilityAlert
      v-if="pack"
      :composition="pack.sample_composition || pack.summary?.sample_composition"
    />
    <el-alert
      v-if="pack?.impact_language"
      type="info"
      :closable="false"
      show-icon
      class="mb"
      :title="pack.impact_language"
    />

    <template v-if="pack">
      <div class="kpi-row">
        <div class="kpi">
          <div class="k">品牌提及率</div>
          <div class="v">{{ fmtPct(pack.summary?.visibility_mention_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="k">首选位率</div>
          <div class="v">{{ fmtPct(pack.summary?.visibility_top1_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="k">点名认知率</div>
          <div class="v">{{ fmtPct(pack.summary?.probe_recognition_rate) }}</div>
        </div>
        <div class="kpi">
          <div class="k">快照数</div>
          <div class="v">{{ pack.summary?.snapshots ?? '—' }}</div>
        </div>
      </div>

      <section v-if="data.markdown" class="md-block">
        <div class="sec-title">报告正文</div>
        <pre class="md-pre">{{ data.markdown }}</pre>
      </section>

      <section v-if="(pack.citations_top || []).length" class="sec">
        <div class="sec-title">Top 被引域名</div>
        <el-table :data="(pack.citations_top || []).slice(0, 15)" size="small">
          <el-table-column prop="domain" label="域名" min-width="160" />
          <el-table-column prop="cite_count" label="次数" width="80" />
        </el-table>
      </section>
    </template>

    <footer class="share-foot">
      只读链接 · 数据来自系统快照汇总 · 非全网抓取
    </footer>
  </div>
</template>

<style scoped>
.share-page {
  max-width: 880px;
  margin: 0 auto;
  padding: 28px 20px 48px;
  min-height: 100vh;
  background: linear-gradient(180deg, #f8fafc 0%, #fff 120px);
  color: #0f172a;
}
.share-header { margin-bottom: 20px; }
.brand {
  font-size: 12px;
  font-weight: 700;
  color: #185fa5;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}
.title {
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.3;
}
.meta {
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}
.mb { margin-bottom: 14px; }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.kpi {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.kpi .k { font-size: 12px; color: #64748b; font-weight: 600; }
.kpi .v { font-size: 22px; font-weight: 750; margin-top: 6px; }
.sec, .md-block {
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 16px;
}
.sec-title {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 12px;
}
.md-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
  margin: 0;
  max-height: 480px;
  overflow: auto;
}
.share-foot {
  margin-top: 24px;
  font-size: 12px;
  color: #94a3b8;
  text-align: center;
}
</style>
