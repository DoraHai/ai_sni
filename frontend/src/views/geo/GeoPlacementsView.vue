<script setup>
/**
 * 媒体 / 信源策略：对齐 geo-v2 media.html。
 * 数字来自布局清单、引用洞察、竞品洞察和 GEO 文章，不写入原型假数。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoMediaPlacement,
  deleteGeoMediaPlacement,
  fetchChannelBlueprint,
  fetchGeoCitationInsights,
  fetchGeoCompetitorInsights,
  listGeoContentTasks,
  listGeoMediaPlacements,
  patchGeoMediaPlacement,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { engineDisplay, fmtInt, pipelineLabel, taskStatusLabel } from '../../utils/geoReportLabels'
import { isPersistedGeoRow } from '../../utils/geoVirtualDefaults'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const statusFilter = ref('')
const qSearch = ref('')
const blueprint = ref(null)
const citations = ref(null)
const competitors = ref(null)
const tasks = ref([])
const dialogOpen = ref(false)
const saving = ref(false)
const editing = ref(null)

const P0_P1 = new Set(['P0', 'P1'])
const PLAYBOOKS = [
  { key: 'official', title: '官网可信底座', badge: '必做', tone: 'green', keys: ['official'] },
  {
    key: 'third',
    title: '高质量第三方',
    badge: '拉权威',
    tone: 'blue',
    keys: ['zhihu', 'wechat', 'media', 'ranking', 'toutiao', 'tech'],
  },
  { key: 'wiki', title: '百科与资料库', badge: '纠偏', tone: 'amber', keys: ['baike', 'baijia', 'quark'] },
]

const CHANNEL_OPTIONS = [
  { value: 'website', label: '官网' },
  { value: 'zhihu', label: '知乎' },
  { value: 'wechat', label: '公众号' },
  { value: 'news', label: '新闻媒体' },
  { value: 'wiki', label: '百科/文档' },
  { value: 'encyclopedia', label: '百科' },
  { value: 'other', label: '其他' },
]

const STATUS_META = {
  planned: { zh: '计划中', tone: 'ok' },
  in_progress: { zh: '进行中', tone: 'warn' },
  published: { zh: '已铺设', tone: 'info' },
  archived: { zh: '已归档', tone: 'muted' },
}

function emptyForm() {
  return {
    name: '',
    channel_type: 'website',
    channel_key: '',
    target_url: '',
    status: 'planned',
    priority: 0,
    authority_note: '',
  }
}
const form = ref(emptyForm())

function typeLabel(row) {
  const key = String(row.channel_type || '').toLowerCase()
  return CHANNEL_OPTIONS.find((c) => c.value === key)?.label || row.channel_type || '其他'
}

function statusMeta(row) {
  return STATUS_META[row.status] || { zh: row.status || '—', tone: 'muted' }
}

const filteredItems = computed(() => {
  let rows = items.value || []
  if (statusFilter.value) {
    rows = rows.filter((r) => r.status === statusFilter.value)
  }
  return rows
})
const pager = useClientPager(filteredItems, { pageSize: 20 })

const blueprintChannels = computed(() => blueprint.value?.all_channels || blueprint.value?.channels || [])

const placementByKey = computed(() => {
  const map = new Map()
  for (const row of items.value || []) {
    const key = String(row.channel_key || '').toLowerCase()
    if (key) map.set(key, row)
  }
  return map
})

const citeItems = computed(() => citations.value?.items || [])

const citedKeys = computed(() => {
  const keys = new Set()
  for (const it of citeItems.value) {
    if (it.blueprint_channel_key) keys.add(it.blueprint_channel_key)
    if (it.is_own_domain) keys.add('official')
  }
  return keys
})

const engineShareByKey = computed(() => {
  const map = new Map()
  for (const it of citeItems.value) {
    const key = it.blueprint_channel_key
    if (!key) continue
    const cur = map.get(key) || { total: 0, byEng: {} }
    const n = Number(it.cite_count || 0)
    cur.total += n
    const list = it.engines || []
    const share = list.length ? n / list.length : n
    for (const e of list) cur.byEng[e] = (cur.byEng[e] || 0) + share
    map.set(key, cur)
  }
  return map
})

const topCitedEngine = computed(() => {
  const counts = {}
  for (const it of citeItems.value) {
    const n = Number(it.cite_count || 0)
    const list = it.engines || []
    const share = list.length ? n / list.length : n
    for (const e of list) counts[e] = (counts[e] || 0) + share
  }
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
  return top ? engineDisplay(top[0]) : ''
})

const highWeightCount = computed(
  () => blueprintChannels.value.filter((ch) => P0_P1.has(ch.priority_band)).length,
)

const citedMediaCount = computed(() => {
  const domains = citations.value?.distinct_cited_domains
  if (domains != null) return domains
  return citedKeys.value.size
})

const pendingChannels = computed(() =>
  blueprintChannels.value.filter(
    (ch) => P0_P1.has(ch.priority_band) && !citedKeys.value.has(ch.channel_key),
  ),
)

const competitorPlatformCount = computed(() => {
  const keys = new Set()
  for (const it of competitors.value?.items || []) {
    for (const k of it.platform_keys || []) {
      if (k && k !== 'official') keys.add(k)
    }
  }
  return keys.size
})

const kpis = computed(() => [
  {
    label: '高权重信源',
    value: fmtInt(highWeightCount.value),
    hint: '蓝图 P0 / P1 阵地',
  },
  {
    label: 'AI 已引用媒体',
    value: fmtInt(citedMediaCount.value),
    hint: topCitedEngine.value ? `${topCitedEngine.value} 引用最多` : '观察期内被引域名',
  },
  {
    label: '待补渠道',
    value: fmtInt(pendingChannels.value.length),
    hint: pendingChannels.value.slice(0, 2).map((ch) => String(ch.name || '').split('（')[0].trim()).join(' / ') || '高价值渠道已有引用',
    warn: pendingChannels.value.length > 0,
  },
  {
    label: '竞品占位信源',
    value: competitorPlatformCount.value ? fmtInt(competitorPlatformCount.value) : '—',
    hint: competitorPlatformCount.value ? '竞品回答命中的阵地' : '暂无竞品占位',
    warn: competitorPlatformCount.value > 0,
  },
])

const playbooks = computed(() =>
  PLAYBOOKS.map((pb) => {
    const channels = blueprintChannels.value.filter((ch) => pb.keys.includes(ch.channel_key))
    return {
      ...pb,
        items: channels.slice(0, 3).map((ch) => ch.name),
    }
  }),
)

const matrixRows = computed(() => {
  const q = qSearch.value.trim().toLowerCase()
  return blueprintChannels.value
    .map((ch) => {
      const placement = placementByKey.value.get(String(ch.channel_key || '').toLowerCase())
      const cited = citedKeys.value.has(ch.channel_key)
      const eng = engineShareByKey.value.get(ch.channel_key)
      const engines = eng
        ? Object.entries(eng.byEng)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 2)
            .map(([e]) => engineDisplay(e))
        : []
      let badge = { text: '未布局', tone: 'red' }
      let next = '新增信源计划'
      if (placement?.status === 'published') {
        badge = { text: '可复用', tone: 'green' }
        next = '保持更新'
      } else if (placement?.status === 'in_progress') {
        badge = { text: '进行中', tone: 'amber' }
        next = '补已铺设 URL'
      } else if (cited) {
        badge = { text: '已有引用', tone: 'blue' }
        next = '收入布局清单'
      } else if (placement?.status === 'planned') {
        badge = { text: '计划中', tone: 'amber' }
        next = '开始铺设'
      }
      return {
        ...ch,
        fits: (ch.fits_groups || []).join('、') || '—',
        engines: engines.join(' / ') || '—',
        badge,
        next,
        placement,
      }
    })
    .filter((row) => {
      if (!q) return true
      return [row.name, row.why, row.fits, row.channel_key].join(' ').toLowerCase().includes(q)
    })
})

const publishPlan = computed(() =>
  (tasks.value || []).slice(0, 4).map((t) => ({
    id: t.id,
    title: t.title || t.question || `文章 #${t.id}`,
    badge: pipelineLabel(t.pipeline_step),
    tone: t.status === 'published' || t.status === 'ready' ? 'green' : t.status === 'needs_fix' ? 'amber' : 'blue',
    extra: taskStatusLabel(t.status),
  })),
)

const citeFeedback = computed(() => {
  const rows = []
  const byKey = new Map()
  for (const it of citeItems.value) {
    const key = it.blueprint_channel_key || it.domain
    if (!key) continue
    const cur = byKey.get(key) || {
      name: it.blueprint_channel_name || it.domain,
      n: 0,
    }
    cur.n += Number(it.cite_count || 0)
    byKey.set(key, cur)
  }
  for (const row of [...byKey.values()].sort((a, b) => b.n - a.n).slice(0, 3)) {
    rows.push({ text: `${row.name}已被引用`, value: `${fmtInt(row.n)} 次`, tone: 'up' })
  }
  for (const ch of pendingChannels.value.slice(0, 2)) {
    rows.push({ text: `${ch.name}尚未被引用`, value: '待处理', tone: 'down' })
  }
  return rows.slice(0, 4)
})

watch(statusFilter, () => pager.resetPage())

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [placeRes, bpRes, citeRes, compRes, taskRes] = await Promise.allSettled([
      listGeoMediaPlacements(tenantId.value),
      fetchChannelBlueprint(tenantId.value, null),
      fetchGeoCitationInsights(tenantId.value, { days: 30 }),
      fetchGeoCompetitorInsights(tenantId.value),
      listGeoContentTasks(tenantId.value, { limit: 4, offset: 0 }),
    ])
    items.value = placeRes.status === 'fulfilled' ? placeRes.value.items || [] : []
    blueprint.value = bpRes.status === 'fulfilled' ? bpRes.value : null
    citations.value = citeRes.status === 'fulfilled' ? citeRes.value : null
    competitors.value = compRes.status === 'fulfilled' ? compRes.value : null
    tasks.value = taskRes.status === 'fulfilled' ? taskRes.value.items || [] : []
    if (placeRes.status === 'rejected') {
      error.value = placeRes.reason?.message || '加载失败'
    }
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

function openCreate(prefill = null) {
  editing.value = null
  form.value = emptyForm()
  if (prefill) {
    form.value.name = prefill.name || ''
    form.value.channel_key = prefill.channel_key || ''
    form.value.channel_type = prefill.channel_type || 'website'
  }
  dialogOpen.value = true
}

function openEdit(row) {
  editing.value = isPersistedGeoRow(row) ? row : null
  form.value = {
    name: row.name || '',
    channel_type: row.channel_type || 'website',
    channel_key: row.channel_key || '',
    target_url: row.target_url || '',
    status: row.status || 'planned',
    priority: Number(row.priority) || 0,
    authority_note: row.authority_note || '',
  }
  dialogOpen.value = true
}

function onMatrixNext(row) {
  if (row.placement) openEdit(row.placement)
  else openCreate(row)
}

async function submitForm() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      channel_type: form.value.channel_type,
      channel_key: form.value.channel_key.trim() || null,
      target_url: form.value.target_url.trim() || null,
      status: form.value.status,
      priority: Number(form.value.priority) || 0,
      authority_note: form.value.authority_note.trim() || null,
    }
    if (isPersistedGeoRow(editing.value)) {
      await patchGeoMediaPlacement(tenantId.value, editing.value.id, payload)
      ElMessage.success('已保存')
    } else {
      await createGeoMediaPlacement({ tenant_id: tenantId.value, ...payload })
      ElMessage.success('已创建信源计划')
    }
    dialogOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveRow(row) {
  try {
    if (isPersistedGeoRow(row)) {
      await patchGeoMediaPlacement(tenantId.value, row.id, {
        status: row.status,
        published_url: row.published_url || null,
      })
      ElMessage.success('已保存')
    } else {
      await createGeoMediaPlacement({
        tenant_id: tenantId.value,
        name: row.name,
        channel_type: row.channel_type || 'other',
        channel_key: row.channel_key || null,
        target_url: row.target_url || null,
        authority_note: row.authority_note || null,
        status: row.status || 'planned',
        published_url: row.published_url || null,
        priority: Number(row.priority) || 0,
        priority_band: row.priority_band || null,
        fits_groups: row.fits_groups || [],
        citation_national: row.citation_national ?? null,
      })
      ElMessage.success('已加入信源计划')
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function remove(row) {
  if (!isPersistedGeoRow(row)) {
    ElMessage.warning('这是尚未保存的默认建议，无需删除')
    return
  }
  try {
    await ElMessageBox.confirm(`删除信源「${row.name}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await deleteGeoMediaPlacement(tenantId.value, row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="媒体 / 信源策略"
    :show-period="false"
    sub="同一套媒体资源可被 SEO / GEO 共用，但 GEO 更看重权威、可引用和信任链"
    :loading="loading"
  >
    <template #actions>
      <input v-model="qSearch" class="gd-search" placeholder="搜索媒体 / 信源…" />
      <router-link class="gd-btn" to="/geo/publishing">渠道库</router-link>
      <button class="gd-btn primary" type="button" @click="openCreate()">+ 新增信源计划</button>
    </template>

    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <div class="gd-kpis">
        <div v-for="k in kpis" :key="k.label" class="gd-card gd-stat">
          <div class="label">{{ k.label }}</div>
          <div class="value" :style="k.warn ? { color: 'var(--gd-warn)' } : {}">{{ k.value }}</div>
          <div class="delta hint">{{ k.hint }}</div>
        </div>
      </div>

      <div class="gd-playbooks">
        <div v-for="pb in playbooks" :key="pb.key" class="gd-card">
          <div class="gd-hd">
            <h3>{{ pb.title }}</h3>
            <span class="gd-badge" :class="pb.tone">{{ pb.badge }}</span>
          </div>
          <div class="gd-bd">
            <ul class="gd-sources">
              <li v-for="(line, i) in pb.items" :key="i">{{ line }}</li>
              <li v-if="!pb.items.length" class="gd-sub">暂无蓝图说明</li>
            </ul>
          </div>
        </div>
      </div>

      <div class="gd-card mb">
        <div class="gd-hd">
          <h3>信源优先级矩阵</h3>
          <span class="more">按当前引用与布局状态</span>
        </div>
        <div class="gd-bd" style="padding:0;overflow:auto">
          <table>
            <thead>
              <tr>
                <th>信源</th>
                <th>适合解决的问题</th>
                <th>偏好 AI 引擎</th>
                <th>当前状态</th>
                <th>下一步动作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrixRows" :key="row.channel_key">
                <td class="kw">{{ row.name }}</td>
                <td>{{ row.fits }}</td>
                <td>{{ row.engines }}</td>
                <td><span class="gd-badge" :class="row.badge.tone">{{ row.badge.text }}</span></td>
                <td>
                  <button class="next-link" type="button" @click="onMatrixNext(row)">{{ row.next }}</button>
                </td>
              </tr>
              <tr v-if="!matrixRows.length">
                <td colspan="5" class="gd-sub" style="padding:18px">无匹配信源</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="gd-bottom">
        <div class="gd-card">
          <div class="gd-hd">
            <h3>发布计划</h3>
            <router-link class="more" to="/geo/tasks">匹配 GEO 文章 →</router-link>
          </div>
          <div class="gd-bd">
            <ul v-if="publishPlan.length" class="gd-sources">
              <li v-for="t in publishPlan" :key="t.id">
                <span class="gd-badge" :class="t.tone">{{ t.badge }}</span>
                <router-link class="plan-link" :to="`/geo/tasks/${t.id}`">{{ t.title }}</router-link>
                <span class="gd-sub extra">{{ t.extra }}</span>
              </li>
            </ul>
            <p v-else class="gd-sub" style="margin:0">还没有 GEO 文章。去文章列表创建。</p>
          </div>
        </div>
        <div class="gd-card">
          <div class="gd-hd">
            <h3>引用效果回流</h3>
            <span class="gd-badge blue">30 天观察</span>
          </div>
          <div class="gd-bd">
            <ul v-if="citeFeedback.length" class="gd-sources">
              <li v-for="(row, i) in citeFeedback" :key="i">
                <span>{{ row.text }}</span>
                <b class="extra" :class="row.tone === 'up' ? 'rank-up' : 'rank-down'">{{ row.value }}</b>
              </li>
            </ul>
            <p v-else class="gd-sub" style="margin:0">观察期内还没有引用回流。去信源分析查看。</p>
            <router-link class="more-foot" to="/geo/citations">去信源分析 →</router-link>
          </div>
        </div>
      </div>

      <details class="layout-details">
        <summary>布局清单</summary>
        <div class="layout-toolbar">
          <el-select v-model="statusFilter" clearable placeholder="全部状态" style="width: 140px">
            <el-option label="计划中" value="planned" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已铺设" value="published" />
            <el-option label="已归档" value="archived" />
          </el-select>
          <button class="gd-btn" type="button" @click="load">刷新</button>
        </div>
        <el-table :data="pager.pagedItems" empty-text="暂无信源布局 · 点「新增信源计划」添加" size="small">
          <el-table-column label="名称" min-width="200">
            <template #default="{ row }">
              <div class="name">{{ row.name }}</div>
              <div v-if="row.authority_note" class="note">{{ row.authority_note }}</div>
            </template>
          </el-table-column>
          <el-table-column label="优先级" width="90">
            <template #default="{ row }">{{ row.priority_band || row.priority || '—' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ typeLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-select v-model="row.status" size="small" style="width: 100%">
                <el-option label="计划中" value="planned" />
                <el-option label="进行中" value="in_progress" />
                <el-option label="已铺设" value="published" />
                <el-option label="已归档" value="archived" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="已铺设 URL" min-width="180">
            <template #default="{ row }">
              <el-input v-model="row.published_url" size="small" placeholder="https://…" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="saveRow(row)">{{ row.virtual_default ? '加入计划' : '保存' }}</el-button>
              <el-button link @click="openEdit(row)">编辑</el-button>
              <el-button v-if="!row.virtual_default" link type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="geo-table-foot">
          <span>共 {{ pager.total }} 条</span>
          <el-pagination
            background
            layout="prev, pager, next"
            :total="pager.total"
            :page-size="pager.pageSize"
            :current-page="pager.page"
            @current-change="pager.onPageChange"
          />
        </div>
      </details>
    </div>

    <el-dialog
      v-model="dialogOpen"
      :title="editing ? '编辑信源计划' : '新增信源计划'"
      width="480px"
    >
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：官网帮助中心 / 知乎机构号" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.channel_type" style="width: 100%">
            <el-option
              v-for="c in CHANNEL_OPTIONS"
              :key="c.value"
              :label="c.label"
              :value="c.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="蓝图 key">
          <el-input v-model="form.channel_key" placeholder="可选" />
        </el-form-item>
        <el-form-item label="目标 URL">
          <el-input v-model="form.target_url" placeholder="https://" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="计划中" value="planned" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已铺设" value="published" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="布局理由">
          <el-input v-model="form.authority_note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 16px; }
.kw { font-weight: 650; }
.name { font-weight: 650; color: #1e2330; }
.note {
  margin-top: 3px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
}
.gd-playbooks {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.gd-sources .extra { margin-left: auto; flex: none; }
.next-link, .plan-link {
  background: none;
  border: 0;
  padding: 0;
  color: var(--gd-accent);
  font: inherit;
  cursor: pointer;
  text-align: left;
  text-decoration: none;
}
.more-foot {
  display: inline-block;
  margin-top: 10px;
  font-size: 12px;
  color: var(--gd-accent);
  text-decoration: none;
}
.layout-details {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--gd-border);
  border-radius: 12px;
  padding: 12px 16px;
}
.layout-details summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--gd-muted);
}
.layout-toolbar {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}
.geo-table-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  color: #6b7280;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .gd-playbooks { grid-template-columns: 1fr; }
}
</style>
