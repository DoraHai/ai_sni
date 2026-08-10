<script setup>
import { onMounted, ref, watch } from 'vue'
import { fetchGeoAiTrends } from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { REPORT_GLOSSARY } from '../../utils/geoReportLabels'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const region = ref('')
const trends = ref([])
const impacts = ref([])
const summary = ref(null)

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    trends.value = []
    impacts.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await fetchGeoAiTrends(tenantId.value, {
      region: region.value || undefined,
    })
    trends.value = data.trends || []
    impacts.value = data.impacts || []
    summary.value = data.summary || null
  } catch (e) {
    error.value = e.message || '加载失败'
    trends.value = []
    impacts.value = []
  } finally {
    loading.value = false
  }
}

function regionLabel(r) {
  if (r === 'cn') return '国内'
  if (r === 'global') return '海外'
  return '双边'
}

function alertType(level) {
  if (level === 'error') return 'error'
  if (level === 'warning') return 'warning'
  return 'info'
}

function levelLabel(level) {
  if (level === 'error') return '紧急'
  if (level === 'warning') return '建议跟进'
  return '参考'
}

const TAG_LABEL = {
  llm_config: 'LLM 配置',
  content_gen: '内容生成',
  patrol: '巡检',
  engine_doubao: '豆包引擎',
  engine_kimi: 'Kimi 引擎',
  engine_perplexity: 'Perplexity',
  placements: '媒体阵地',
  placements_shortform: '短内容阵地',
  tone: '表达语气',
  longform: '长文信源',
  website: '官网',
  crawler_audit: '爬虫审计',
  schema: '结构化标记',
  citations: '引用',
}

function tagLabel(tag) {
  return TAG_LABEL[tag] || tag
}

watch([tenantId, region], load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">AI 动态与策略影响</div>
        <div class="page-desc">
          汇总国内外模型/爬虫公开变化，并结合本租户监测配置给出可执行建议（非实时新闻流）。
        </div>
      </div>
      <div class="header-actions">
        <el-select v-model="region" clearable placeholder="全部地区" style="width: 140px">
          <el-option label="国内" value="cn" />
          <el-option label="海外" value="global" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/engines">引擎配置</router-link>
        <router-link class="el-button" to="/geo/topic-heat">话题热度</router-link>
      </div>
    </div>

    <details class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.aiTrends" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div v-if="summary" class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">动态条目</div>
        <div class="kpi-value">{{ summary.trend_count || 0 }}</div>
        <div class="kpi-hint">当前筛选下的公开动态</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">策略建议</div>
        <div class="kpi-value">{{ summary.impact_count || 0 }}</div>
        <div class="kpi-hint">结合本租户数据生成</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">需跟进</div>
        <div class="kpi-value">{{ summary.warning || 0 }}</div>
        <div class="kpi-hint">warning 级及以上</div>
      </div>
    </div>

    <section class="geo-panel mb">
      <div class="panel-title">对本租户的策略建议</div>
      <p class="geo-panel-desc">优先处理「建议跟进」；点击「去处理」跳到对应配置页。</p>
      <div v-if="!impacts.length" class="geo-empty">
        <div class="empty-title">暂无策略建议</div>
        <div>完善引擎/巡检/官网渠道后，这里会出现更具体的动作项。</div>
      </div>
      <el-alert
        v-for="(a, idx) in impacts"
        :key="idx"
        :type="alertType(a.level)"
        :closable="false"
        show-icon
        class="impact-alert"
      >
        <template #title>
          <div class="impact-title">
            <span>
              <el-tag size="small" class="lvl" :type="alertType(a.level)">{{ levelLabel(a.level) }}</el-tag>
              {{ a.title }}
            </span>
            <router-link
              v-if="a.href && !String(a.href).startsWith('/diagnostic')"
              :to="a.href"
              class="impact-link"
            >
              去处理
            </router-link>
            <a
              v-else-if="a.href"
              :href="a.href"
              class="impact-link"
              target="_blank"
              rel="noopener"
            >去处理</a>
          </div>
        </template>
        <div>{{ a.detail }}</div>
      </el-alert>
    </section>

    <section class="geo-panel">
      <div class="panel-title">公开动态目录</div>
      <p class="geo-panel-desc">人工维护摘要；用于策略对齐，不替代行业资讯订阅。</p>
      <div v-if="!trends.length" class="geo-empty">暂无动态条目</div>
      <div v-else class="trend-list">
        <article v-for="t in trends" :key="t.id" class="trend-card">
          <div class="trend-top">
            <el-tag size="small">{{ regionLabel(t.region) }}</el-tag>
            <span class="trend-date">{{ t.published_on || '—' }}</span>
          </div>
          <h3>{{ t.title }}</h3>
          <p>{{ t.summary }}</p>
          <div class="trend-meta">{{ t.vendor }} · 来源 {{ t.source }}</div>
          <div class="tag-row">
            <el-tag
              v-for="tag in (t.impact_tags || [])"
              :key="tag"
              size="small"
              type="info"
              class="tag"
            >
              {{ tagLabel(tag) }}
            </el-tag>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.impact-alert { margin-bottom: 10px; }
.impact-title {
  display: flex; justify-content: space-between; gap: 12px; align-items: center; width: 100%;
}
.impact-link { font-size: 12px; font-weight: 500; }
.lvl { margin-right: 8px; vertical-align: middle; }
.trend-list {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;
}
.trend-card {
  border: 1px solid #e8edf5; border-radius: 12px; padding: 14px 16px; background: #fafbfc;
}
.trend-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.trend-date { font-size: 12px; color: #94a3b8; }
.trend-card h3 { margin: 0 0 8px; font-size: 14px; font-weight: 650; color: #0f172a; line-height: 1.4; }
.trend-card p { margin: 0; font-size: 13px; color: #475569; line-height: 1.55; }
.trend-meta { margin-top: 10px; font-size: 12px; color: #94a3b8; }
.tag-row { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.tag { margin: 0; }
</style>
