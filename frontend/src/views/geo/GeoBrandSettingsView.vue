<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import GeoBusinessProfileForm from '../../components/GeoBusinessProfileForm.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import {
  createGeoBusiness,
  fetchGeoCompetitorInsights,
  listGeoBusinesses,
  patchGeoBusiness,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const newBizName = ref('')
const error = ref('')
const businesses = ref([])
const selectedId = ref(null)
const profile = ref({})
const insightNames = ref([])
const newCompetitor = ref('')

const tenantName = computed(() => {
  const hit = (session.tenants || []).find((t) => t.id === tenantId.value)
  return hit?.name || (tenantId.value ? `客户 #${tenantId.value}` : '未选择客户')
})
const current = computed(
  () => businesses.value.find((b) => b.id === selectedId.value) || null,
)
const filledCount = computed(() => {
  const p = profile.value || {}
  return ['product_name', 'website', 'summary', 'industry', 'honors', 'qualifications']
    .filter((k) => String(p[k] || '').trim()).length
})
const completeness = computed(() => `${filledCount.value}/6`)

function splitNames(raw) {
  if (Array.isArray(raw)) return raw.map((x) => String(x || '').trim()).filter(Boolean)
  return String(raw || '')
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

const competitorList = computed(() => splitNames(profile.value.competitors))
const suggestedCompetitors = computed(() => {
  const have = new Set(competitorList.value.map((n) => n.toLowerCase()))
  return insightNames.value.filter((n) => n && !have.has(n.toLowerCase())).slice(0, 8)
})

function emptyProfile() {
  return {
    product_name: '',
    website: '',
    summary: '',
    honors: '',
    qualifications: '',
    capabilities: '',
    audience: '',
    scenarios: '',
    geo_scope: '',
    industry: '',
    competitors: '',
    recommend_reasons: '',
    banned_claims: '',
    cta: '',
  }
}

function profileFromRow(row) {
  const p = row?.profile || {}
  const join = (v) => (Array.isArray(v) ? v.join('，') : v || '')
  return {
    ...emptyProfile(),
    ...p,
    product_name: p.product_name || row?.name || '',
    website: p.website || p.website_url || p.official_url || '',
    summary: p.summary || row?.description || '',
    honors: join(p.honors),
    qualifications: join(p.qualifications),
    capabilities: join(p.capabilities),
    audience: join(p.audience),
    scenarios: join(p.scenarios),
    geo_scope: p.geo_scope || '',
    industry: p.industry || '',
    competitors: join(p.competitors),
    recommend_reasons: join(p.recommend_reasons),
    banned_claims: join(p.banned_claims),
    cta: p.cta || '',
  }
}

function setCompetitors(names) {
  profile.value = { ...profile.value, competitors: names.join('，') }
}

function addCompetitor(name) {
  const n = String(name || newCompetitor.value || '').trim()
  if (!n) return
  const next = [...competitorList.value]
  if (next.some((x) => x.toLowerCase() === n.toLowerCase())) {
    newCompetitor.value = ''
    return
  }
  next.push(n)
  setCompetitors(next)
  newCompetitor.value = ''
}

function removeCompetitor(name) {
  setCompetitors(competitorList.value.filter((x) => x !== name))
}

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [b, comps] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
    ])
    businesses.value = b.items || []
    insightNames.value = (comps?.items || []).map((x) => x.name).filter(Boolean)
    if (!selectedId.value && businesses.value.length) selectedId.value = businesses.value[0].id
    profile.value = profileFromRow(current.value)
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(selectedId, () => {
  profile.value = profileFromRow(current.value)
})

