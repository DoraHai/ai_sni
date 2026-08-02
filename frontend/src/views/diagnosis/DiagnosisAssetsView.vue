<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoKnowledge,
  deleteGeoKnowledge,
  discoverGeoBrand,
  fetchGeoAssetProfile,
  fetchGeoKnowledge,
  saveGeoAudience,
  saveGeoBrand,
} from '../../api/geo'

const props = defineProps({
  tenantId: { type: [Number, String], required: true },
  asset: { type: Object, required: true },
  initialWebsite: { type: String, default: '' },
})
const emit = defineEmits(['brand-saved'])

const loading = ref(false)
const saving = ref(false)
const profileLoaded = ref(false)
const profileReady = ref(false)
const discovering = ref(false)
const discoveryEvidence = ref({})
const discoveryUsedAI = ref(false)
const brand = reactive({
  name: '', website: '', industry: '', business_desc: '',
  brand_terms: '', core_products: '', proof_points: '',
})
const audience = reactive({
  segments: '', decision_roles: '', pain_points: '', search_scenarios: '',
})
const knowledge = ref([])
const search = ref('')
const typeFilter = ref('')
const composerOpen = ref(false)
const draft = reactive({ title: '', item_type: 'product', body: '', source_url: '' })

const typeOptions = [
  { value: '', label: '全部资料' },
  { value: 'product', label: '产品资料' },
  { value: 'case', label: '客户案例' },
  { value: 'whitepaper', label: '行业白皮书' },
  { value: 'faq', label: 'FAQ' },
  { value: 'other', label: '其他' },
]
const typeLabel = (value) => typeOptions.find((item) => item.value === value)?.label || '其他'
const splitLines = (value) => value.split(/\n|，|,/).map((item) => item.trim()).filter(Boolean)
const joinLines = (value) => Array.isArray(value) ? value.join('\n') : ''
const activePage = computed(() => props.asset.page)
const requiredFields = computed(() => [
  { label: '官方网站', ready: Boolean(brand.website.trim()) },
  { label: '品牌名称', ready: Boolean(brand.name.trim()) },
  { label: '所属行业', ready: Boolean(brand.industry.trim()) },
  { label: '核心产品与服务', ready: splitLines(brand.core_products).length > 0 },
])
const requiredReady = computed(() => requiredFields.value.every((item) => item.ready))
const completion = computed(() => requiredFields.value.filter((item) => item.ready).length * 25)
const setupStep = computed(() => profileReady.value ? 3 : Object.keys(discoveryEvidence.value).length ? 2 : 1)

function normalizeWebsite(value) {
  const input = String(value || '').trim()
  if (!input) return ''
  return /^https?:\/\//i.test(input) ? input : `https://${input}`
}

async function loadProfile() {
  if (!props.tenantId || profileLoaded.value) return
  loading.value = true
  try {
    const data = await fetchGeoAssetProfile(props.tenantId, props.initialWebsite)
    Object.assign(brand, {
      ...data.brand,
      website: data.brand?.website || props.initialWebsite || '',
      brand_terms: joinLines(data.brand?.brand_terms),
      core_products: joinLines(data.brand?.core_products),
      proof_points: joinLines(data.brand?.proof_points),
    })
    profileReady.value = Boolean(data.profile_ready)
    Object.assign(audience, {
      segments: joinLines(data.audience?.segments),
      decision_roles: joinLines(data.audience?.decision_roles),
      pain_points: joinLines(data.audience?.pain_points),
      search_scenarios: joinLines(data.audience?.search_scenarios),
    })
    profileLoaded.value = true
  } catch (error) {
    ElMessage.error(error.message || '品牌资产加载失败')
  } finally {
    loading.value = false
  }
}

async function discoverProfile() {
  const website = normalizeWebsite(brand.website || props.initialWebsite)
  if (!website) {
    ElMessage.warning('请先填写官方网站')
    return
  }
  brand.website = website
  discovering.value = true
  try {
    const data = await discoverGeoBrand({ tenantId: Number(props.tenantId), website })
    Object.assign(brand, {
      ...data.brand,
      brand_terms: joinLines(data.brand?.brand_terms),
      core_products: joinLines(data.brand?.core_products),
      proof_points: joinLines(data.brand?.proof_points),
    })
    discoveryEvidence.value = data.brand?.evidence || {}
    discoveryUsedAI.value = Boolean(data.ai_used)
    profileReady.value = false
    ElMessage.success('官网信息已整理，请确认后开始体检')
  } catch (error) {
    ElMessage.error(error.message || '官网信息读取失败，请检查网址或手动填写')
  } finally {
    discovering.value = false
  }
}

