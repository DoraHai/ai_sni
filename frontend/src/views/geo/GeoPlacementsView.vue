<script setup>
/**
 * 媒体 / 信源策略：勾选权威阵地，增删查改信源计划。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoMediaPlacement,
  deleteGeoMediaPlacement,
  listGeoMediaPlacements,
  patchGeoMediaPlacement,
} from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const items = ref([])
const qSearch = ref('')
const dialogOpen = ref(false)
const saving = ref(false)
const editing = ref(null)

const CHANNEL_OPTIONS = [
  { value: 'website', slug: 'website', label: '网站', icon: '⌂' },
  { value: 'encyclopedia', slug: 'encyclopedia', label: '百科', icon: '▣' },
  { value: 'wiki', slug: 'wiki', label: '百科', icon: '▣' },
  { value: 'zhihu', slug: 'community', label: '社区', icon: '◉' },
  { value: 'community', slug: 'community', label: '社区', icon: '◉' },
  { value: 'community_qa', slug: 'community', label: '社区', icon: '◉' },
  { value: 'wechat', slug: 'wechat', label: '公众号', icon: '▣' },
  { value: 'news', slug: 'news', label: '新闻', icon: '☰' },
  { value: 'industry_media', slug: 'media', label: '行业媒体', icon: '📰' },
  { value: 'media', slug: 'media', label: '行业媒体', icon: '📰' },
  { value: 'toutiao', slug: 'toutiao', label: '头条', icon: '☰' },
  { value: 'baijiahao', slug: 'baijiahao', label: '百家号', icon: '☰' },
  { value: 'visual_content', slug: 'video', label: '视频', icon: '▶' },
  { value: 'other', slug: 'other', label: '其他', icon: '○' },
]

const STATUS_META = {
  planned: { en: 'planned', zh: '计划中', tone: 'ok' },
  in_progress: { en: 'in_progress', zh: '进行中', tone: 'warn' },
  published: { en: 'published', zh: '已发布', tone: 'info' },
  archived: { en: 'archived', zh: '已归档', tone: 'muted' },
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

function typeMeta(row) {
  const key = String(row.channel_type || row.channel_key || '').toLowerCase()
  return CHANNEL_OPTIONS.find((c) => c.value === key) || {
    value: key,
    slug: key || 'other',
    label: row.channel_type || '其他',
    icon: '○',
  }
}

function statusMeta(row) {
  return STATUS_META[row.status] || {
    en: row.status || '—',
    zh: row.status || '—',
    tone: 'muted',
  }
}



const filteredItems = computed(() => {
  const q = qSearch.value.trim().toLowerCase()
  let rows = items.value || []
  if (q) {
    rows = rows.filter((r) =>
      `${r.name || ''} ${r.target_url || ''} ${r.channel_type || ''} ${r.channel_key || ''}`
        .toLowerCase()
        .includes(q),
    )
  }
  return rows
})
const pager = useClientPager(filteredItems, { pageSize: 20 })

watch(qSearch, () => pager.resetPage())

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

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  dialogOpen.value = true
}

function openEdit(row) {
  editing.value = row
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
    if (editing.value) {
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

async function markPublished(row) {
  try {
    await patchGeoMediaPlacement(tenantId.value, row.id, { status: 'published' })
    ElMessage.success('已标记为已发布')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function remove(row) {
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
    title="信源策略"
    :show-period="false"
    sub="同一套媒体选题可供 SEO / GEO 共用，GEO 圈选高权威、可引用的信任源"
    :loading="loading"
  >
    <template #actions>
      <input v-model="qSearch" class="gd-search" placeholder="搜索媒体 / 信源…" />
      <button class="gd-btn" @click="load">刷新</button>
      <button class="gd-btn primary" @click="openCreate">+ 新增信源计划</button>
    </template>

    <div class="geo-dash">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <div class="geo-table-card">
        <el-table :data="pager.pagedItems" empty-text="暂无信源计划" class="pack-table">
          <el-table-column label="名称" width="440">
            <template #default="{ row }">
              <div class="name">{{ row.name }}</div>
              <div v-if="row.authority_note" class="note">{{ row.authority_note }}</div>
              <a
                v-if="row.target_url"
                :href="row.target_url"
                target="_blank"
                rel="noopener"
                class="url"
              >{{ row.target_url }}</a>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="148">
            <template #default="{ row }">
              <div class="geo-type-cell">
                <span class="geo-type-icon">{{ typeMeta(row).icon }}</span>
                <span class="type-label">{{ typeMeta(row).label }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <span class="geo-status-cell">
                <i class="geo-status-dot" :class="statusMeta(row).tone" />
                {{ statusMeta(row).zh }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="168">
            <template #default="{ row }">
              <div class="geo-act">
                <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
                <el-button
                  v-if="row.status !== 'published'"
                  link
                  class="act-publish"
                  @click="markPublished(row)"
                >发布</el-button>
                <el-button link type="danger" @click="remove(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column min-width="24" class-name="col-fill" />
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
      </div>
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
              :label="`${c.label} · ${c.slug}`"
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
            <el-option label="已发布" value="published" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="备注">
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
.name { font-weight: 650; color: #1e2330; }
.note {
  margin-top: 3px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
}
.url {
  display: inline-block;
  margin-top: 4px;
  color: #6d28d9;
  text-decoration: none;
  font-size: 12px;
}
.url:hover { text-decoration: underline; }
.type-label {
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}
.geo-status-cell { white-space: nowrap; }
.note { max-width: 52ch; }
.mb { margin-bottom: 12px; }
</style>
