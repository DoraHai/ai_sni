<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoUnit,
  listGeoBusinesses,
  listGeoDailyMetrics,
  listGeoPrompts,
  listGeoUnits,
  patchGeoUnit,
} from '../../api/geoContent'
import GeoV2Page from '../../components/GeoV2Page.vue'
import NeedHintAlert from '../../components/NeedHintAlert.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'
import { fmtPct } from '../../utils/geoReportLabels'

const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const businesses = ref([])
const units = ref([])
const prompts = ref([])
const daily = ref([])
const filterBusinessId = ref(null)
const createOpen = ref(false)
const creating = ref(false)
const editOpen = ref(false)
const saving = ref(false)
const qSearch = ref('')
const form = ref({ business_id: null, name: '', keyword: '', description: '' })
const editForm = ref({ id: null, business_id: null, name: '', keyword: '', description: '' })

const filteredUnits = computed(() => {
  let rows = units.value || []
  if (filterBusinessId.value) {
    rows = rows.filter((u) => u.business_id === filterBusinessId.value)
  }
  const q = qSearch.value.trim().toLowerCase()
  if (q) {
    rows = rows.filter((u) =>
      `${u.name || ''} ${u.keyword || ''} ${u.description || ''}`.toLowerCase().includes(q),
    )
  }
  return rows
})

function bizName(id) {
  return businesses.value.find((b) => b.id === id)?.name || `#${id}`
}

function promptCount(unitId) {
  return prompts.value.filter((p) => p.unit_id === unitId).length
}

function unitMention(unitId) {
  const row = daily.value.find((d) => d.unit_id === unitId)
  return row?.brand_mention_rate
}

