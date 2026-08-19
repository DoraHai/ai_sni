<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addNegativeWord, fetchNegativeWords, removeNegativeWord } from '../../api/negatives'
import { fetchCandidates, updateCandidateStatus } from '../../api/expansion'
import { fetchAdgroupList, fetchCampaignList } from '../../api/keywords'
import AddToPlanDialog from '../../components/AddToPlanDialog.vue'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

const loading = ref(false)
const error = ref('')
const negData = ref(null) // 现有否词 + 重复/冲突检测
const scanData = ref(null) // 自研扫描待审（拓词"建议否定"候选，pending）
const rejectedData = ref(null) // 已驳回（同候选，ignored）

const view = ref('review') // review=待审建议 existing=现有否词 rejected=已驳回
const addToPlanDialogRef = ref(null)

const filters = reactive({ scope: '', match: '', flag: '', q: '' })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [neg, scan, rejected] = await Promise.all([
      fetchNegativeWords({ tenantId: TENANT_ID.value, ...filters }),
      fetchCandidates({
        tenantId: TENANT_ID.value, suggestedCategory: 'negative', status: 'pending',
        page: 1, pageSize: 200,
      }),
      fetchCandidates({
        tenantId: TENANT_ID.value, suggestedCategory: 'negative', status: 'ignored',
        page: 1, pageSize: 200,
      }),
    ])
    negData.value = neg
    scanData.value = scan
    rejectedData.value = rejected
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

let qTimer = null
watch(() => [filters.scope, filters.match, filters.flag], load)
watch(() => filters.q, () => {
  clearTimeout(qTimer)
  qTimer = setTimeout(load, 400)
})

const summary = computed(() => negData.value?.summary)
// 待审 = 自研扫描 pending + 本地检测出的重复/冲突
const reviewCount = computed(() =>
  (scanData.value?.total || 0) + (summary.value?.duplicates || 0) + (summary.value?.conflicts || 0))

// 待审建议合并行：自研扫描候选在前（可操作），重复/冲突检测在后（写回类禁用）
const reviewRows = computed(() => {
  const scans = (scanData.value?.candidates || []).map((c) => ({
    ...c,
    kind: 'scan',
    id: c.id,
    word: c.word,
    typeLabel: '自研扫描',
    typeCls: 'tag-scan',
    scopeText: '待人工定（线下添加时选）',
    matchLabel: '—',
    trigger: c.impression != null ? `${c.impression} 次` : '—',
    conversions30d: c.conversions_30d,
    basis: [
      c.matched_keyword ? `触发词「${c.matched_keyword}」` : null,
      c.impression != null ? `窗口展现 ${c.impression} / 点击 ${c.click ?? 0}` : null,
      c.potential_score != null ? `潜力分 ${c.potential_score}` : null,
      '来自搜索词报告（已触发未添加的低价值词）',
    ].filter(Boolean).join(' · '),
  }))
  const detected = (negData.value?.items || [])
    .filter((i) => i.flags.length)
    .map((i) => ({
      kind: i.flags.includes('conflict') ? 'conflict' : 'duplicate',
      id: `${i.scope}-${i.campaign_id}-${i.adgroup_id}-${i.match}-${i.word}`,
      word: i.word,
      typeLabel: i.flags.includes('conflict') ? '冲突检测' : '重复检测',
      typeCls: i.flags.includes('conflict') ? 'tag-conflict' : 'tag-dup',
      scopeText: scopeText(i),
      matchLabel: i.match_label,
      trigger: '—',
      basis: i.note,
      scope: i.scope, match: i.match, adgroup_id: i.adgroup_id, adgroup_name: i.adgroup_name,
    }))
  return [...scans, ...detected]
})

function scopeText(i) {
  if (i.scope === 'adgroup') return `单元级 · ${i.adgroup_name || i.adgroup_id}`
  return `计划级 · ${i.campaign_name || i.campaign_id}`
}

async function setScanStatus(row, status, label) {
  try {
    await updateCandidateStatus({ tenantId: TENANT_ID.value, candidateId: row.id, status })
    ElMessage.success(`「${row.word}」${label}`)
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openAddToPlan(row) {
  addToPlanDialogRef.value?.open(row)
}

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))

