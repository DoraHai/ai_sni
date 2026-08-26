<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchSeoBrandProfile, updateSeoBrandProfile } from '../../api/seo'
import { currentTenantId, session } from '../../store/session'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const profile = ref({ official_domains: [], ranking_ready: false })
const form = reactive({ brand_name: '', website: '' })

const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.keywords'))
const websiteHasScheme = computed(() => /^https?:\/\//i.test(form.website.trim()))
const hostPreview = computed(() => {
  const value = form.website.trim()
  if (!value) return '等待填写官网'
  try { return new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`).hostname }
  catch { return '网址格式待确认' }
})

async function load() {
  if (!currentTenantId.value) {
    error.value = '请先选择客户'
    return
  }
  loading.value = true
  try {
    profile.value = await fetchSeoBrandProfile({ tenantId: currentTenantId.value })
    form.brand_name = profile.value.brand_name || ''
    form.website = profile.value.website || ''
    error.value = ''
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.brand_name.trim()) return ElMessage.warning('请填写品牌名称')
  if (!form.website.trim()) return ElMessage.warning('请填写官网网址')
  saving.value = true
  try {
    profile.value = await updateSeoBrandProfile({
      tenant_id: currentTenantId.value,
      brand_name: form.brand_name.trim(),
      website: form.website.trim(),
    })
    form.brand_name = profile.value.brand_name
    form.website = profile.value.website
    session.setTenants(session.tenants.map((item) => (
      item.id === currentTenantId.value ? { ...item, name: profile.value.brand_name } : item
    )))
    ElMessage.success('品牌与官网已保存，排名识别规则立即生效')
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

watch(currentTenantId, load)
onMounted(load)
</script>

<template>
  <div class="brand-assets-page" v-loading="loading">
    <section class="brand-hero">
      <div>
        <div class="eyebrow">BRAND IDENTITY · RANKING SOURCE</div>
        <h1>先告诉系统，哪个结果属于你</h1>
        <p>品牌名称用于内容和 AI 判断，官网域名用于识别百度搜索结果中的官方页面。</p>
      </div>
      <div class="ready-seal" :class="{ ready: profile.ranking_ready }">
        <span>{{ profile.ranking_ready ? '✓' : '01' }}</span>
        <div><b>{{ profile.ranking_ready ? '排名判断已就绪' : '需要补充基础资料' }}</b><small>{{ profile.ranking_ready ? '官网规则已进入每日采集' : '填写品牌与官网即可启用' }}</small></div>
      </div>
    </section>

    <el-alert v-if="error" class="page-error" :title="error" type="warning" :closable="false" />

    <section class="identity-card">
      <header>
        <div><span class="step">01</span><div><h2>品牌与主官网</h2><p>这是 SEO 排名归属判断的最低必要信息</p></div></div>
        <span class="required-note">两项必填</span>
      </header>

      <div class="identity-grid">
        <label>
          <span>品牌名称</span>
          <input v-model="form.brand_name" :disabled="!canEdit" maxlength="100" placeholder="例如：苏尔寿" @keyup.enter="save">
          <small>用于识别标题、摘要及品牌推文中的品牌主体</small>
        </label>
        <label>
          <span>官方网站</span>
          <div class="url-input" :class="{ complete: websiteHasScheme }"><i v-if="!websiteHasScheme">https://</i><input v-model="form.website" :disabled="!canEdit" inputmode="url" placeholder="www.example.com" @keyup.enter="save"></div>
          <small>支持直接输入域名，系统会自动规范为官网地址</small>
        </label>
      </div>

      <div class="rule-preview">
        <div class="domain-mark">WWW</div>
        <div><span>即将用于排名判断的官网域名</span><strong>{{ hostPreview }}</strong></div>
        <div class="flow"><em>百度前 50</em><b>→</b><em>域名匹配</em><b>→</b><em class="hit">官网排名</em></div>
      </div>

      <footer>
        <p><span>隐私说明</span>这里只保存公开品牌名称和官网地址，不会采集账号密码。</p>
        <button v-if="canEdit" type="button" :disabled="saving" @click="save">{{ saving ? '正在保存…' : '保存并启用排名判断' }}</button>
      </footer>
    </section>

    <section class="next-assets">
      <header><div><span class="step muted">02</span><div><h2>后续可继续完善</h2><p>不会影响当前官网排名判断</p></div></div></header>
      <div class="asset-roadmap">
        <article><b>品牌账号</b><span>知乎、百家号、公众号</span><i>下一步</i></article>
        <article><b>品牌推文</b><span>已发布文章与问答 URL</span><i>下一步</i></article>
        <article><b>事实知识库</b><span>产品、案例、资质与 FAQ</span><i>规划中</i></article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.brand-assets-page{min-height:calc(100vh - 60px);padding:26px 28px 72px;color:#17233d;background:radial-gradient(circle at 86% -8%,rgba(38,88,215,.1),transparent 32%),#f5f7fb;font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif}.brand-hero{min-height:178px;display:flex;align-items:flex-end;justify-content:space-between;gap:34px;padding:30px 34px;border:1px solid #dce4f2;border-radius:18px;background:#fff;box-shadow:0 18px 46px rgba(30,48,86,.055)}.brand-hero>div:first-child{max-width:760px}.eyebrow{color:#2658d7;font:800 10px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.17em}.brand-hero h1{margin:12px 0 8px;font:750 32px/1.12 "Noto Serif SC","Songti SC",serif;letter-spacing:-.035em}.brand-hero p{margin:0;color:#748097;font-size:13px;line-height:1.75}.ready-seal{min-width:245px;padding:15px 17px;display:flex;align-items:center;gap:12px;border:1px solid #e1e7f0;border-radius:13px;background:#f8faff}.ready-seal>span{width:39px;height:39px;display:grid;place-items:center;border-radius:11px;color:#64748b;background:#e9edf5;font:800 12px Georgia,serif}.ready-seal b,.ready-seal small{display:block}.ready-seal b{font-size:12px}.ready-seal small{margin-top:4px;color:#8a95a7;font-size:10px}.ready-seal.ready{border-color:#bde4d4;background:#f2fbf7}.ready-seal.ready>span{color:#fff;background:#159467}.ready-seal.ready b{color:#107250}.page-error{margin-top:14px}.identity-card,.next-assets{margin-top:15px;border:1px solid #dfe5ef;border-radius:16px;background:#fff;box-shadow:0 12px 34px rgba(34,51,83,.04)}.identity-card>header,.next-assets>header{padding:19px 22px;border-bottom:1px solid #edf0f5}.identity-card>header,.identity-card>header>div,.next-assets>header>div{display:flex;align-items:center;justify-content:space-between;gap:12px}.identity-card h2,.next-assets h2{margin:0;font-size:16px}.identity-card header p,.next-assets header p{margin:4px 0 0;color:#8792a4;font-size:10.5px}.step{width:34px;height:34px;display:grid;place-items:center;border-radius:10px;color:#fff;background:#2658d7;font:800 11px Georgia,serif}.step.muted{color:#5e6b80;background:#edf1f7}.required-note{padding:5px 9px;border-radius:14px;color:#ad6325;background:#fff1df;font-size:9px;font-weight:800}.identity-grid{display:grid;grid-template-columns:1fr 1.25fr;gap:18px;padding:25px 24px}.identity-grid label>span,.identity-grid label>small{display:block}.identity-grid label>span{margin-bottom:8px;font-size:11px;font-weight:750}.identity-grid label>small{margin-top:7px;color:#8b96a7;font-size:9.5px}.identity-grid input{width:100%;height:46px;box-sizing:border-box;padding:0 13px;border:1px solid #dce3ee;border-radius:10px;outline:0;color:#18243b;background:#fbfcfe;font:inherit;font-size:13px;transition:.18s}.identity-grid input:focus{border-color:#6f91e8;background:#fff;box-shadow:0 0 0 3px rgba(38,88,215,.08)}.url-input{position:relative}.url-input i{position:absolute;left:13px;top:15px;color:#8a96a8;font-size:11px;font-style:normal;pointer-events:none}.url-input input{padding-left:58px}.rule-preview{margin:0 24px 23px;padding:16px 18px;display:flex;align-items:center;gap:13px;border:1px solid #dbe5f5;border-radius:12px;background:linear-gradient(110deg,#f7faff,#fbfdff)}.domain-mark{width:42px;height:42px;display:grid;place-items:center;border-radius:11px;color:#2658d7;background:#e8efff;font:900 9px ui-monospace,monospace}.rule-preview>div:nth-child(2){min-width:200px;flex:1}.rule-preview span,.rule-preview strong{display:block}.rule-preview span{color:#8390a3;font-size:9.5px}.rule-preview strong{margin-top:5px;font-size:13px}.flow{display:flex;align-items:center;gap:8px}.flow em{padding:6px 9px;border-radius:7px;color:#68758a;background:#edf1f7;font-size:9px;font-style:normal;font-weight:700}.flow b{color:#a0aabc}.flow .hit{color:#177553;background:#e8f7f0}.identity-card>footer{padding:17px 24px;display:flex;align-items:center;justify-content:space-between;gap:20px;border-top:1px solid #edf0f5}.identity-card footer p{margin:0;color:#7e899a;font-size:10px}.identity-card footer p span{margin-right:7px;padding:3px 6px;border-radius:8px;color:#2759d2;background:#eaf0ff;font-weight:800}.identity-card footer button{height:40px;padding:0 17px;border:0;border-radius:9px;color:#fff;background:#2658d7;font-weight:750;cursor:pointer;box-shadow:0 8px 20px rgba(38,88,215,.2)}.identity-card footer button:disabled{opacity:.55;cursor:wait}.asset-roadmap{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:17px 20px 20px}.asset-roadmap article{position:relative;padding:16px;border:1px solid #e4e8ef;border-radius:11px;background:#fbfcfe}.asset-roadmap b,.asset-roadmap span{display:block}.asset-roadmap b{font-size:12px}.asset-roadmap span{margin-top:5px;color:#8994a5;font-size:9.5px}.asset-roadmap i{position:absolute;right:12px;top:12px;padding:3px 6px;border-radius:8px;color:#7d889a;background:#eef1f5;font-size:8px;font-style:normal}@media(max-width:900px){.brand-assets-page{padding:18px 15px 60px}.brand-hero{align-items:flex-start;flex-direction:column;padding:24px}.ready-seal{min-width:0;width:100%;box-sizing:border-box}.identity-grid{grid-template-columns:1fr}.flow{display:none}.asset-roadmap{grid-template-columns:1fr}.identity-card>footer{align-items:flex-start;flex-direction:column}.identity-card footer button{width:100%}}@media(max-width:560px){.brand-hero h1{font-size:27px}.rule-preview{align-items:flex-start}.identity-grid{padding:20px 18px}.identity-card>footer{padding:16px 18px}}
.url-input.complete input{padding-left:13px}
</style>
