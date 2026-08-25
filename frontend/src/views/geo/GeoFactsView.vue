<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createGeoFact, listGeoBusinesses, listGeoFacts, patchGeoFact, verifyGeoFact } from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { getGeoPrototypePageSurface } from '../../utils/geoEditorSurface'

const router = useRouter()
const prototypeSurface = getGeoPrototypePageSurface()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const trust = ref('')
const filterBusinessId = ref(null)
const businesses = ref([])
const pager = useClientPager(items, { pageSize: 20 })
const createOpen = ref(false)
const editOpen = ref(false)
const creating = ref(false)
const saving = ref(false)
const verifyOpen = ref(false)
const verifying = ref(false)
const verifyRow = ref(null)
const verifyForm = ref({
  excerpt: '',
  excerpt_locator: '',
  source_url: '',
  note: '',
})
const form = ref({
  title: '',
  statement: '',
  fact_type: 'product',
  source_name: '',
  source_url: '',
  trust_level: 'needs_review',
  business_id: null,
})
const editForm = ref({
  id: null,
  title: '',
  statement: '',
  fact_type: 'product',
  source_name: '',
  source_url: '',
  trust_level: 'needs_review',
  business_id: null,
})

function bizName(id) {
  return businesses.value.find((b) => b.id === id)?.name || (id ? `#${id}` : '租户共用')
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = {}
    if (trust.value) params.trust_level = trust.value
    if (filterBusinessId.value) params.business_id = filterBusinessId.value
    const [data, b] = await Promise.all([
      listGeoFacts(tenantId.value, params),
      businesses.value.length
        ? Promise.resolve({ items: businesses.value })
        : listGeoBusinesses(tenantId.value, { status: 'active' }).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || businesses.value
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.title.trim() || !form.value.statement.trim() || !form.value.source_name.trim()) {
    ElMessage.warning('标题、陈述与来源名必填')
    return
  }
  creating.value = true
  try {
    await createGeoFact({
      tenant_id: tenantId.value,
      title: form.value.title.trim(),
      statement: form.value.statement.trim(),
      fact_type: form.value.fact_type,
      source_name: form.value.source_name.trim(),
      source_url: form.value.source_url.trim() || null,
      trust_level: form.value.trust_level,
      business_id: form.value.business_id || null,
    })
    ElMessage.success('已创建事实')
    createOpen.value = false
    form.value = {
      title: '',
      statement: '',
      fact_type: 'product',
      source_name: '',
      source_url: '',
      trust_level: 'needs_review',
      business_id: filterBusinessId.value || null,
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function openVerify(row) {
  verifyRow.value = row
  verifyForm.value = {
    excerpt: (row.statement || '').slice(0, 160),
    excerpt_locator: '',
    source_url: row.source_url || '',
    note: '',
  }
  verifyOpen.value = true
}

async function submitVerify() {
  if (!verifyRow.value) return
  if (!verifyForm.value.excerpt.trim() || !verifyForm.value.excerpt_locator.trim()) {
    ElMessage.warning('请填写摘录原文和定位（例如「官网首页第二段」）')
    return
  }
  if (!verifyForm.value.source_url.trim()) {
    ElMessage.warning('核验必须填写来源 URL')
    return
  }
  verifying.value = true
  try {
    await verifyGeoFact(tenantId.value, verifyRow.value.id, {
      excerpt: verifyForm.value.excerpt.trim(),
      excerpt_locator: verifyForm.value.excerpt_locator.trim(),
      source_url: verifyForm.value.source_url.trim(),
      note: verifyForm.value.note.trim() || null,
    })
    ElMessage.success(`已核验 #${verifyRow.value.id}`)
    verifyOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '核验失败')
  } finally {
    verifying.value = false
  }
}

async function archive(row) {
  try {
    await patchGeoFact(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success(`已归档 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message || '归档失败')
  }
}

function openEdit(row) {
  editForm.value = {
    id: row.id,
    title: row.title || '',
    statement: row.statement || '',
    fact_type: row.fact_type || 'product',
    source_name: row.source_name || '',
    source_url: row.source_url || '',
    trust_level: row.trust_level || 'needs_review',
    business_id: row.business_id || null,
  }
  editOpen.value = true
}

async function submitEdit() {
  if (!editForm.value.title.trim() || !editForm.value.statement.trim()) {
    ElMessage.warning('标题与陈述必填')
    return
  }
  saving.value = true
  try {
    await patchGeoFact(tenantId.value, editForm.value.id, {
      title: editForm.value.title.trim(),
      statement: editForm.value.statement.trim(),
      fact_type: editForm.value.fact_type,
      source_name: editForm.value.source_name.trim() || null,
      source_url: editForm.value.source_url.trim() || null,
      trust_level: editForm.value.trust_level,
      business_id: editForm.value.business_id || null,
    })
    ElMessage.success('已保存')
    editOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const FACT_TYPE_LABELS = {
  product: '产品',
  case: '案例',
  metric: '指标',
  policy: '政策',
  other: '其他',
}
const typeCards = computed(() => [
  { key: 'product', title: '产品', text: '功能说明、版本差异、适用场景' },
  { key: 'case', title: '案例', text: '行业、规模、结果数据' },
  { key: 'metric', title: '指标', text: '可核验的效果与数据' },
  { key: 'policy', title: '政策 / 边界', text: '承诺、限制与禁用表述' },
  { key: 'other', title: '官网 / 上传资料', text: '可被内容生成复用的材料' },
].map((g) => ({
  ...g,
  count: items.value.filter((i) => i.fact_type === g.key).length,
})))

const knowledgeGaps = computed(() => {
  const cards = typeCards.value
  const caseN = cards.find((c) => c.key === 'case')?.count || 0
  const faqish = (cards.find((c) => c.key === 'other')?.count || 0)
  const out = []
  if (caseN < 3) {
    out.push({
      title: '案例缺口',
      text: `当前仅 ${caseN} 条案例事实`,
      reason: '补案例后可支撑选型类提问。',
    })
  }
  if (faqish < 10) {
    out.push({
      title: 'FAQ / 资料缺口',
      text: '价格、版本和替代方案类事实偏少',
      reason: '这些内容更容易被 AI 摘取为答案。',
    })
  }
  return out
})

const knowledgeAnswer = computed(() => ({
  now: [
    '我现在怎么样？',
    `知识库 ${items.value.length} 条，已核验 ${items.value.filter((i) => i.trust_level === 'verified').length} 条。`,
  ],
  why: ['为什么？', 'AI 更容易引用有明确场景、结果数据和更新时间的事实。'],
  next: [
    '下一步怎么办？',
    knowledgeGaps.value[0]?.reason || '优先把待核验事实核验到 3 条以上再生成文章。',
  ],
}))
const TRUST_LABELS = {
  verified: '已核验',
  needs_review: '待核验',
  draft: '草稿',
}
const STATUS_LABELS = {
  active: '生效中',
  archived: '已归档',
}

function factTypeLabel(v) {
  return FACT_TYPE_LABELS[v] || v || '—'
}
function trustLabel(v) {
  return TRUST_LABELS[v] || v || '—'
}
function statusLabel(v) {
  return STATUS_LABELS[v] || v || '—'
}

watch([tenantId, trust, filterBusinessId], () => {
  pager.resetPage()
  load()
})
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="知识库"
    :show-period="false"
    sub="维护品牌事实、案例和 FAQ，供 GEO 文章与 AI 可见度引用"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn primary" @click="createOpen = true">+ 新建事实</button>
    </template>
    <div class="geo-dash">

    <NeedHintAlert v-if="prototypeSurface.showKnowledgeHealth" />
    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
    <div v-if="prototypeSurface.showKnowledgeHealth" class="gv2-grid-3" style="margin-bottom: 14px;">
      <button
        v-for="c in typeCards"
        :key="c.key"
        type="button"
        class="gv2-card"
        style="text-align:left;cursor:pointer;"
        @click="form.fact_type = c.key; createOpen = true"
      >
        <b>{{ c.title }}</b>
        <p>{{ c.text }}</p>
        <span class="gv2-tag">{{ c.count }} 条</span>
      </button>
    </div>
    <section v-if="prototypeSurface.showKnowledgeHealth && knowledgeGaps.length" class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">素材健康度</span>
          <h2>下一步补什么</h2>
        </div>
      </div>
      <div class="recommend-list">
        <div v-for="g in knowledgeGaps" :key="g.title" class="gv2-card">
          <b>{{ g.title }}</b>
          <p>{{ g.text }}</p>
          <p>{{ g.reason }}</p>
        </div>
      </div>
    </section>

    <div class="filters">
      <el-select v-model="trust" clearable placeholder="信任级别" style="width: 168px">
        <el-option label="已核验" value="verified" />
        <el-option label="待核验" value="needs_review" />
        <el-option label="草稿" value="draft" />
      </el-select>
      <el-select v-if="prototypeSurface.showKnowledgeHealth" v-model="filterBusinessId" clearable filterable placeholder="业务线（含共用）" style="width: 200px">
        <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <span class="toolbar-hint">母稿会优先使用已核验资料</span>
    </div>

    <div class="geo-table-shell">
      <el-table :data="pager.pagedItems" empty-text="暂无事实">
        <el-table-column v-if="prototypeSurface.showKnowledgeHealth" prop="id" label="ID" width="72" />
        <el-table-column label="标题 / 陈述" min-width="260">
          <template #default="{ row }">
            <div class="title">{{ row.title }}</div>
            <div class="sub">{{ row.statement }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ factTypeLabel(row.fact_type) }}</template>
        </el-table-column>
        <el-table-column label="业务" width="120">
          <template #default="{ row }">{{ bizName(row.business_id) }}</template>
        </el-table-column>
        <el-table-column label="来源" min-width="120">
          <template #default="{ row }">
            <div>{{ row.source_name || '—' }}</div>
            <div v-if="row.source_url" class="sub">{{ row.source_url }}</div>
          </template>
        </el-table-column>
        <el-table-column label="信任" width="160">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.trust_level === 'verified' ? 'success' : row.trust_level === 'needs_review' ? 'warning' : 'info'"
              effect="light"
            >
              {{ trustLabel(row.trust_level) }}
            </el-tag>
            <div v-if="row.verification?.verified_at" class="sub">
              {{ row.verification.excerpt_locator || '已记录摘录' }}
              · {{ String(row.verification.verified_at).slice(0, 16).replace('T', ' ') }}
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="prototypeSurface.showKnowledgeHealth" label="状态" width="90">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button
              v-if="row.trust_level !== 'verified' && row.status === 'active'"
              type="primary"
              link
              @click="openVerify(row)"
            >核验</el-button>
            <el-button
              v-if="row.status === 'active'"
              type="danger"
              link
              @click="archive(row)"
            >归档</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="geo-pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="pager.total"
          :page-size="pager.pageSize"
          :current-page="pager.page"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="pager.onPageChange"
          @size-change="pager.onSizeChange"
        />
      </div>
    </div>

    <el-dialog v-model="editOpen" title="编辑事实" width="560px" class="geo-form-dialog">
      <el-form label-width="88px" label-position="right" class="geo-dialog-form">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="editForm.statement" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.fact_type" style="width: 100%">
            <el-option label="产品" value="product" />
            <el-option label="案例" value="case" />
            <el-option label="指标" value="metric" />
            <el-option label="政策" value="policy" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名">
          <el-input v-model="editForm.source_name" />
        </el-form-item>
        <el-form-item label="来源 URL">
          <el-input v-model="editForm.source_url" />
        </el-form-item>
        <el-form-item label="所属业务">
          <el-select v-model="editForm.business_id" clearable filterable placeholder="租户共用" style="width: 100%">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="信任级">
          <el-select v-model="editForm.trust_level" style="width: 100%">
            <el-option label="待核验" value="needs_review" />
            <el-option label="草稿" value="draft" />
          </el-select>
          <div class="field-help">已核验只能通过「核验」填写摘录依据后生效</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createOpen" title="新建事实" width="560px" class="geo-form-dialog">
      <el-form label-width="88px" label-position="right" class="geo-dialog-form">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="简短可检索的事实标题" />
        </el-form-item>
        <el-form-item label="陈述" required>
          <el-input v-model="form.statement" type="textarea" :rows="3" placeholder="可核验的陈述原文" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.fact_type" style="width: 100%">
            <el-option label="产品" value="product" />
            <el-option label="案例" value="case" />
            <el-option label="指标" value="metric" />
            <el-option label="政策" value="policy" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属业务">
          <el-select v-model="form.business_id" clearable filterable placeholder="租户共用" style="width: 100%">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源名" required>
          <el-input v-model="form.source_name" />
        </el-form-item>
        <el-form-item label="来源 URL">
          <el-input v-model="form.source_url" />
        </el-form-item>
        <el-form-item label="信任级">
          <el-select v-model="form.trust_level" style="width: 100%">
            <el-option label="待核验" value="needs_review" />
            <el-option label="草稿" value="draft" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="verifyOpen" title="核验事实" width="560px" class="geo-form-dialog">
      <p class="verify-hint">
        核验不是点一下过关。请从源页摘录陈述中的原文，并写明定位（章节/段落/锚点），同时留下核验 URL。
      </p>
      <el-form label-width="96px" label-position="right" class="geo-dialog-form">
        <el-form-item label="摘录原文" required>
          <el-input
            v-model="verifyForm.excerpt"
            type="textarea"
            :rows="3"
            placeholder="必须是陈述里的连续原文"
          />
        </el-form-item>
        <el-form-item label="摘录定位" required>
          <el-input
            v-model="verifyForm.excerpt_locator"
            placeholder="例如：官网首页「产品能力」第二段"
          />
        </el-form-item>
        <el-form-item label="来源 URL" required>
          <el-input v-model="verifyForm.source_url" placeholder="https://" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="verifyForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="verifyOpen = false">取消</el-button>
        <el-button type="primary" :loading="verifying" @click="submitVerify">确认核验</el-button>
      </template>
    </el-dialog>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.title { font-weight: 650; color: #0f172a; }
.sub {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 3px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.field-help { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.verify-hint { font-size: 13px; color: #475569; line-height: 1.5; margin: 0 0 12px; }
.toolbar-hint {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
}
</style>