async function saveProfile() {
  saving.value = true
  try {
    if (activePage.value === 'brand') {
      if (!requiredReady.value) return ElMessage.warning('请完成四项必填信息后再开始体检')
      const result = await saveGeoBrand({
        tenant_id: Number(props.tenantId),
        ...brand,
        brand_terms: splitLines(brand.brand_terms),
        core_products: splitLines(brand.core_products),
        proof_points: splitLines(brand.proof_points),
      })
      profileReady.value = true
      ElMessage.success('品牌档案已保存，正在进入网站体检')
      emit('brand-saved', result.brand)
    } else {
      await saveGeoAudience({
        tenant_id: Number(props.tenantId),
        segments: splitLines(audience.segments),
        decision_roles: splitLines(audience.decision_roles),
        pain_points: splitLines(audience.pain_points),
        search_scenarios: splitLines(audience.search_scenarios),
      })
      ElMessage.success('目标用户画像已保存')
    }
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function loadKnowledge() {
  if (!props.tenantId) return
  loading.value = true
  try {
    const data = await fetchGeoKnowledge({
      tenantId: props.tenantId,
      q: search.value,
      itemType: typeFilter.value,
    })
    knowledge.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message || '知识库加载失败')
  } finally {
    loading.value = false
  }
}

function resetDraft() {
  Object.assign(draft, { title: '', item_type: 'product', body: '', source_url: '' })
}

async function saveKnowledge() {
  if (!draft.title.trim() || !draft.body.trim()) {
    ElMessage.warning('请填写资料标题和正文')
    return
  }
  saving.value = true
  try {
    await createGeoKnowledge({ tenant_id: Number(props.tenantId), ...draft })
    ElMessage.success('资料已加入知识库')
    resetDraft()
    composerOpen.value = false
    await loadKnowledge()
  } catch (error) {
    ElMessage.error(error.message || '资料保存失败')
  } finally {
    saving.value = false
  }
}

async function importTextFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > 100000) {
    ElMessage.warning('单个文本文件请控制在 100 KB 以内')
    return
  }
  draft.title = draft.title || file.name.replace(/\.[^.]+$/, '')
  draft.body = await file.text()
  draft.item_type = file.name.toLowerCase().includes('faq') ? 'faq' : draft.item_type
  composerOpen.value = true
  ElMessage.success('文件内容已读取，请确认后保存')
}

async function removeKnowledge(item) {
  try {
    await ElMessageBox.confirm(`确认删除“${item.title}”？`, '删除资料', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteGeoKnowledge({ tenantId: props.tenantId, knowledgeId: item.id })
    ElMessage.success('资料已删除')
    await loadKnowledge()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '删除失败')
  }
}

