<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createSeoKeyword, createSeoRankSnapshot, fetchSeoKeywords, importSeoKeywords, updateSeoKeyword } from '../../api/seo'
import { currentTenantId, session } from '../../store/session'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const result = ref({ items: [], total: 0, stats: {} })
const engine = ref('baidu')
const filters = reactive({ q: '', priority: '', intent: '', status: 'active' })
const dialogOpen = ref(false)
const rankDialogOpen = ref(false)
const importDialogOpen = ref(false)
const importText = ref('')
const editing = ref(null)
const rankTarget = ref(null)
const saving = ref(false)

const form = reactive({
  keyword: '', cluster: '', intent: '', monthly_volume: null, difficulty: null,
  priority: 'P2', landing_page: '', status: 'active', notes: '',
})
const rankForm = reactive({ rank: null, result_url: '', device: 'desktop', region: '全国', checked_at: '' })

const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.keywords'))
const stats = computed(() => result.value.stats || {})
const coverage = computed(() => {
  const active = Number(stats.value.active || 0)
  return active ? Math.round(Number(stats.value.with_landing_page || 0) / active * 100) : 0
})

function fmt(value) {
  return value == null ? '—' : Number(value).toLocaleString('zh-CN')
}
function rankDelta(row) {
  if (row.rank_delta == null || row.rank_delta === 0) return '—'
  return `${row.rank_delta > 0 ? '↑' : '↓'}${Math.abs(row.rank_delta)}`
}
function resetForm(row = null) {
  editing.value = row
  Object.assign(form, {
    keyword: row?.keyword || '', cluster: row?.cluster || '', intent: row?.intent || '',
    monthly_volume: row?.monthly_volume ?? null, difficulty: row?.difficulty ?? null,
    priority: row?.priority || 'P2', landing_page: row?.landing_page || '',
    status: row?.status || 'active', notes: row?.notes || '',
  })
  dialogOpen.value = true
}
function openRank(row) {
  rankTarget.value = row
  Object.assign(rankForm, {
    rank: row.latest_rank ?? null,
    result_url: row.rank_url || row.landing_page || '',
    device: 'desktop', region: '全国', checked_at: new Date().toISOString().slice(0, 16),
  })
  rankDialogOpen.value = true
}

