<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchLatestGeoAudit } from '../../api/geo'
import {
  fetchGeoCitationInsights,
  fetchGeoCompetitorInsights,
  fetchGeoContentStats,
  listGeoBusinesses,
  listGeoFacts,
} from '../../api/geoContent'
import GeoObjectSwitcher from '../../components/GeoObjectSwitcher.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const stats = ref(null)
const audit = ref(null)
const facts = ref([])
const businesses = ref([])
const cites = ref(null)
const comps = ref(null)

function clamp(n) {
  return Math.max(0, Math.min(100, Math.round(n)))
}
function tone(score) {
  if (score >= 80) return 'good'
  if (score >= 60) return 'warn'
  return 'bad'
}
function toneLabel(t) {
  if (t === 'good') return '表现良好'
  if (t === 'bad') return '优先修复'
  return '需要优化'
}

const rows = computed(() => {
  const s = stats.value || {}
  const biz = businesses.value || []
  const withProfile = biz.filter((b) => b.profile && (b.profile.summary || b.profile.product_name)).length
  const brandScore = biz.length ? clamp(50 + (withProfile / biz.length) * 50) : 40
  const verified = facts.value.filter((f) => f.trust_level === 'verified').length
  const contentScore = clamp(30 + Math.min(verified, 20) * 3 + Math.min(s.published || 0, 10) * 2)
  const parseScore = audit.value?.score != null ? clamp(audit.value.score) : 45
  const citeN = cites.value?.items?.length ?? cites.value?.domains?.length ?? 0
  const citeScore = clamp(40 + Math.min(citeN, 20) * 2)
  const missing = Number(s.prompts_brand_missing || 0)
  const compScore = clamp(80 - Math.min(missing, 20) * 2)
  return [
    {
      name: '品牌基础',
      score: brandScore,
      why: biz.length
        ? `${biz.length} 条业务中 ${withProfile} 条已有画像。`
        : '还没有业务线，AI 不知道该在哪些场景推荐你。',
      next: '补充品牌边界、目标客户和禁用表述。',
      tone: tone(brandScore),
      href: '/geo/brand',
    },
    {
      name: '内容质量',
      score: contentScore,
      why: `已核验事实 ${verified} 条，已发布文章 ${s.published ?? 0} 篇。`,
      next: '把关键答案放到首段，并补场景化案例。',
      tone: tone(contentScore),
      href: '/geo/knowledge',
    },
    {
      name: '网站可解析能力',
      score: parseScore,
      why: audit.value
        ? `最近一次体检 ${audit.value.score} 分。`
        : '还没有网站体检结果，FAQPage / Product / Article 可能不完整。',
      next: '补 JSON-LD、sitemap、Canonical，必要时打开诊断中心深检。',
      tone: tone(parseScore),
      href: '/diagnostic-center/',
    },
    {
      name: 'AI引用能力',
      score: citeScore,
      why: citeN ? `观察到来源 ${citeN} 个。` : '暂无明显引用，第三方来源不足。',
      next: '把案例、白皮书、帮助文档发到更可信的页面。',
      tone: tone(citeScore),
      href: '/geo/tasks',
    },
    {
      name: '竞品差距',
      score: compScore,
      why: missing
        ? `${missing} 条提问品牌未被推荐。`
        : '核心提问已有基础露出，对比类问题仍需盯防。',
      next: '生成竞品对比和选型框架内容。',
      tone: tone(compScore),
      href: '/geo/answers',
    },
  ]
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [s, a, f, b, ci, co] = await Promise.all([
      fetchGeoContentStats(tenantId.value),
      fetchLatestGeoAudit(tenantId.value).catch(() => ({ audit: null })),
      listGeoFacts(tenantId.value).catch(() => ({ items: [] })),
      listGeoBusinesses(tenantId.value, { status: 'active' }).catch(() => ({ items: [] })),
      fetchGeoCitationInsights(tenantId.value).catch(() => null),
      fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
    ])
    stats.value = s
    audit.value = a?.audit || a
    facts.value = f.items || []
    businesses.value = b.items || []
    cites.value = ci
    comps.value = co
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="官网结构优化"
    sub="看页面结构、可解析性和引用友好度，先改最影响 AI 摘取的地方"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" @click="router.push('/diagnostic-center/')">打开网站体检</button>
      <button class="gd-btn primary" @click="router.push('/geo/recommend')">去优化</button>
    </template>
    <div class="geo-dash">

      <GeoObjectSwitcher />
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="gv2-panel">
        <div class="gv2-panel-head">
          <div>
            <span class="gv2-kicker">体检报告</span>
            <h2>GEO优化诊断</h2>
            <p class="sub">每一项都说明状态、评分、原因和优化建议。</p>
          </div>
        </div>
        <div
          v-for="r in rows"
          :key="r.name"
          class="diagnosis-item"
          role="button"
          @click="r.href.startsWith('http') || r.href.startsWith('/diagnostic') ? (window.location.href = r.href) : router.push(r.href)"
        >
          <b>{{ r.name }}</b>
          <strong>{{ r.score }}</strong>
          <p>
            <span class="gv2-tag" :class="r.tone">{{ toneLabel(r.tone) }}</span><br />
            {{ r.why }}
          </p>
          <p>{{ r.next }}</p>
        </div>
      </section>
    </div>
  </GeoWorkbenchPage>
</template>