async function save() {
  if (!current.value) {
    ElMessage.warning('请先选择或创建一条业务')
    return
  }
  saving.value = true
  try {
    await patchGeoBusiness(tenantId.value, current.value.id, { profile: profile.value })
    ElMessage.success('品牌资料已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function createBusiness() {
  const name = String(newBizName.value || '').trim()
  if (!name) {
    ElMessage.warning('请填写品牌/业务名称')
    return
  }
  if (!tenantId.value) {
    ElMessage.warning('请先选择客户')
    return
  }
  creating.value = true
  try {
    const row = await createGeoBusiness({ tenant_id: tenantId.value, name })
    ElMessage.success('已创建')
    newBizName.value = ''
    await load()
    if (row?.id) selectedId.value = row.id
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="品牌信息"
    :show-period="false"
    :sub="`维护品牌名称、官网、行业和业务介绍，供 GEO 文章与 AI 可见度引用 · 已填写 ${completeness}`"
    :loading="loading"
  >
    <template #actions>
      <button class="gd-btn" :disabled="loading" @click="load">刷新</button>
      <button class="gd-btn primary" :disabled="saving || !current" @click="save">保存</button>
    </template>

    <div class="geo-dash brand-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <el-empty v-if="!businesses.length" description="还没有品牌资料。先建一条业务线，再填写官网、行业和介绍。">
        <div class="brand-create">
          <el-input v-model="newBizName" placeholder="品牌 / 业务名称" style="width: 240px" />
          <el-button type="primary" :loading="creating" @click="createBusiness">创建</el-button>
        </div>
      </el-empty>

      <template v-else>
        <section class="brand-block">
          <div class="block-copy">
            <h3>当前业务</h3>
            <p>品牌字段按业务分开维护。客户 {{ tenantName }}</p>
          </div>
          <div class="biz-controls">
            <el-select
              v-model="selectedId"
              filterable
              placeholder="选择业务"
              class="biz-select"
            >
              <el-option
                v-for="b in businesses"
                :key="b.id"
                :label="b.name"
                :value="b.id"
              />
            </el-select>
            <el-input
              v-model="newBizName"
              placeholder="再加一条业务"
              size="small"
              style="width: 180px"
              @keyup.enter="createBusiness"
            />
            <button type="button" class="gd-btn" :disabled="creating" @click="createBusiness">
              {{ creating ? '创建中…' : '新建' }}
            </button>
          </div>
        </section>

        <section v-if="current" class="brand-block stacked">
          <div class="editing-line">正在编辑：{{ current.name }}</div>
          <GeoBusinessProfileForm v-model="profile" />
        </section>

        <section v-if="current" class="brand-block stacked">
          <div class="block-copy">
            <h3>竞争对手</h3>
            <p>列出主要替代品牌，竞品分析会按这些名字归并快照。</p>
          </div>

          <div v-if="competitorList.length" class="comp-tags">
            <span v-for="name in competitorList" :key="name" class="comp-tag">
              {{ name }}
              <button type="button" class="comp-x" :title="`删除 ${name}`" @click="removeCompetitor(name)">×</button>
            </span>
          </div>
          <p v-else class="empty-hint">还没有竞品，从下方推荐添加或手动输入。</p>

          <div class="comp-add">
            <input
              v-model="newCompetitor"
              class="comp-input"
              placeholder="输入竞品名称"
              @keyup.enter="addCompetitor()"
            />
            <button type="button" class="gd-btn primary" @click="addCompetitor()">+ 新增</button>
          </div>

          <div v-if="suggestedCompetitors.length" class="suggest">
            <div class="suggest-label">快照里出现过、尚未加入</div>
            <div class="suggest-chips">
              <button
                v-for="n in suggestedCompetitors"
                :key="n"
                type="button"
                class="suggest-chip"
                @click="addCompetitor(n)"
              >+ {{ n }}</button>
            </div>
          </div>
        </section>
      </template>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.brand-page { max-width: 880px; }
.mb { margin-bottom: 14px; }
.brand-block {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding: 18px 20px;
  background: #fff;
  border: 1px solid #e8eaf0;
  border-radius: 14px;
}
.brand-block.stacked {
  display: block;
}
.block-copy h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 750;
  color: #1e2330;
}
.block-copy p {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
}
.biz-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.biz-select { width: min(280px, 70vw); }
.editing-line {
  margin-bottom: 16px;
  font-size: 13px;
  color: #6b7280;
}
.comp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 14px 0 4px;
}
.comp-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 6px 12px;
  border-radius: 999px;
  background: #f5f3ff;
  color: #5b21b6;
  font-size: 13px;
  font-weight: 600;
}
.comp-x {
  border: 0;
  background: transparent;
  color: #7c3aed;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.comp-x:hover { color: #b91c1c; }
.empty-hint {
  margin: 12px 0 0;
  font-size: 13px;
  color: #9ca3af;
}
.comp-add {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  max-width: 520px;
}
.comp-input {
  flex: 1;
  min-width: 0;
  height: 38px;
  padding: 0 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  font-size: 13px;
  background: #fff;
}
.comp-input:focus {
  outline: none;
  border-color: #7c3aed;
}
.suggest { margin-top: 16px; }
.suggest-label {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 8px;
}
.suggest-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.suggest-chip {
  border: 1px solid #ede9fe;
  background: #fff;
  color: #6d28d9;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.suggest-chip:hover {
  background: #f5f3ff;
  border-color: #c4b5fd;
}
</style>