async function load() {
  if (!currentTenantId.value) {
    result.value = { items: [], total: 0, stats: {} }
    error.value = '请先在右上角选择客户'
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await fetchSeoKeywords({
      tenantId: currentTenantId.value,
      ...filters,
      engine: engine.value,
      pageSize: 100,
    })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function saveKeyword() {
  if (!form.keyword.trim()) return ElMessage.warning('请填写关键词')
  saving.value = true
  try {
    const payload = {
      cluster: form.cluster || null,
      intent: form.intent || null,
      monthly_volume: form.monthly_volume,
      difficulty: form.difficulty,
      priority: form.priority,
      landing_page: form.landing_page || null,
      status: form.status,
      notes: form.notes || null,
    }
    if (editing.value) {
      await updateSeoKeyword({ keywordId: editing.value.id, tenantId: currentTenantId.value, payload })
    } else {
      await createSeoKeyword({ tenant_id: currentTenantId.value, keyword: form.keyword.trim(), ...payload })
    }
    dialogOpen.value = false
    ElMessage.success(editing.value ? '关键词已更新' : '关键词已加入资产库')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function saveRank() {
  if (!rankTarget.value) return
  saving.value = true
  try {
    await createSeoRankSnapshot({
      tenant_id: currentTenantId.value,
      keyword_id: rankTarget.value.id,
      engine: engine.value,
      device: rankForm.device,
      region: rankForm.region,
      rank: rankForm.rank,
      result_url: rankForm.result_url || null,
      checked_at: rankForm.checked_at ? new Date(rankForm.checked_at).toISOString() : new Date().toISOString(),
      subject_type: 'own',
      source: 'manual',
    })
    rankDialogOpen.value = false
    ElMessage.success('自然排名快照已记录')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function importKeywords() {
  const rows = importText.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!rows.length) return ElMessage.warning('请至少填写一个关键词')
  const items = rows.map((line) => {
    const [keyword, cluster, intent, monthlyVolume, difficulty, priority, landingPage] = line.split(/\t|,/).map((value) => value?.trim())
    return {
      tenant_id: currentTenantId.value,
      keyword,
      cluster: cluster || null,
      intent: intent || null,
      monthly_volume: monthlyVolume ? Number(monthlyVolume) : null,
      difficulty: difficulty ? Number(difficulty) : null,
      priority: ['P0', 'P1', 'P2', 'P3'].includes(priority) ? priority : 'P2',
      landing_page: landingPage || null,
    }
  }).filter((item) => item.keyword)
  if (!items.length) return ElMessage.warning('没有识别到有效关键词')
  saving.value = true
  try {
    const response = await importSeoKeywords({ tenant_id: currentTenantId.value, items })
    importDialogOpen.value = false
    importText.value = ''
    ElMessage.success(`已导入 ${response.created} 个关键词${response.skipped?.length ? `，跳过 ${response.skipped.length} 个重复项` : ''}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

let searchTimer
watch(() => filters.q, () => { clearTimeout(searchTimer); searchTimer = setTimeout(load, 260) })
watch([() => filters.priority, () => filters.intent, () => filters.status, engine, currentTenantId], load)
onMounted(load)
</script>

<template>
  <div class="seo-page">
    <section class="seo-hero">
      <div>
        <span class="eyebrow">SEO / KEYWORD ASSETS</span>
        <h1>关键词资产</h1>
        <p>管理自然搜索关键词、搜索需求、优化优先级与承接页面。这里的数据与 SEM 广告关键词完全分离。</p>
      </div>
      <div v-if="canEdit" class="hero-actions"><button class="secondary-action" type="button" @click="importDialogOpen = true">批量导入</button><button class="primary-action" type="button" @click="resetForm()">＋ 添加关键词</button></div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />

    <section class="metric-grid">
      <article><span>有效关键词</span><strong>{{ fmt(stats.active || 0) }}</strong><small>SEO 自然搜索词库</small></article>
      <article><span>月搜索需求</span><strong>{{ fmt(stats.monthly_volume || 0) }}</strong><small>由规划师或人工导入</small></article>
      <article><span>承接页覆盖</span><strong>{{ coverage }}%</strong><small>{{ fmt(stats.with_landing_page || 0) }} 个词已绑定页面</small></article>
      <article><span>高优先级</span><strong>{{ fmt(stats.high_priority || 0) }}</strong><small>P0–P1 待重点投入</small></article>
    </section>

    <section class="asset-panel">
      <header class="panel-head">
        <div><span class="section-no">01</span><h2>关键词资产清单</h2></div>
        <div class="engine-switch" aria-label="搜索引擎">
          <button v-for="item in [{k:'baidu',n:'百度'},{k:'google',n:'Google'},{k:'bing',n:'Bing'}]" :key="item.k" :class="{ active: engine === item.k }" @click="engine = item.k">{{ item.n }}</button>
        </div>
      </header>
      <div class="filters">
        <el-input v-model="filters.q" clearable placeholder="搜索关键词、词簇或承接页面" class="search-input" />
        <el-select v-model="filters.priority" placeholder="全部优先级" clearable><el-option v-for="p in ['P0','P1','P2','P3']" :key="p" :label="p" :value="p" /></el-select>
        <el-select v-model="filters.intent" placeholder="全部意图" clearable><el-option v-for="i in ['产品','价格','方案','指南','对比','品牌']" :key="i" :label="i" :value="i" /></el-select>
        <el-select v-model="filters.status"><el-option label="有效" value="active" /><el-option label="已暂停" value="paused" /><el-option label="已归档" value="archived" /></el-select>
        <span class="result-count">{{ result.total }} 个关键词</span>
      </div>

      <el-table v-loading="loading" :data="result.items" class="asset-table" empty-text="暂无关键词，点击“添加关键词”建立第一项 SEO 资产">
        <el-table-column label="关键词 / 词簇" min-width="210">
          <template #default="{ row }"><button class="keyword-link" @click="router.push(`/seo/keywords/${row.id}`)">{{ row.keyword }}</button><small>{{ row.cluster || '未归类' }}</small></template>
        </el-table-column>
        <el-table-column prop="intent" label="搜索意图" width="100"><template #default="{ row }"><span class="soft-tag">{{ row.intent || '待判断' }}</span></template></el-table-column>
        <el-table-column label="月搜索量" width="110"><template #default="{ row }"><b>{{ fmt(row.monthly_volume) }}</b></template></el-table-column>
        <el-table-column label="难度" width="120"><template #default="{ row }"><div class="difficulty"><i><b :style="{ width: `${row.difficulty || 0}%` }" /></i><span>{{ row.difficulty ?? '—' }}</span></div></template></el-table-column>
        <el-table-column prop="priority" label="优先级" width="90"><template #default="{ row }"><span class="priority" :class="row.priority.toLowerCase()">{{ row.priority }}</span></template></el-table-column>
        <el-table-column label="自然排名" width="120"><template #default="{ row }"><div class="rank"><strong>{{ row.latest_rank ?? '未监控' }}</strong><em :class="{ up: row.rank_delta > 0, down: row.rank_delta < 0 }">{{ rankDelta(row) }}</em></div></template></el-table-column>
        <el-table-column label="承接页面" min-width="190"><template #default="{ row }"><span v-if="row.landing_page" class="url-cell">{{ row.landing_page }}</span><span v-else class="missing">待绑定</span></template></el-table-column>
        <el-table-column label="操作" width="185" fixed="right"><template #default="{ row }"><div class="row-actions"><button @click="router.push(`/seo/keywords/${row.id}`)">详情</button><button v-if="canEdit" @click="openRank(row)">记排名</button><button v-if="canEdit" @click="resetForm(row)">编辑</button></div></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogOpen" :title="editing ? '编辑关键词资产' : '添加关键词资产'" width="620px">
      <el-form label-position="top" class="form-grid">
        <el-form-item label="关键词" class="full"><el-input v-model="form.keyword" :disabled="!!editing" maxlength="200" /></el-form-item>
        <el-form-item label="词簇"><el-input v-model="form.cluster" placeholder="例如：CRM 核心词" /></el-form-item>
        <el-form-item label="搜索意图"><el-select v-model="form.intent" clearable><el-option v-for="i in ['产品','价格','方案','指南','对比','品牌']" :key="i" :label="i" :value="i" /></el-select></el-form-item>
        <el-form-item label="月搜索量"><el-input-number v-model="form.monthly_volume" :min="0" controls-position="right" /></el-form-item>
        <el-form-item label="竞争难度（0–100）"><el-input-number v-model="form.difficulty" :min="0" :max="100" controls-position="right" /></el-form-item>
        <el-form-item label="优先级"><el-select v-model="form.priority"><el-option v-for="p in ['P0','P1','P2','P3']" :key="p" :label="p" :value="p" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="form.status"><el-option label="有效" value="active" /><el-option label="暂停" value="paused" /><el-option label="归档" value="archived" /></el-select></el-form-item>
        <el-form-item label="承接页面" class="full"><el-input v-model="form.landing_page" placeholder="https://example.com/product" /></el-form-item>
        <el-form-item label="运营备注" class="full"><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveKeyword">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="rankDialogOpen" title="记录自然排名快照" width="520px">
      <p class="dialog-context">{{ rankTarget?.keyword }} · {{ engine }}</p>
      <el-form label-position="top" class="form-grid">
        <el-form-item label="自然排名（1–100）"><el-input-number v-model="rankForm.rank" :min="1" :max="100" /></el-form-item>
        <el-form-item label="设备"><el-select v-model="rankForm.device"><el-option label="桌面端" value="desktop" /><el-option label="移动端" value="mobile" /></el-select></el-form-item>
        <el-form-item label="地区"><el-input v-model="rankForm.region" /></el-form-item>
        <el-form-item label="采集时间"><el-input v-model="rankForm.checked_at" type="datetime-local" /></el-form-item>
        <el-form-item label="排名页面 URL" class="full"><el-input v-model="rankForm.result_url" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="rankDialogOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRank">保存快照</el-button></template>
    </el-dialog>

    <el-dialog v-model="importDialogOpen" title="批量导入关键词资产" width="680px">
      <p class="dialog-tip">每行一个关键词，支持制表符或逗号分隔：关键词、词簇、意图、月搜索量、难度、优先级、承接页。</p>
      <el-input v-model="importText" type="textarea" :rows="10" placeholder="CRM系统,CRM核心词,产品,3600,58,P0,https://example.com/crm&#10;CRM价格,CRM商业词,价格,1200,42,P1,https://example.com/pricing" />
      <template #footer><el-button @click="importDialogOpen = false">取消</el-button><el-button type="primary" :loading="saving" @click="importKeywords">开始导入</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.seo-page{--ink:#17233d;--blue:#2658d7;--line:#e3e8f1;--muted:#768198;min-height:100%;padding:26px;background:radial-gradient(circle at 80% -20%,rgba(38,88,215,.09),transparent 36%),#f5f7fb;color:var(--ink)}
.seo-hero{display:flex;align-items:end;justify-content:space-between;gap:30px;padding:27px 30px;border:1px solid #dce4f2;border-radius:17px;background:#fff;box-shadow:0 15px 44px rgba(30,49,88,.05)}
.eyebrow{color:var(--blue);font:800 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.13em}.seo-hero h1{margin:9px 0 7px;font:750 34px/1.1 "Noto Serif SC","Songti SC",serif;letter-spacing:-.04em}.seo-hero p{max-width:760px;margin:0;color:var(--muted);line-height:1.7}.hero-actions{display:flex;gap:8px;flex:none}.primary-action,.secondary-action{height:40px;padding:0 18px;border-radius:9px;font-weight:700;cursor:pointer}.primary-action{border:0;color:#fff;background:var(--blue);box-shadow:0 8px 20px rgba(38,88,215,.22)}.secondary-action{border:1px solid #cbd5e7;color:#48618f;background:#fff}
.el-alert{margin-top:14px}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:15px 0}.metric-grid article{padding:19px 20px;border:1px solid var(--line);border-radius:13px;background:#fff}.metric-grid span,.metric-grid small{display:block;color:var(--muted);font-size:11px}.metric-grid strong{display:block;margin:10px 0 5px;font-size:28px;letter-spacing:-.04em}
.asset-panel{overflow:hidden;border:1px solid var(--line);border-radius:15px;background:#fff}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:16px 19px;border-bottom:1px solid #edf0f5}.panel-head>div:first-child{display:flex;align-items:center;gap:10px}.panel-head h2{margin:0;font-size:15px}.section-no{color:#8ea0c7;font:700 11px ui-monospace,monospace}.engine-switch{display:flex;padding:3px;border:1px solid #dfe4ed;border-radius:9px;background:#f5f7fa}.engine-switch button{height:29px;padding:0 12px;border:0;border-radius:6px;background:transparent;color:#707a90;font-size:11px;font-weight:700;cursor:pointer}.engine-switch button.active{background:#fff;color:var(--blue);box-shadow:0 2px 8px rgba(31,45,75,.08)}
.filters{display:flex;gap:9px;padding:14px 17px}.filters .el-select{width:130px}.search-input{max-width:330px}.result-count{align-self:center;margin-left:auto;color:var(--muted);font-size:11px}.asset-table{--el-table-border-color:#edf0f5}.keyword-link{display:block;padding:0;border:0;background:none;color:var(--ink);font-weight:750;cursor:pointer}.keyword-link:hover{color:var(--blue)}.asset-table small{display:block;margin-top:4px;color:#929bad}.soft-tag{padding:4px 8px;border-radius:999px;background:#f0f2f6;color:#667187;font-size:11px}.priority{width:31px;height:25px;display:grid;place-items:center;border-radius:7px;font-size:10px;font-weight:850}.priority.p0{background:#fde8e7;color:#a73732}.priority.p1{background:#fff0df;color:#a15b1d}.priority.p2{background:#eaf0ff;color:#2854b5}.priority.p3{background:#eff1f5;color:#6e788a}.difficulty{display:flex;align-items:center;gap:7px}.difficulty i{width:58px;height:5px;overflow:hidden;border-radius:9px;background:#edf0f4}.difficulty i b{display:block;height:100%;background:var(--blue)}.difficulty span{font-size:11px}.rank{display:flex;align-items:baseline;gap:6px}.rank strong{font-size:17px}.rank em{font-style:normal;font-size:10px;color:#8b94a3}.rank em.up{color:#25805e}.rank em.down{color:#c64f49}.url-cell{display:block;overflow:hidden;color:#4767ae;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.missing{color:#c04d46;font-size:11px}.row-actions{display:flex;gap:5px}.row-actions button{padding:5px 7px;border:1px solid #e0e5ee;border-radius:6px;background:#fff;color:#627089;font-size:10.5px;cursor:pointer}.row-actions button:hover{border-color:#9eb2e8;color:var(--blue)}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.form-grid .full{grid-column:1/-1}.form-grid :deep(.el-select),.form-grid :deep(.el-input-number){width:100%}.dialog-context,.dialog-tip{margin:-4px 0 15px;color:var(--muted);font-size:12px;line-height:1.65}
@media(max-width:1050px){.metric-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.seo-page{padding:14px}.seo-hero{align-items:flex-start;flex-direction:column}.metric-grid{grid-template-columns:1fr 1fr}.filters{flex-wrap:wrap}.search-input{max-width:none;width:100%}.result-count{margin-left:0}.form-grid{grid-template-columns:1fr}.form-grid .full{grid-column:auto}}@media(max-width:480px){.metric-grid{grid-template-columns:1fr}}
</style>
