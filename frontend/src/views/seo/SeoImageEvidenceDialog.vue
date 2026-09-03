<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchSeoImageEvidence } from '../../api/seo'

const props = defineProps({ visible: Boolean, tenantId: Number, siteId: Number, page: Object })
const emit = defineEmits(['update:visible'])
const data = ref(null), loading = ref(false), error = ref(''), filter = ref('all')
let generation = 0
const evidence = computed(() => data.value?.evidence)
const items = computed(() => (evidence.value?.items || []).filter(row => filter.value === 'all' || row.alt_state === filter.value))
const stateLabel = state => ({ missing: '缺少 Alt 属性', empty: '空 Alt（需判断用途）', whitespace: 'Alt 仅含空白' }[state] || '未知')
const time = value => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) + ' CST' : '—'
async function load() {
  const token = ++generation
  data.value = null; error.value = ''; loading.value = false
  if (!props.visible || !props.tenantId || !props.siteId || !props.page?.id) return
  loading.value = true
  try {
    const response = await fetchSeoImageEvidence({ tenantId: props.tenantId, siteId: props.siteId, pageId: props.page.id })
    if (token === generation) data.value = response
  } catch (e) { if (token === generation) error.value = e.message || '读取失败，请重试' }
  finally { if (token === generation) loading.value = false }
}
watch(() => [props.visible, props.tenantId, props.siteId, props.page?.id], () => {
  filter.value = 'all'; load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { ++generation })
</script>

<template>
  <el-dialog :model-value="visible" title="图片 Alt 核查明细（程序证据）" width="min(980px, 96vw)" @update:model-value="emit('update:visible', $event)">
    <p class="wrap">#{{ page?.id }} {{ page?.url }}</p>
    <el-alert title="仅读取抓取存档，不调用 AI、不加载图片、不修改官网。空 Alt 可能用于装饰图片；图片用途及整改文本需人工判断。" type="info" :closable="false" />
    <p v-if="loading" role="status">正在读取图片证据…</p>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="data">
      <p>存档抓取时间：{{ time(data.fetched_at) }}<span v-if="data.snapshot_id"> · 快照 #{{ data.snapshot_id }}</span></p>
      <el-alert v-if="data.fetch_error" title="最近抓取失败，不能据此判断图片情况；未回退展示旧成功记录。" type="warning" :closable="false" />
      <p v-else-if="!evidence">{{ data.snapshot_id ? '旧存档未记录逐图明细，需要后续成功扫描才能补齐。' : '尚无抓取存档，不能判断图片情况。' }}<span v-if="data.legacy_candidate_count != null">旧计数：{{ data.legacy_candidate_count }}（不代表全部需要修改）。</span></p>
      <template v-else>
        <p>静态 HTML 中 {{ evidence.images_count }} 张图片，{{ evidence.candidate_count }} 个待核查项：缺属性 {{ evidence.counts.missing }}、空 Alt {{ evidence.counts.empty }}、仅空白 {{ evidence.counts.whitespace }}。不含脚本动态生成图片。</p>
        <p>位置按静态 HTML 中的图片顺序记录；地址仅为属性证据，不代表浏览器最终选用或已验证可访问的图片。</p>
        <el-alert v-if="evidence.truncated" :title="`仅保存前 ${evidence.limit} 个候选项，以下明细及筛选结果不覆盖全部图片。`" type="warning" :closable="false" />
        <el-select v-model="filter" aria-label="Alt 类型筛选" class="filter">
          <el-option label="全部候选项" value="all" /><el-option label="缺少 Alt 属性" value="missing" />
          <el-option label="空 Alt" value="empty" /><el-option label="仅空白" value="whitespace" />
        </el-select>
        <el-table :data="items" max-height="420" :empty-text="evidence.candidate_count ? '当前筛选下没有已记录的候选项' : '本次静态 HTML 未发现缺少或空 Alt 的图片；不代表图片描述质量已通过'">
          <el-table-column label="位置" width="165"><template #default="{ row }">第 {{ row.position }} 张 · {{ row.section }}<small v-if="row.element_id">ID：{{ row.element_id }}</small><small>{{ row.in_link ? '位于链接内' : '不在链接内' }}</small><small v-if="row.role">声明 role：{{ row.role }}（非用途结论）</small></template></el-table-column>
          <el-table-column label="图片地址证据" min-width="330"><template #default="{ row }"><div class="wrap">{{ row.source_url || '未取得可展示的 HTTP(S) 地址' }}</div><small v-if="row.source_url_truncated">地址过长，已截断；请按图片位置核对完整地址。</small><small v-if="row.source_attribute">属性：{{ row.source_attribute }}</small><small v-if="row.srcset" class="wrap">候选 srcset（可能截断）：{{ row.srcset }}</small></template></el-table-column>
          <el-table-column label="Alt 状态" width="185"><template #default="{ row }">{{ stateLabel(row.alt_state) }}</template></el-table-column>
        </el-table>
      </template>
    </template>
    <template #footer><el-button :loading="loading" @click="load">重新读取存档</el-button><el-button @click="emit('update:visible', false)">关闭</el-button></template>
  </el-dialog>
</template>

<style scoped>
p{font-size:14px;line-height:1.7}.wrap,small{overflow-wrap:anywhere;white-space:normal}small{display:block;font-size:13px;color:#657774;margin-top:6px}.filter{width:230px;margin:10px 0}
</style>
