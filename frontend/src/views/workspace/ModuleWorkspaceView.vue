<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchModules, fetchTenants } from '../../api/auth'
import { session } from '../../store/session'

const router = useRouter()
const loading = ref(false)

const moduleMeta = {
  sem: {
    label: 'SEM 智投',
    code: 'SEM',
    description: '管理推广账号、投放计划、关键词和转化效果。',
    assetLabel: '推广账号',
    entry: '/sem/accounts',
  },
  seo: {
    label: 'SEO 增长',
    code: 'SEO',
    description: '按网站管理关键词、内容资产和自然搜索表现。',
    assetLabel: '网站',
    entry: '/seo/sites',
  },
  geo: {
    label: 'GEO 增长',
    code: 'GEO',
    description: '按品牌项目管理内容生产和 AI 搜索可见度。',
    assetLabel: '网站 / 品牌项目',
    entry: '/deal-sniper/geo/dashboard.html#/geo/projects',
    external: true,
  },
}

const modules = computed(() => session.modules
  .filter((item) => item.available && moduleMeta[item.module_code])
  .map((item) => ({ ...item, ...moduleMeta[item.module_code] })))
const customerName = computed(() => session.user?.tenant_id
  ? session.tenants.find((item) => item.id === session.user.tenant_id)?.name || session.user?.display_name
  : '平台管理员')

async function load() {
  loading.value = true
  try {
    const [moduleResult, tenantResult] = await Promise.all([fetchModules(), fetchTenants()])
    session.setModules(moduleResult.modules)
    session.setTenants(tenantResult.tenants)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function enter(item) {
  if (item.external) return window.location.assign(item.entry)
  router.push(item.entry)
}

onMounted(load)
</script>

<template>
  <div class="workspace" v-loading="loading">
    <section class="workspace-hero">
      <div>
        <div class="eyebrow">MY WORKSPACE</div>
        <h1>{{ customerName }}，选择要进入的工作台</h1>
        <p>使用同一个账号进入已开通模块；进入模块后，再选择该模块下的网站、品牌项目或推广账号。</p>
      </div>
      <div class="identity-card">
        <span>当前身份</span>
        <strong>{{ session.user?.role_label || '客户' }}</strong>
        <small v-if="session.user?.tenant_id">客户数据独立隔离</small>
        <small v-else>可按模块选择客户</small>
      </div>
    </section>

    <section v-if="modules.length" class="module-grid" aria-label="已开通模块">
      <article v-for="item in modules" :key="item.module_code" class="module-card" :class="`module-${item.module_code}`">
        <div class="module-top">
          <span class="module-mark">{{ item.code }}</span>
          <el-tag v-if="item.status === 'trial'" type="warning" effect="plain">试用中</el-tag>
          <el-tag v-else type="success" effect="plain">已开通</el-tag>
        </div>
        <h2>{{ item.label }}</h2>
        <p>{{ item.description }}</p>
        <div class="module-scope">
          <span>进入后管理</span>
          <strong>{{ item.assetLabel }}</strong>
        </div>
        <div class="module-foot">
          <span v-if="!session.user?.tenant_id">{{ item.tenant_count }} 个已开通客户</span>
          <span v-else>仅显示本客户数据</span>
          <el-button type="primary" @click="enter(item)">进入工作台</el-button>
        </div>
      </article>
    </section>

    <el-empty v-else-if="!loading" description="当前账号没有可用模块，请联系平台管理员开通" />
  </div>
</template>

<style scoped>
.workspace{padding:28px;max-width:1180px}.workspace-hero{display:flex;align-items:stretch;justify-content:space-between;gap:32px;padding:28px 30px;border:1px solid #dfe7f0;border-radius:16px;background:linear-gradient(135deg,#fff 0%,#f4f8fd 100%);box-shadow:0 12px 32px rgba(31,62,96,.06)}
.eyebrow{color:#2f6fa7;font-size:11px;font-weight:800;letter-spacing:1.4px}.workspace-hero h1{margin:9px 0 10px;color:#172b3f;font-size:27px}.workspace-hero p{max-width:720px;margin:0;color:#647487;font-size:14px;line-height:1.7}.identity-card{min-width:190px;padding:16px 18px;border-radius:12px;background:#163a5b;color:#fff;display:flex;flex-direction:column;justify-content:center}.identity-card span{font-size:11px;color:#a9c0d6}.identity-card strong{margin:5px 0;font-size:18px}.identity-card small{color:#d2deea}
.module-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:22px}.module-card{min-height:290px;padding:22px;border:1px solid #e0e7ef;border-radius:15px;background:#fff;display:flex;flex-direction:column;box-shadow:0 9px 24px rgba(31,62,96,.05);transition:transform .16s ease,box-shadow .16s ease}.module-card:hover{transform:translateY(-2px);box-shadow:0 14px 34px rgba(31,62,96,.1)}.module-top{display:flex;align-items:center;justify-content:space-between}.module-mark{width:52px;height:52px;border-radius:13px;display:grid;place-items:center;color:#fff;font-size:14px;font-weight:800;letter-spacing:.5px}.module-sem .module-mark{background:#2166a6}.module-seo .module-mark{background:#168265}.module-geo .module-mark{background:#7a55bd}.module-card h2{margin:19px 0 8px;color:#172b3f;font-size:21px}.module-card>p{min-height:46px;margin:0;color:#6b7a8c;font-size:13px;line-height:1.65}.module-scope{margin-top:18px;padding:12px 14px;border-radius:9px;background:#f5f8fb;display:flex;flex-direction:column;gap:4px}.module-scope span{color:#8795a5;font-size:11px}.module-scope strong{color:#31485e;font-size:13px}.module-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:auto;padding-top:20px;color:#8996a5;font-size:11px}
@media(max-width:900px){.module-grid{grid-template-columns:1fr}.workspace-hero{flex-direction:column}.identity-card{min-width:0}.workspace{padding:18px}}
</style>