// 添加否词弹框（单元级 updateAdgroup 写回）
const negDialog = reactive({ visible: false, word: '', campaignId: null, adgroupId: null, matchMode: 'exact', submitting: false })
const negCampaigns = ref([])
const negAdgroups = ref([])

async function openAddNeg(word = '') {
  Object.assign(negDialog, { visible: true, word, campaignId: null, adgroupId: null, matchMode: 'exact', submitting: false })
  negAdgroups.value = []
  if (!negCampaigns.value.length) {
    try {
      negCampaigns.value = (await fetchCampaignList({ tenantId: TENANT_ID.value })).campaigns || []
    } catch (e) {
      ElMessage.error('加载计划失败：' + (e.message || ''))
    }
  }
}

async function onNegCampaign(cid) {
  negDialog.adgroupId = null
  negAdgroups.value = []
  if (!cid) return
  try {
    negAdgroups.value = (await fetchAdgroupList({ tenantId: TENANT_ID.value, campaignId: cid })).adgroups || []
  } catch (e) {
    ElMessage.error('加载单元失败：' + (e.message || ''))
  }
}

async function submitAddNeg() {
  if (!negDialog.word.trim()) return ElMessage.warning('请输入否词')
  if (!negDialog.adgroupId) return ElMessage.warning('请选择目标单元')
  negDialog.submitting = true
  try {
    const res = await addNegativeWord({ tenantId: TENANT_ID.value, word: negDialog.word.trim(), adgroupId: negDialog.adgroupId, matchMode: negDialog.matchMode })
    if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上')
    else ElMessage.success('已添加否词')
    negDialog.visible = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    negDialog.submitting = false
  }
}

