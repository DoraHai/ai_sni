<script setup>
/**
 * 媒体阵地 CRUD（media-placements）
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoMediaPlacement,
  deleteGeoMediaPlacement,
  listGeoMediaPlacements,
  patchGeoMediaPlacement,
} from '../../api/geoContent'
import { useClientPager } from '../../composables/useClientPager'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const qSearch = ref('')

const filteredItems = computed(() => {
  const q = qSearch.value.trim()
  let rows = items.value || []
  if (q) {
    rows = rows.filter(
      (r) =>
        String(r.name || '').includes(q) ||
        String(r.target_url || '').includes(q) ||
        String(r.channel_key || '').includes(q),
    )
  }
  return rows
})
const pager = useClientPager(filteredItems, { pageSize: 20 })

const kpi = computed(() => {
  const rows = items.value || []
  const published = rows.filter((r) => r.status === 'published')
  const planned = rows.filter((r) => r.status === 'planned' || r.status === 'in_progress')
  return {
    high: published.length,
    cited: published.filter((r) => r.channel_type === 'website' || r.channel_key).length,
    pending: planned.length,
    occupy: rows.filter((r) => /竞品|competitor/i.test(`${r.name}${r.authority_note || ''}`)).length,
  }
})

function byType(keys) {
  return (items.value || []).filter((r) => {
    const blob = `${r.channel_type || ''} ${r.channel_key || ''} ${r.name || ''}`.toLowerCase()
    return keys.some((k) => blob.includes(k))
  })
}
const siteItems = computed(() => byType(['website', '官网', 'site', 'blog']))
const thirdItems = computed(() => byType(['zhihu', '知乎', 'media', 'wechat', '公众号', 'news']))
const wikiItems = computed(() => byType(['baike', '百科', 'wiki', 'docs']))
const createOpen = ref(false)
const form = ref({
  name: '',
  channel_type: 'website',
  channel_key: '',
  target_url: '',
  status: 'planned',
  priority: 0,
  authority_note: '',
})

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户'
    items.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await listGeoMediaPlacements(tenantId.value)
    items.value = data.items || []
  } catch (e) {
    error.value = e.message || '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  try {
    await createGeoMediaPlacement({
      tenant_id: tenantId.value,
      name: form.value.name.trim(),
      channel_type: form.value.channel_type,
      channel_key: form.value.channel_key.trim() || null,
      target_url: form.value.target_url.trim() || null,
      status: form.value.status,
      priority: Number(form.value.priority) || 0,
      authority_note: form.value.authority_note.trim() || null,
    })
    ElMessage.success('已创建阵地')
    createOpen.value = false
    form.value = {
      name: '',
      channel_type: 'website',
      channel_key: '',
      target_url: '',
      status: 'planned',
      priority: 0,
      authority_note: '',
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

async function setStatus(row, status) {
  try {
    await patchGeoMediaPlacement(tenantId.value, row.id, { status })
    ElMessage.success('已更新状态')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`删除阵地「${row.name}」？`, '删除', {
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
    sub="同一套媒体资源可被 SEO / GEO 共用，GEO 更看重权威、可引用和信任链"
    :loading="loading"
  >
    <template #actions>
      <input v-model="qSearch" class="gd-search" placeholder="搜索媒体 / 信源…" />
      <button class="gd-btn" @click="router.push('/geo/publishing')">渠道库</button>
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn primary" @click="createOpen = true">+ 新增信源计划</button>
    </template>
    <div class="geo-dash geo-pl">

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <div class="gd-kpis">
      <div class="gd-card gd-stat"><div class="label">高权重信源</div><div class="value">{{ kpi.high }}</div><div class="delta hint">已发布阵地</div></div>
      <div class="gd-card gd-stat"><div class="label">已布局媒体</div><div class="value">{{ kpi.cited }}</div><div class="delta hint">官网/带蓝图 key</div></div>
      <div class="gd-card gd-stat"><div class="label">待补渠道</div><div class="value">{{ kpi.pending }}</div><div class="delta hint">规划中 / 进行中</div></div>
      <div class="gd-card gd-stat"><div class="label">竞品占位信源</div><div class="value">{{ kpi.occupy }}</div><div class="delta hint">名称或备注含竞品</div></div>
    </div>

    <div class="gd-kpis" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="gd-card">
        <div class="gd-hd"><h3>官网可信底座</h3><span class="gd-badge green">必做</span></div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li v-for="r in siteItems.slice(0, 3)" :key="r.id">{{ r.name }} · {{ r.status }}</li>
            <li v-if="!siteItems.length" class="gd-sub">还没有官网/博客阵地，建议补 About、FAQ、案例页。</li>
          </ul>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd"><h3>高质量第三方</h3><span class="gd-badge blue">拉权威</span></div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li v-for="r in thirdItems.slice(0, 3)" :key="r.id">{{ r.name }} · {{ r.status }}</li>
            <li v-if="!thirdItems.length" class="gd-sub">还没有知乎/公众号/媒体计划。</li>
          </ul>
        </div>
      </div>
      <div class="gd-card">
        <div class="gd-hd"><h3>百科与资料库</h3><span class="gd-badge amber">纠偏</span></div>
        <div class="gd-bd">
          <ul class="gd-sources">
            <li v-for="r in wikiItems.slice(0, 3)" :key="r.id">{{ r.name }} · {{ r.status }}</li>
            <li v-if="!wikiItems.length" class="gd-sub">还没有百科/文档类信源。</li>
          </ul>
        </div>
      </div>
    </div>

    <el-table :data="pager.pagedItems" stripe empty-text="暂无阵地" size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="channel_type" label="类型" width="110" />
      <el-table-column prop="channel_key" label="蓝图 key" width="100" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="priority" label="优先级" width="80" />
      <el-table-column prop="target_url" label="URL" min-width="160" show-overflow-tooltip />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status !== 'published'"
            link
            type="success"
            @click="setStatus(row, 'published')"
          >标为已发布</el-button>
          <el-button
            v-if="row.status !== 'planned'"
            link
            @click="setStatus(row, 'planned')"
          >标为规划中</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="createOpen" title="新建媒体阵地" width="480px">
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-input v-model="form.channel_type" placeholder="website / zhihu / ranking …" />
        </el-form-item>
        <el-form-item label="蓝图 key">
          <el-input v-model="form.channel_key" />
        </el-form-item>
        <el-form-item label="目标 URL">
          <el-input v-model="form.target_url" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="planned" value="planned" />
            <el-option label="in_progress" value="in_progress" />
            <el-option label="published" value="published" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.authority_note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-pl { padding: 4px 2px 24px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; }
.header-actions { display: flex; gap: 8px; }
.mb { margin-bottom: 12px; }
</style>
