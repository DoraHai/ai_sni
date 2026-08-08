<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchSeoKeywordDetail } from '../../api/seo'
import { currentTenantId } from '../../store/session'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const data = ref(null)
const engine = ref('baidu')
const detail = computed(() => data.value?.keyword || {})
const history = computed(() => data.value?.rank_history || [])

function fmt(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
const chartPoints = computed(() => {
  const values = history.value.filter((item) => item.rank != null)
  if (!values.length) return ''
  const width = 760; const height = 220; const padX = 28; const padY = 22
  const maxRank = Math.max(10, ...values.map((item) => item.rank))
  return values.map((item, index) => {
    const x = padX + index * ((width - padX * 2) / Math.max(values.length - 1, 1))
    const y = padY + ((item.rank - 1) / Math.max(maxRank - 1, 1)) * (height - padY * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

async function load() {
  if (!currentTenantId.value) { error.value = '请先选择客户'; return }
  loading.value = true; error.value = ''
  try {
    data.value = await fetchSeoKeywordDetail({ keywordId: route.params.keywordId, tenantId: currentTenantId.value, engine: engine.value, days: 90 })
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
watch([engine, currentTenantId, () => route.params.keywordId], load)
onMounted(load)
</script>

<template>
  <div class="detail-page" v-loading="loading">
    <button class="back" @click="router.push('/seo/keywords')">← 返回关键词资产</button>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <template v-if="data">
      <section class="detail-hero">
        <div><span>KEYWORD DETAIL / {{ engine.toUpperCase() }}</span><h1>{{ detail.keyword }}</h1><p>{{ detail.cluster || '未归类' }} · {{ detail.intent || '意图待判断' }} · {{ detail.landing_page || '尚未绑定承接页面' }}</p></div>
        <div class="engine"><button v-for="e in [{k:'baidu',n:'百度'},{k:'google',n:'Google'},{k:'bing',n:'Bing'}]" :key="e.k" :class="{active:engine===e.k}" @click="engine=e.k">{{ e.n }}</button></div>
      </section>
      <section class="metrics">
        <article><span>当前自然排名</span><strong>{{ detail.latest_rank ?? '未监控' }}</strong><small>{{ detail.rank_checked_at ? `更新于 ${new Date(detail.rank_checked_at).toLocaleString()}` : '尚无排名快照' }}</small></article>
        <article><span>月搜索量</span><strong>{{ fmt(detail.monthly_volume) }}</strong><small>自然搜索需求规模</small></article>
        <article><span>竞争难度</span><strong>{{ detail.difficulty == null ? '—' : `${detail.difficulty}/100` }}</strong><small>0–100 综合竞争评分</small></article>
        <article><span>优化优先级</span><strong>{{ detail.priority }}</strong><small>{{ detail.status }}</small></article>
      </section>
      <section class="chart-card">
        <header><div><span>01 / RANK HISTORY</span><h2>90 天自然排名趋势</h2></div><small>排名数字越小越好</small></header>
        <div v-if="history.length" class="chart">
          <svg viewBox="0 0 760 220" preserveAspectRatio="none" aria-label="自然排名趋势">
            <line v-for="n in 5" :key="n" x1="28" :y1="22 + (n-1)*44" x2="732" :y2="22 + (n-1)*44" />
            <polyline :points="chartPoints" />
          </svg>
        </div>
        <el-empty v-else description="暂无自然排名快照；请从关键词资产页记录或通过批量接口导入" />
      </section>
      <section class="history-card">
        <header><span>02 / SNAPSHOTS</span><h2>排名观测记录</h2></header>
        <el-table :data="[...history].reverse()" empty-text="暂无记录">
          <el-table-column label="采集时间" min-width="180"><template #default="{row}">{{ new Date(row.checked_at).toLocaleString() }}</template></el-table-column>
          <el-table-column prop="engine" label="搜索引擎" width="110" />
          <el-table-column prop="device" label="设备" width="100" />
          <el-table-column prop="region" label="地区" width="100" />
          <el-table-column label="自然排名" width="110"><template #default="{row}"><b>#{{ row.rank ?? '100+' }}</b></template></el-table-column>
          <el-table-column prop="result_url" label="排名页面" min-width="240" show-overflow-tooltip />
          <el-table-column prop="source" label="数据来源" width="110" />
        </el-table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.detail-page{min-height:100%;padding:26px;background:#f5f7fb;color:#17233d}.back{margin-bottom:14px;padding:0;border:0;background:none;color:#5270b6;font-weight:700;cursor:pointer}.detail-hero{display:flex;align-items:end;justify-content:space-between;gap:20px;padding:27px 30px;border:1px solid #dce4f2;border-radius:17px;background:#fff}.detail-hero span,.chart-card header span,.history-card header span{color:#2658d7;font:800 10px ui-monospace,monospace;letter-spacing:.12em}.detail-hero h1{margin:8px 0 6px;font:750 34px "Noto Serif SC","Songti SC",serif}.detail-hero p{margin:0;color:#778298}.engine{display:flex;padding:3px;border:1px solid #e0e5ee;border-radius:9px;background:#f5f7fa}.engine button{height:30px;padding:0 12px;border:0;border-radius:6px;background:transparent;color:#707a90;font-weight:700;cursor:pointer}.engine button.active{background:#fff;color:#2658d7;box-shadow:0 2px 8px rgba(31,45,75,.08)}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:15px 0}.metrics article{padding:19px 20px;border:1px solid #e3e8f1;border-radius:13px;background:#fff}.metrics span,.metrics small{display:block;color:#768198;font-size:11px}.metrics strong{display:block;margin:10px 0 5px;font-size:27px}.chart-card,.history-card{overflow:hidden;margin-top:15px;border:1px solid #e3e8f1;border-radius:15px;background:#fff}.chart-card header,.history-card header{display:flex;align-items:end;justify-content:space-between;padding:16px 19px;border-bottom:1px solid #edf0f5}.chart-card h2,.history-card h2{margin:4px 0 0;font-size:15px}.chart-card header small{color:#8b95a7}.chart{height:300px;padding:24px}.chart svg{width:100%;height:100%}.chart line{stroke:#e9edf4;stroke-width:1}.chart polyline{fill:none;stroke:#2658d7;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.el-alert{margin-bottom:14px}@media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:640px){.detail-page{padding:14px}.detail-hero{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr 1fr}.chart{height:230px;padding:12px}}
</style>