async function removeNeg(row) {
  if (row.scope !== 'adgroup') return ElMessage.warning('计划级否词暂只能在百度后台删除（updateCampaign 未做）')
  try {
    await ElMessageBox.confirm(
      `将从单元「${row.adgroup_name || row.adgroup_id}」删除否词「${row.word}」（${row.match_label || ''}）。\n演练模式下不真改线上。`,
      '删除否词', { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = await removeNegativeWord({ tenantId: TENANT_ID.value, word: row.word, adgroupId: row.adgroup_id, matchMode: row.match })
    if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上')
    else ElMessage.success('已删除否词')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

// 顶栏切换客户后重新拉数
watch(TENANT_ID, load)

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">否词管理</div>
        <div class="page-desc">
          现有否词 <b>{{ fmtInt(summary?.total) }}</b> 条 ·
          待审建议 <b class="danger-text">{{ fmtInt(reviewCount) }}</b> 条 ·
          数据源：百度计划/单元否词（每日同步）+ 自研搜索词扫描 · 添加/删除否词支持单元级写回（dry-run 保护，演练模式不真改线上）
        </div>
      </div>
      <div class="page-actions">
        <el-button v-if="session.canEdit('optimize.negatives')" type="primary" @click="openAddNeg()">手动添加否词</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- KPI 条 -->
    <div class="kpi-strip">
      <div class="kpi-mini danger">
        <div class="km-label">重复否词（本地检测）</div>
        <div class="km-value">{{ fmtInt(summary?.duplicates) }}</div>
        <div class="km-meta">单元级与所属计划重复，可清理</div>
      </div>
      <div class="kpi-mini warn">
        <div class="km-label">冲突否词（本地检测）</div>
        <div class="km-value">{{ fmtInt(summary?.conflicts) }}</div>
        <div class="km-meta">与现役关键词冲突，导致漏展</div>
      </div>
      <div class="kpi-mini danger">
        <div class="km-label">自研搜索词扫描</div>
        <div class="km-value">{{ fmtInt(scanData?.total) }}</div>
        <div class="km-meta">来自拓词"建议否定"候选</div>
      </div>
      <div class="kpi-mini dim">
        <div class="km-label">冷门否词</div>
        <div class="km-value">M2</div>
        <div class="km-meta">需否词触发数据，百度暂不提供</div>
      </div>
    </div>

    <!-- 视图 tabs -->
    <div class="view-tabs">
      <span class="view-tab" :class="{ active: view === 'review' }" @click="view = 'review'">
        待审建议<span class="v-count">{{ fmtInt(reviewCount) }}</span>
      </span>
      <span class="view-tab" :class="{ active: view === 'existing' }" @click="view = 'existing'">
        现有否词<span class="v-count">{{ fmtInt(summary?.total) }}</span>
      </span>
      <span class="view-tab" :class="{ active: view === 'rejected' }" @click="view = 'rejected'">
        已驳回<span class="v-count">{{ fmtInt(rejectedData?.total) }}</span>
      </span>
    </div>

    <!-- ===== 待审建议 ===== -->
    <div v-if="view === 'review'" class="table-panel">
      <el-table :data="reviewRows" row-key="id" :fit="true">
        <el-table-column label="否词建议" width="130">
          <template #default="{ row }"><b>{{ row.word }}</b></template>
        </el-table-column>
        <el-table-column label="建议类型" width="90">
          <template #default="{ row }">
            <span class="src-tag" :class="row.typeCls">{{ row.typeLabel }}</span>
          </template>
        </el-table-column>
        <el-table-column label="作用范围" width="140">
          <template #default="{ row }">{{ row.scopeText }}</template>
        </el-table-column>
        <el-table-column label="匹配方式" width="80" align="center">
          <template #default="{ row }">{{ row.matchLabel }}</template>
        </el-table-column>
        <el-table-column label="近 30 天触发" width="90" align="right">
          <template #default="{ row }"><span class="num">{{ row.trigger }}</span></template>
        </el-table-column>
        <el-table-column label="近30天转化" width="90" align="right">
          <template #default="{ row }">
            <span class="num">{{ row.kind === 'scan' ? fmtInt(row.conversions30d) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="判定依据" width="170">
          <template #default="{ row }">
            <el-tooltip :content="row.basis" placement="top" :disabled="!row.basis">
              <span class="basis basis-compact">{{ row.basis }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="196">
          <template #default="{ row }">
            <div class="row-actions" v-if="row.kind === 'scan' && session.canEdit('optimize.negatives')">
              <el-tooltip content="选目标单元加成否词（updateAdgroup 写回，dry-run 保护）" placement="top">
                <el-button class="review-action is-negative" size="small" @click="openAddNeg(row.word)">加否词</el-button>
              </el-tooltip>
              <el-tooltip content="打开加入计划弹窗，选单元、出价和匹配方式后设为正式关键词" placement="top">
                <el-button class="review-action is-expand" size="small" @click="openAddToPlan(row)">设为关键词</el-button>
              </el-tooltip>
              <el-button class="review-action is-dismiss" size="small" @click="setScanStatus(row, 'ignored', '已驳回')">驳回</el-button>
            </div>
            <div class="row-actions" v-else-if="session.canEdit('optimize.negatives')">
              <el-tooltip v-if="row.scope === 'adgroup'" :content="row.kind === 'conflict' ? '删除该单元否词解除冲突' : '删除重复的单元否词'" placement="top">
                <el-button size="small" type="danger" plain @click="removeNeg(row)">{{ row.kind === 'conflict' ? '删除解冲突' : '删除合并' }}</el-button>
              </el-tooltip>
              <el-tooltip v-else content="计划级否词暂只能在百度后台删除（updateCampaign 未做）" placement="top">
                <span><el-button size="small" disabled>计划级·后台处理</el-button></span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">暂无待审建议。自研扫描来自拓词页"建议否定"候选；重复/冲突由本地检测自动产出。</div>
        </template>
      </el-table>
    </div>

    <!-- ===== 现有否词 ===== -->
    <template v-if="view === 'existing'">
      <div class="filter-row">
        <el-select v-model="filters.scope" placeholder="作用范围 · 全部" clearable style="width: 150px">
          <el-option label="计划级" value="campaign" />
          <el-option label="单元级" value="adgroup" />
        </el-select>
        <el-select v-model="filters.match" placeholder="匹配方式 · 全部" clearable style="width: 150px">
          <el-option label="短语否" value="phrase" />
          <el-option label="精确否" value="exact" />
        </el-select>
        <el-select v-model="filters.flag" placeholder="检测标记 · 全部" clearable style="width: 150px">
          <el-option label="重复" value="duplicate" />
          <el-option label="冲突" value="conflict" />
        </el-select>
        <el-input v-model="filters.q" placeholder="搜索否词 / 计划 / 单元" clearable style="width: 220px" />
      </div>
      <div class="table-panel">
        <el-table :data="negData?.items || []" row-key="id">
          <el-table-column label="否词" min-width="150">
            <template #default="{ row }"><b>{{ row.word }}</b></template>
          </el-table-column>
          <el-table-column label="匹配方式" width="92">
            <template #default="{ row }">
              <span class="match-tag">{{ row.match_label }}</span>
            </template>
          </el-table-column>
          <el-table-column label="作用范围" min-width="200">
            <template #default="{ row }">
              <span class="scope-tag" :class="row.scope">{{ scopeText(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="所属计划" min-width="150">
            <template #default="{ row }">{{ row.campaign_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="检测标记" min-width="220">
            <template #default="{ row }">
              <template v-if="row.flags.length">
                <span v-if="row.flags.includes('duplicate')" class="src-tag tag-dup">重复</span>
                <span v-if="row.flags.includes('conflict')" class="src-tag tag-conflict">冲突</span>
                <span class="basis" style="margin-left: 6px">{{ row.note }}</span>
              </template>
              <span v-else class="dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button
                v-if="session.canEdit('optimize.negatives') && row.scope === 'adgroup'"
                size="small" type="danger" plain @click="removeNeg(row)"
              >删除</el-button>
              <el-tooltip v-else-if="session.canEdit('optimize.negatives')" content="计划级否词暂只能在百度后台删除" placement="left">
                <span class="dim" style="font-size: 11px">计划级</span>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>
        <div class="table-footer"><span>共 {{ fmtInt(negData?.total || 0) }} 条（随每日 02:00 维度同步更新）</span></div>
      </div>
    </template>

    <!-- ===== 已驳回 ===== -->
    <div v-if="view === 'rejected'" class="table-panel">
      <el-table :data="rejectedData?.candidates || []" row-key="id">
        <el-table-column label="否词建议" min-width="160">
          <template #default="{ row }"><b>{{ row.word }}</b></template>
        </el-table-column>
        <el-table-column label="触发词" min-width="150">
          <template #default="{ row }">{{ row.matched_keyword || '—' }}</template>
        </el-table-column>
        <el-table-column label="窗口展现 / 点击" width="130" align="right">
          <template #default="{ row }">
            <span class="num">{{ fmtInt(row.impression) }} / {{ fmtInt(row.click) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="潜力分" width="90" align="right">
          <template #default="{ row }"><span class="num">{{ row.potential_score ?? '—' }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="session.canEdit('optimize.negatives')" size="small" text @click="setScanStatus(row, 'pending', '已恢复待审')">恢复待审</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-line">本期还没有驳回过否词建议。</div></template>
      </el-table>
    </div>

    <!-- 配额说明 -->
    <div class="note">
      <b>否词配额</b>：当前已使用 <b>{{ fmtInt(summary?.total) }}</b> 条（计划级 {{ fmtInt(summary?.campaign_level) }} + 单元级
      {{ fmtInt(summary?.adgroup_level) }}；短语否 {{ fmtInt(summary?.phrase) }} / 精确否 {{ fmtInt(summary?.exact) }}）。
      配额上限按百度账户星级浮动（200-900 条），星级数据待接入；定期清理重复/冷门否词可释放配额。
    </div>

    <AddToPlanDialog ref="addToPlanDialogRef" :tenant-id="TENANT_ID" @success="load" />

    <!-- 添加否词弹框（单元级 updateAdgroup 写回） -->
    <el-dialog v-model="negDialog.visible" title="添加否词" width="440px">
      <el-form label-width="72px" label-position="left">
        <el-form-item label="否词">
          <el-input v-model="negDialog.word" placeholder="输入否定关键词" />
        </el-form-item>
        <el-form-item label="计划">
          <el-select v-model="negDialog.campaignId" placeholder="选择计划" style="width: 100%" @change="onNegCampaign">
            <el-option v-for="c in negCampaigns" :key="c.campaign_id" :label="c.campaign_name" :value="c.campaign_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="单元">
          <el-select v-model="negDialog.adgroupId" placeholder="先选计划" style="width: 100%" :disabled="!negDialog.campaignId">
            <el-option v-for="a in negAdgroups" :key="a.adgroup_id" :label="a.adgroup_name" :value="a.adgroup_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="negDialog.matchMode">
            <el-radio label="exact">精确否</el-radio>
            <el-radio label="phrase">短语否</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div class="neg-tip">否词加到所选单元（单元级）；受 dry-run 保护，演练模式下不真改线上。</div>
      <template #footer>
        <el-button @click="negDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="negDialog.submitting" @click="submitAddNeg">确认添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.danger-text { color: #e24b4a; }

.kpi-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1100px) { .kpi-strip { grid-template-columns: repeat(2, 1fr); } }
.kpi-mini { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 12px 14px; }
.kpi-mini.danger { border-left: 3px solid #e24b4a; }
.kpi-mini.warn { border-left: 3px solid #ba7517; }
.kpi-mini.dim { opacity: 0.65; }
.km-label { font-size: 11px; color: var(--sem-text-sub); }
.km-value { font-size: 22px; font-weight: 700; color: var(--sem-text); margin: 4px 0 2px; font-variant-numeric: tabular-nums; }
.km-meta { font-size: 11px; color: #9ca3af; }

.view-tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.view-tab { padding: 7px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; color: var(--sem-text-sub); background: #fff; border: 1px solid var(--sem-border); user-select: none; }
.view-tab.active { color: var(--sem-primary); background: #eff4fb; border-color: var(--sem-primary); font-weight: 500; }
.v-count { font-size: 11px; margin-left: 6px; color: #9ca3af; }
.view-tab.active .v-count { color: var(--sem-primary); }

.filter-row { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; margin-bottom: 12px; }
.table-footer { padding: 10px 14px; font-size: 12px; color: var(--sem-text-sub); border-top: 1px solid var(--sem-border); }
.empty-line { font-size: 12px; color: var(--sem-text-sub); padding: 18px 0; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #c0c4cc; }
.basis { font-size: 11px; color: var(--sem-text-sub); line-height: 1.5; }
.basis-compact { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.src-tag { font-size: 11px; padding: 1px 7px; border-radius: 3px; white-space: nowrap; }
.tag-scan { background: #eff4fb; color: #185fa5; }
.tag-dup { background: #fef6f6; color: #e24b4a; }
.tag-conflict { background: #fcf6ea; color: #ba7517; }
.match-tag { font-size: 11px; padding: 1px 7px; border-radius: 3px; background: #f3f4f6; color: #4b5563; }
.scope-tag { font-size: 11px; padding: 1px 7px; border-radius: 3px; }
.scope-tag.campaign { background: #e5f4ed; color: #1d9e75; }
.scope-tag.adgroup { background: #f2ebfb; color: #6b47b5; }

.row-actions { display: flex; gap: 4px; align-items: center; }
.review-action { height: 26px; margin: 0 !important; padding: 0 9px; border-radius: 5px; font-size: 11px; font-weight: 600; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.review-action.is-negative { background: #fff; border-color: #f0c998; color: #b86b16; }
.review-action.is-negative:hover { background: #fff7ed; border-color: #e7a350; color: #9e5710; }
.review-action.is-expand { background: #edf5ff; border-color: #b7d4f2; color: #1768ad; }
.review-action.is-expand:hover { background: #dfefff; border-color: #79addd; color: #10578f; }
.review-action.is-dismiss { background: #fff; border-color: #d8dee8; color: #667085; }
.review-action.is-dismiss:hover { background: #f8fafc; border-color: #aeb9c9; color: #475467; }
.note { padding: 10px 12px; background: #fffbf4; border: 1px solid #fed7aa; border-radius: 6px; font-size: 11px; color: #4b5563; line-height: 1.8; }
.note b { color: #9a3412; }
.neg-tip { font-size: 12px; color: #ba7517; margin-top: 4px; }
</style>