function formatDate(value) {
  if (!value) return '刚刚'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

async function activate() {
  if (activePage.value === 'knowledge') await loadKnowledge()
  else await loadProfile()
}

watch(() => props.asset.page, activate)
watch(() => props.tenantId, () => {
  profileLoaded.value = false
  activate()
})
onMounted(activate)
</script>

<template>
  <div class="asset-workspace" :class="{ loading }">
    <section class="asset-hero">
      <div>
        <span class="eyebrow">{{ asset.kicker }}</span>
        <h2>{{ asset.label }}</h2>
        <p>{{ asset.description }}</p>
      </div>
      <span class="state"><i /> 已接入数据底座</span>
    </section>

    <template v-if="activePage === 'brand'">
      <section class="setup-rail" aria-label="品牌建档进度">
        <div v-for="(label, index) in ['填写官网', '确认品牌信息', '开始网站体检']" :key="label" :class="{ active: setupStep === index + 1, done: setupStep > index + 1 }">
          <span>{{ setupStep > index + 1 ? '✓' : index + 1 }}</span>
          <p><small>STEP {{ String(index + 1).padStart(2, '0') }}</small><b>{{ label }}</b></p>
        </div>
      </section>

      <section class="form-card">
        <div class="card-heading">
          <div><span class="eyebrow">01 / BRAND FOUNDATION</span><h3>{{ profileReady ? '品牌档案已就绪' : '先建立品牌档案' }}</h3></div>
          <p>诊断建议需要先知道“你是谁、提供什么”。资料仅供诊断中心使用，不会修改 SEM 客户信息。</p>
        </div>

        <div class="website-starter">
          <div>
            <span class="starter-index">A</span>
            <p><strong>从官方网站开始</strong><small>系统读取公开页面，自动整理可编辑的候选信息。</small></p>
          </div>
          <label>
            <input v-model="brand.website" inputmode="url" autocomplete="url" placeholder="例如：https://www.yourbrand.com" @keyup.enter="discoverProfile">
            <button type="button" :disabled="discovering" @click="discoverProfile">{{ discovering ? '正在读取官网…' : '从官网自动识别 →' }}</button>
          </label>
          <div class="privacy-note"><span>只读</span>仅读取公开网页，不登录后台，也不会修改目标网站。</div>
        </div>

        <div class="completion-strip">
          <div><strong>必填资料完整度 {{ completion }}%</strong><span>{{ requiredReady ? '已具备开始体检的条件' : '完成四项信息后即可开始' }}</span></div>
          <i><b :style="{ width: `${completion}%` }" /></i>
          <ul><li v-for="item in requiredFields" :key="item.label" :class="{ ready: item.ready }">{{ item.ready ? '✓' : '○' }} {{ item.label }}</li></ul>
        </div>

        <div class="form-grid">
          <label><span>品牌名称 * <em v-if="discoveryEvidence.name">{{ discoveryEvidence.name }}</em></span><input v-model="brand.name" placeholder="例如：某某科技" /></label>
          <label><span>所属行业 * <em v-if="discoveryEvidence.industry">{{ discoveryEvidence.industry }}</em></span><input v-model="brand.industry" placeholder="例如：工业制造 / 金属加工" /></label>
          <label><span>品牌词根</span><input v-model="brand.brand_terms" placeholder="多个词用逗号分隔" /></label>
          <label class="wide"><span>业务定位与品牌介绍 <em v-if="discoveryEvidence.business_desc">{{ discoveryEvidence.business_desc }}</em></span><textarea v-model="brand.business_desc" rows="4" placeholder="说明服务对象、核心能力与差异化定位" /></label>
          <label><span>核心产品与服务 * <em v-if="discoveryEvidence.core_products">{{ discoveryEvidence.core_products }}</em></span><textarea v-model="brand.core_products" rows="6" placeholder="每行一项，例如：金属切削刀具" /></label>
          <label><span>可信信息与证明</span><textarea v-model="brand.proof_points" rows="6" placeholder="资质、客户、奖项、数据，每行一项" /></label>
        </div>
        <div v-if="Object.keys(discoveryEvidence).length" class="review-note">
          <span>{{ discoveryUsedAI ? 'AI' : 'WEB' }}</span>
          <p><strong>请确认自动识别结果</strong><small>候选值来自官网公开信息，仍可能存在简称或行业归类偏差；保存前可以直接修改。</small></p>
        </div>
        <footer><span>保存后将按当前官网域名建立独立档案</span><button :disabled="saving || !requiredReady" @click="saveProfile">{{ saving ? '正在保存…' : profileReady ? '保存并重新体检 →' : '确认信息并开始体检 →' }}</button></footer>
      </section>
    </template>

    <template v-else-if="activePage === 'audience'">
      <section class="form-card">
        <div class="card-heading">
          <div><span class="eyebrow">01 / AUDIENCE MAP</span><h3>目标用户定义</h3></div>
          <p>每行填写一个对象或场景，便于诊断和内容策略直接引用。</p>
        </div>
        <div class="form-grid audience-grid">
          <label><span>核心客群</span><textarea v-model="audience.segments" rows="8" placeholder="例如：大型制造企业设备负责人" /></label>
          <label><span>决策角色</span><textarea v-model="audience.decision_roles" rows="8" placeholder="例如：采购负责人、技术总监" /></label>
          <label><span>主要痛点与购买动机</span><textarea v-model="audience.pain_points" rows="8" placeholder="例如：交付周期不稳定、维护成本高" /></label>
          <label><span>搜索与决策场景</span><textarea v-model="audience.search_scenarios" rows="8" placeholder="例如：对比方案、寻找供应商、验证参数" /></label>
        </div>
        <footer><span>这些信息会帮助建议更贴近真实决策链路</span><button :disabled="saving" @click="saveProfile">{{ saving ? '保存中…' : '保存目标用户 →' }}</button></footer>
      </section>
    </template>

    <template v-else>
      <section class="knowledge-tools">
        <div><strong>{{ knowledge.length }}</strong><span>当前资料</span></div>
        <input v-model="search" placeholder="搜索标题、正文或来源…" @keyup.enter="loadKnowledge" />
        <select v-model="typeFilter" @change="loadKnowledge"><option v-for="item in typeOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select>
        <button class="ghost" @click="$refs.fileInput.click()">导入文本</button>
        <input ref="fileInput" class="hidden-file" type="file" accept=".txt,.md,.json,text/plain,application/json" @change="importTextFile" />
        <button @click="composerOpen = !composerOpen">{{ composerOpen ? '收起' : '新增资料 +' }}</button>
      </section>

      <section v-if="composerOpen" class="composer">
        <div class="card-heading"><div><span class="eyebrow">NEW KNOWLEDGE</span><h3>新增知识资料</h3></div><p>支持手动录入，或导入 TXT、Markdown、JSON 文本。</p></div>
        <div class="form-grid">
          <label><span>资料标题 *</span><input v-model="draft.title" placeholder="清晰描述这份资料" /></label>
          <label><span>资料类型</span><select v-model="draft.item_type"><option v-for="item in typeOptions.slice(1)" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label class="wide"><span>正文内容 *</span><textarea v-model="draft.body" rows="9" placeholder="粘贴产品事实、案例、白皮书摘要或 FAQ…" /></label>
          <label class="wide"><span>来源链接</span><input v-model="draft.source_url" placeholder="https://（选填）" /></label>
        </div>
        <footer><button class="cancel" @click="composerOpen = false">取消</button><button :disabled="saving" @click="saveKnowledge">{{ saving ? '保存中…' : '保存到知识库 →' }}</button></footer>
      </section>

      <section v-if="knowledge.length" class="knowledge-grid">
        <article v-for="item in knowledge" :key="item.id">
          <header><span :class="`type-${item.item_type}`">{{ typeLabel(item.item_type) }}</span><time>{{ formatDate(item.created_at) }}</time></header>
          <h3>{{ item.title }}</h3>
          <p>{{ item.body }}</p>
          <footer><a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noopener">查看来源 ↗</a><span v-else>内部资料</span><button @click="removeKnowledge(item)">删除</button></footer>
        </article>
      </section>
      <section v-else-if="!loading" class="empty">
        <b>▤</b><h3>知识库还没有资料</h3><p>录入产品事实、案例与 FAQ，诊断建议才有可靠依据。</p><button @click="composerOpen = true">新增第一份资料 →</button>
      </section>
    </template>
  </div>
</template>

<style scoped>
.asset-workspace{display:grid;gap:18px;max-width:1460px;margin:0 auto;padding:28px 32px 80px;color:#18272b;font-family:"Avenir Next","Noto Sans SC","PingFang SC",sans-serif}.asset-workspace.loading{opacity:.72}.asset-hero{min-height:170px;display:flex;align-items:flex-end;justify-content:space-between;gap:40px;padding:32px 38px;border:1px solid rgba(103,174,165,.22);border-radius:16px;background:radial-gradient(circle at 88% 0%,rgba(90,211,191,.2),transparent 34%),linear-gradient(135deg,#f9fdfc,#edf8f5);box-shadow:0 14px 38px rgba(45,87,83,.07)}.asset-hero>div{max-width:760px}.eyebrow{color:#0b9388;font-size:9px;font-weight:850;letter-spacing:.18em}.asset-hero h2{margin:10px 0 7px;font:700 32px "Songti SC","Noto Serif SC",serif}.asset-hero p,.card-heading p{margin:0;color:#687b7e;font-size:12px;line-height:1.75}.state{padding:9px 13px;border:1px solid #b9ddd8;border-radius:20px;color:#076a64;background:rgba(255,255,255,.78);font-size:10px;font-weight:800}.state i{display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;background:#24b394;box-shadow:0 0 0 4px rgba(36,179,148,.12)}.form-card,.composer{padding:28px 30px;border:1px solid #dfe7e6;border-radius:14px;background:#fff}.card-heading{display:flex;align-items:end;justify-content:space-between;gap:24px;padding-bottom:22px;border-bottom:1px solid #e7edec}.card-heading h3{margin:7px 0 0;font:700 21px "Songti SC","Noto Serif SC",serif}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 18px;padding:25px 0}.form-grid label{display:grid;gap:8px}.form-grid label.wide{grid-column:1/-1}.form-grid label>span{color:#55676b;font-size:11px;font-weight:750}.form-grid label>span em{float:right;padding:3px 7px;border-radius:10px;color:#087a71;background:#e7f6f3;font-size:8px;font-style:normal;font-weight:800}.form-grid input,.form-grid textarea,.form-grid select,.knowledge-tools input,.knowledge-tools select{width:100%;box-sizing:border-box;border:1px solid #dbe5e3;border-radius:9px;outline:0;background:#fbfdfc;color:#203236;font:inherit;font-size:12px;transition:.2s}.form-grid input,.form-grid select{height:43px;padding:0 13px}.form-grid textarea{padding:12px 13px;resize:vertical;line-height:1.7}.form-grid input:focus,.form-grid textarea:focus,.form-grid select:focus,.knowledge-tools input:focus{border-color:#6dc5bb;box-shadow:0 0 0 3px rgba(11,147,136,.08);background:#fff}.form-card>footer,.composer>footer{display:flex;align-items:center;justify-content:flex-end;gap:12px;padding-top:18px;border-top:1px solid #edf1f0}.form-card>footer span{margin-right:auto;color:#819094;font-size:10px}.form-card button,.composer button,.knowledge-tools button,.empty button{height:40px;padding:0 17px;border:0;border-radius:8px;color:#fff;background:#0b9388;font-size:11px;font-weight:800;cursor:pointer}.form-card button:disabled,.composer button:disabled{opacity:.45;cursor:not-allowed}.setup-rail{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;overflow:hidden;border:1px solid #dfe7e6;border-radius:14px;background:#dfe7e6}.setup-rail>div{display:flex;align-items:center;gap:12px;padding:16px 20px;background:#fff}.setup-rail>div.active{background:#f0faf8}.setup-rail>div.done{background:#f8fbfa}.setup-rail>div>span{width:29px;height:29px;display:grid;place-items:center;border:1px solid #cddbd9;border-radius:50%;color:#82918f;font:700 11px Georgia,serif}.setup-rail>div.active>span,.setup-rail>div.done>span{border-color:#0b9388;color:#fff;background:#0b9388}.setup-rail p,.setup-rail small,.setup-rail b{display:block;margin:0}.setup-rail small{color:#92a09e;font-size:7px;letter-spacing:.16em}.setup-rail b{margin-top:3px;font-size:11px}.website-starter{margin:24px 0 0;padding:20px 22px;border:1px solid #b9ddd8;border-radius:12px;background:linear-gradient(135deg,#f5fcfa,#edf8f5)}.website-starter>div:first-child{display:flex;align-items:center;gap:12px;margin-bottom:14px}.starter-index{width:32px;height:32px;display:grid;place-items:center;border-radius:9px;color:#fff;background:#0b9388;font:700 14px Georgia,serif}.website-starter p,.website-starter strong,.website-starter small{display:block;margin:0}.website-starter p small{margin-top:3px;color:#738583;font-size:10px}.website-starter label{display:grid;grid-template-columns:1fr auto;padding:5px;border:1px solid #c9dcda;border-radius:11px;background:#fff;box-shadow:0 9px 28px rgba(33,81,76,.06)}.website-starter input{min-width:0;height:44px;padding:0 13px;border:0;outline:0;color:#1d3033;background:transparent;font:inherit;font-size:12px}.website-starter button{height:44px;padding:0 18px}.privacy-note{margin-top:10px;color:#70817f;font-size:9px}.privacy-note span{margin-right:7px;padding:3px 6px;border-radius:8px;color:#087a71;background:#dff3ef;font-weight:800}.completion-strip{display:grid;grid-template-columns:auto minmax(160px,1fr) auto;align-items:center;gap:18px;margin:18px 0 0;padding:14px 17px;border:1px solid #e2e9e8;border-radius:10px;background:#fbfdfc}.completion-strip>div strong,.completion-strip>div span{display:block}.completion-strip>div strong{font-size:11px}.completion-strip>div span{margin-top:3px;color:#82918f;font-size:9px}.completion-strip>i{height:5px;overflow:hidden;border-radius:8px;background:#e4ecea}.completion-strip>i b{display:block;height:100%;border-radius:inherit;background:#0b9388;transition:width .3s ease}.completion-strip ul{display:flex;gap:6px;margin:0;padding:0;list-style:none}.completion-strip li{padding:4px 7px;border-radius:12px;color:#8a9896;background:#eef2f1;font-size:8px;white-space:nowrap}.completion-strip li.ready{color:#087a71;background:#e2f5f1}.review-note{display:flex;align-items:center;gap:12px;margin:0 0 22px;padding:14px 16px;border-left:3px solid #0b9388;background:#f4faf8}.review-note>span{width:34px;height:34px;display:grid;place-items:center;border-radius:9px;color:#fff;background:#0b9388;font-size:9px;font-weight:900}.review-note p,.review-note strong,.review-note small{display:block;margin:0}.review-note small{margin-top:4px;color:#768684;font-size:9px;line-height:1.6}.knowledge-tools{display:grid;grid-template-columns:auto minmax(240px,1fr) 140px auto auto;gap:10px;align-items:center;padding:16px 18px;border:1px solid #dfe7e6;border-radius:12px;background:#fff}.knowledge-tools>div{display:flex;align-items:baseline;gap:7px;padding-right:12px}.knowledge-tools strong{font:700 25px Georgia,serif;color:#076a64}.knowledge-tools span{color:#7c8c90;font-size:10px}.knowledge-tools input,.knowledge-tools select{height:40px;padding:0 12px}.knowledge-tools button.ghost,.composer button.cancel{border:1px solid #cfe0dd;color:#5f7476;background:#fff}.hidden-file{display:none}.composer{box-shadow:0 16px 42px rgba(30,72,68,.08)}.knowledge-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.knowledge-grid article{min-height:190px;display:flex;flex-direction:column;padding:23px 24px;border:1px solid #dfe7e6;border-radius:12px;background:#fff;transition:.2s}.knowledge-grid article:hover{transform:translateY(-2px);border-color:#b8d8d4;box-shadow:0 12px 25px rgba(34,74,70,.06)}.knowledge-grid header,.knowledge-grid footer{display:flex;align-items:center;justify-content:space-between}.knowledge-grid header span{padding:5px 8px;border-radius:15px;color:#087a71;background:#e8f7f4;font-size:9px;font-weight:800}.knowledge-grid time{color:#99a5a7;font-size:9px}.knowledge-grid h3{margin:18px 0 9px;font-size:15px}.knowledge-grid p{display:-webkit-box;overflow:hidden;margin:0 0 20px;color:#708084;font-size:11px;line-height:1.75;-webkit-line-clamp:3;-webkit-box-orient:vertical;white-space:pre-line}.knowledge-grid footer{margin-top:auto;padding-top:14px;border-top:1px solid #edf1f0}.knowledge-grid footer a,.knowledge-grid footer span{color:#0b9388;font-size:10px;text-decoration:none}.knowledge-grid footer button{border:0;color:#a76464;background:transparent;font-size:10px;cursor:pointer}.empty{min-height:280px;display:grid;place-items:center;align-content:center;padding:30px;border:1px dashed #bdd8d4;border-radius:14px;background:rgba(255,255,255,.7);text-align:center}.empty b{width:55px;height:55px;display:grid;place-items:center;border-radius:16px;color:#fff;background:#0b9388;font-size:20px}.empty h3{margin:17px 0 6px;font:700 20px "Songti SC","Noto Serif SC",serif}.empty p{margin:0 0 19px;color:#748487;font-size:11px}@media(max-width:1050px){.completion-strip{grid-template-columns:1fr}.completion-strip ul{flex-wrap:wrap}}@media(max-width:850px){.asset-workspace{padding:18px 15px 60px}.asset-hero{align-items:flex-start;flex-direction:column;padding:25px}.form-grid,.knowledge-grid{grid-template-columns:1fr}.form-grid label.wide{grid-column:auto}.knowledge-tools{grid-template-columns:1fr 1fr}.knowledge-tools input{grid-column:1/-1}.card-heading{align-items:flex-start;flex-direction:column}.audience-grid{grid-template-columns:1fr}.setup-rail{grid-template-columns:1fr}.website-starter label{grid-template-columns:1fr}.website-starter button{width:100%}}@media print{.knowledge-tools,.form-card button,.composer{display:none}}
</style>