const cards = computed(() =>
  filteredUnits.value.slice(0, 3).map((u) => {
    const n = promptCount(u.id)
    const rate = unitMention(u.id)
    return {
      name: u.keyword || u.name,
      value: rate != null ? fmtPct(rate) : n ? `${n} 问` : '待测',
      reason: n
        ? `已关联 ${n} 条 AI 提问。关键词用来发现用户会向 AI 问什么。`
        : '还没有 AI 提问。先从关键词生成提问，再追踪推荐率。',
      action: n ? '查看提问' : '生成提问',
      unit: u,
    }
  }),
)

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [b, u, p, m] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      listGeoUnits(tenantId.value, { status: 'active' }),
      listGeoPrompts(tenantId.value, { status: 'active' }),
      listGeoDailyMetrics(tenantId.value, { scope_level: 'unit' }).catch(() => ({ items: [] })),
    ])
    businesses.value = b.items || []
    units.value = u.items || []
    prompts.value = p.items || []
    daily.value = m.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.business_id || !form.value.name.trim()) {
    ElMessage.warning('请选择业务并填写关键词名称')
    return
  }
  creating.value = true
  try {
    await createGeoUnit({
      tenant_id: tenantId.value,
      business_id: form.value.business_id,
      name: form.value.name.trim(),
      keyword: form.value.keyword.trim() || form.value.name.trim(),
      description: form.value.description.trim() || null,
    })
    ElMessage.success('已添加关键词')
    createOpen.value = false
    form.value = { business_id: filterBusinessId.value, name: '', keyword: '', description: '' }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function goQuestions(unit) {
  router.push({ path: '/geo/questions', query: { unit_id: String(unit.id) } })
}

function openEdit(row) {
  editForm.value = {
    id: row.id,
    business_id: row.business_id,
    name: row.name || '',
    keyword: row.keyword || '',
    description: row.description || '',
  }
  editOpen.value = true
}

async function submitEdit() {
  if (!editForm.value.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    await patchGeoUnit(tenantId.value, editForm.value.id, {
      name: editForm.value.name.trim(),
      keyword: editForm.value.keyword.trim() || editForm.value.name.trim(),
      description: editForm.value.description.trim() || null,
      business_id: editForm.value.business_id,
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

async function archiveUnit(row) {
  try {
    await ElMessageBox.confirm(`归档关键词「${row.keyword || row.name}」？`, '归档', {
      type: 'warning',
      confirmButtonText: '归档',
    })
    await patchGeoUnit(tenantId.value, row.id, { status: 'archived' })
    ElMessage.success('已归档')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '归档失败')
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoV2Page
    tag="连接用户需求"
    title="关键词不是拿来堆排名的，而是用来发现用户会向 AI 问什么。"
    desc="围绕业务沉淀关键词，并识别这些关键词背后的真实购买场景、常见问题和内容机会。"
    :steps="['选择业务', '维护关键词', '生成AI提问', '追踪推荐率']"
    :answer="{
      now: ['我现在怎么样？', cards[0] ? `${cards[0].name} 已有提问覆盖` : '还没有关键词。', '先选一条业务，把核心词建起来。'],
      why: ['为什么？', 'AI 回答常从具体问题进入，泛关键词很难直接触发品牌推荐。'],
      next: ['下一步怎么办？', '把核心词拆成选型、价格、行业方案和替代方案等提问簇。'],
    }"
  >
    <template #actions>
      <el-button type="primary" @click="createOpen = true">新增关键词</el-button>
      <el-button @click="router.push('/geo/recommend')">AI 推荐</el-button>
    </template>

    <NeedHintAlert />
    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <section class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">关键词机会池</span>
          <h2>当前关键词</h2>
          <p class="sub">按业务查看关键词、关联提问数和下一步动作。</p>
        </div>
        <input v-model="qSearch" class="gd-search" placeholder="搜索关键词…" />
        <el-select
          v-model="filterBusinessId"
          clearable
          filterable
          placeholder="全部业务"
          style="width: 200px"
        >
          <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
      </div>
      <div class="metric-list">
        <div v-for="c in cards" :key="c.name" class="gv2-card gv2-metric">
          <div>
            <b>{{ c.name }}</b>
            <p>{{ c.reason }}</p>
          </div>
          <div>
            <strong>{{ c.value }}</strong>
            <em>{{ c.action }}</em>
          </div>
        </div>
        <el-empty v-if="!filteredUnits.length" description="还没有关键词。先新增一条。" />
      </div>
    </section>

    <section class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">关键词到 AI 提问</span>
          <h2>从词到问题</h2>
        </div>
      </div>
      <el-table :data="filteredUnits" empty-text="暂无关键词">
        <el-table-column label="关键词" min-width="160">
          <template #default="{ row }">{{ row.keyword || row.name }}</template>
        </el-table-column>
        <el-table-column label="业务" min-width="140">
          <template #default="{ row }">{{ bizName(row.business_id) }}</template>
        </el-table-column>
        <el-table-column label="AI 提问" width="120">
          <template #default="{ row }">{{ promptCount(row.id) }} 条</template>
        </el-table-column>
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="goQuestions(row)">查看提问</el-button>
            <el-button
              link
              type="primary"
              @click="router.push({ path: '/geo/recommend', query: { keyword: row.keyword || row.name } })"
            >
              生成提问
            </el-button>
            <el-button link type="danger" @click="archiveUnit(row)">归档</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="editOpen" title="编辑关键词" width="480px">
      <el-form label-position="top">
        <el-form-item label="所属业务" required>
          <el-select v-model="editForm.business_id" filterable placeholder="选择业务" style="width: 100%">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词名称" required>
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="检索词（可选）">
          <el-input v-model="editForm.keyword" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createOpen" title="新增关键词" width="480px">
      <el-form label-position="top">
        <el-form-item label="所属业务" required>
          <el-select v-model="form.business_id" filterable placeholder="选择业务" style="width: 100%">
            <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词名称" required>
          <el-input v-model="form.name" placeholder="如：CRM软件" />
        </el-form-item>
        <el-form-item label="检索词（可选）">
          <el-input v-model="form.keyword" placeholder="默认同名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>
  </GeoV2Page>
</template>
