<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import GeoBusinessProfileForm from '../../components/GeoBusinessProfileForm.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import {
  fetchGeoCompetitorInsights,
  fetchOnboardingReadiness,
  listGeoBusinesses,
  patchGeoBusiness,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId, session } = useGeoTenant()
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const businesses = ref([])
const selectedId = ref(null)
const readiness = ref(null)
const profile = ref({})

const tenantName = computed(() => {
  const hit = (session.tenants || []).find((t) => t.id === tenantId.value)
  return hit?.name || (tenantId.value ? `客户 #${tenantId.value}` : '未选择客户')
})
const current = computed(
  () => businesses.value.find((b) => b.id === selectedId.value) || null,
)
const completeness = computed(() => {
  const p = profile.value || {}
  const keys = ['product_name', 'website', 'summary', 'audience', 'industry', 'banned_claims']
  const hit = keys.filter((k) => String(p[k] || '').trim()).length
  return `${hit}/${keys.length}`
})
const insightNames = ref([])
const newCompetitor = ref('')

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
  return insightNames.value.filter((n) => n && !have.has(n.toLowerCase())).slice(0, 6)
})

function emptyProfile() {
  return {
    product_name: '',
    website: '',
    summary: '',
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
    product_name: p.product_name || row?.name || '',
    website: p.website || p.website_url || p.official_url || '',
    summary: p.summary || row?.description || '',
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
    const [b, r, comps] = await Promise.all([
      listGeoBusinesses(tenantId.value, { status: 'active' }),
      fetchOnboardingReadiness(tenantId.value).catch(() => null),
      fetchGeoCompetitorInsights(tenantId.value).catch(() => null),
    ])
    businesses.value = b.items || []
    readiness.value = r
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

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="品牌信息"
    :sub="`维护品牌名称、官网、行业和业务介绍 · 完整度 ${completeness}`"
    :loading="loading"
  >
    <template #actions>
      <span class="gd-badge green">完整度 {{ completeness }}</span>
      <button class="gd-btn" @click="router.push('/geo/onboarding')">开户向导</button>
      <button class="gd-btn primary" :disabled="saving" @click="save">保存</button>
    </template>
    <div class="geo-dash">

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <section class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">基础配置</span>
          <h2>品牌资料 · {{ tenantName }}</h2>
          <p class="sub">按业务线维护画像。AI 生成文章时会读取这些字段。</p>
        </div>
        <el-select v-model="selectedId" placeholder="选择业务" style="width: 220px">
          <el-option v-for="b in businesses" :key="b.id" :label="b.name" :value="b.id" />
        </el-select>
      </div>
      <el-empty v-if="!businesses.length" description="还没有业务线，先去业务管理或开户向导创建。">
        <el-button type="primary" @click="router.push('/geo/businesses')">去业务管理</el-button>
      </el-empty>
      <GeoBusinessProfileForm v-else v-model="profile" />
      <div v-if="current" class="gd-card" style="margin-top:16px">
        <div class="gd-hd"><h3>竞争对手</h3></div>
        <div class="gd-bd">
          <p class="gd-sub" style="margin:0 0 12px">列出主要替代品牌，竞品分析会按这些名字归并快照。</p>
          <div v-for="name in competitorList" :key="name" class="comp-row">
            <b>{{ name }}</b>
            <button class="gd-btn" style="margin-left:auto" @click="removeCompetitor(name)">删除</button>
          </div>
          <div v-if="!competitorList.length" class="gd-sub">还没有竞品，从下方推荐添加或手动输入。</div>
          <div style="display:flex;gap:8px;margin-top:12px">
            <input v-model="newCompetitor" class="gd-search" placeholder="输入竞品名称" @keyup.enter="addCompetitor()" />
            <button class="gd-btn primary" @click="addCompetitor()">+ 新增</button>
          </div>
          <div v-if="suggestedCompetitors.length" style="margin-top:14px">
            <div class="gd-sub">快照里出现过、尚未加入</div>
            <div class="geo-chips">
              <button
                v-for="n in suggestedCompetitors"
                :key="n"
                class="geo-chip"
                @click="addCompetitor(n)"
              >+ {{ n }}</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-if="readiness?.items?.length" class="gv2-panel">
      <div class="gv2-panel-head">
        <div>
          <span class="gv2-kicker">配置影响</span>
          <h2>还差什么</h2>
          <p class="sub">已就绪 {{ readiness.ready_count }}/{{ readiness.total }}</p>
        </div>
      </div>
      <div class="gv2-grid-2">
        <div
          v-for="it in readiness.items"
          :key="it.key"
          class="gv2-card"
          role="button"
          @click="it.href && router.push(it.href)"
        >
          <b>{{ it.title }}</b>
          <p>{{ it.hint }}</p>
          <span class="gv2-tag" :class="it.ok ? 'good' : 'warn'">{{ it.ok ? '已就绪' : '待补' }}</span>
        </div>
      </div>
    </section>
    </div>
  </GeoWorkbenchPage>
</template>
<style scoped>
.comp-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #e8eaf0;
}
</style>
