<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchOcpcPackages } from '../../api/ocpc'
import { session } from '../../store/session'
import { formatUtcTimestamp } from '../../utils/dateTime'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动
const tenantName = computed(() => session.tenants.find((item) => item.id === TENANT_ID.value)?.name || '当前客户')

const loading = ref(false)
const error = ref('')
const data = ref(null)
let loadVersion = 0

async function load() {
  const version = ++loadVersion
  const tenantId = TENANT_ID.value
  if (!tenantId) return
  loading.value = true
  error.value = ''
  try {
    const result = await fetchOcpcPackages({ tenantId })
    if (version !== loadVersion || tenantId !== TENANT_ID.value) return
    data.value = result
  } catch (e) {
    if (version === loadVersion && tenantId === TENANT_ID.value) {
      error.value = '页面数据暂时无法加载，请稍后重试'
    }
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

watch(TENANT_ID, () => { data.value = null; load() })
onMounted(load)

const fmtMoney = (v) => (v == null ? '—' : '¥' + Number(v).toFixed(2))
const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))

// 学习状态 → 配色（学习中=黄、学习失败=红、学习结束/投放中=绿、未生效=灰）
const STATUS_CLS = { 0: 'gray', 1: 'green', 2: 'amber', 3: 'red', 4: 'green' }

const summary = computed(() => data.value?.summary || {})

// 数据充足度横幅文案
const adequacyBanner = computed(() => {
  const s = summary.value
  if (data.value && data.value.total === 0) return null
  const n = s.account_conv_7d ?? 0
  const min = s.learn_weekly_min ?? 15
  if (s.adequacy === 'sufficient') {
    return { type: 'success', title: `近 7 天电话转化 ${n} 个，达到 OCPC 学习参考门槛（≥${min}/周），数据基本喂得动。` }
  }
  if (s.adequacy === 'low') {
    return { type: 'warning', title: `近 7 天电话转化仅 ${n} 个，低于 OCPC 学习参考门槛（≥${min}/周）。转化量偏少时 OCPC 模型学不动，效果可能不如手动 CPC——这是 OCPC 的硬前提，不是平台限制。` }
  }
  return { type: 'error', title: `近 7 天电话转化为 0。OCPC 靠转化数据喂模型，没有转化等于让算法盲投，不建议在此状态下开/调 OCPC。` }
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">oCPC 投放</div>
        <div class="page-desc">
          数据源：百度 OcpcService/getTargetPackageList 同步（只读）· oCPC = 设「目标转化出价」由百度算法自动出价，与关键词 CPC 出价是两套机制
          <template v-if="summary.data_until"> · 转化数据截至 {{ summary.data_until }}</template>
        </div>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- 数据充足度横幅：OCPC 能不能用，先看转化数据喂不喂得饱 -->
    <el-alert
      v-if="adequacyBanner"
      :type="adequacyBanner.type"
      :title="adequacyBanner.title"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
    />

    <!-- 账户口径统计卡 -->
    <div v-if="data && data.total > 0" class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">oCPC 策略数</div>
        <div class="stat-value">{{ fmtInt(data.total) }}</div>
        <div class="stat-sub">目标转化包（绑定计划级）</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">近 7 天电话转化</div>
        <div class="stat-value">{{ fmtInt(summary.account_conv_7d) }}</div>
        <div class="stat-sub">学习参考门槛 ≥{{ summary.learn_weekly_min }}/周</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">近 30 天电话转化</div>
        <div class="stat-value">{{ fmtInt(summary.account_conv_30d) }}</div>
        <div class="stat-sub">电话按钮点击（Detail2）口径</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">学习状态分布</div>
        <div class="status-dist">
          <span v-for="(n, label) in summary.status_counts" :key="label" class="dist-pill">
            {{ label }} {{ n }}
          </span>
          <span v-if="!Object.keys(summary.status_counts || {}).length" class="dim">—</span>
        </div>
      </div>
    </div>

    <!-- 策略卡列表 -->
    <div v-if="data && data.total > 0" class="pkg-list">
      <div v-for="p in data.packages" :key="p.package_id" class="pkg-card">
        <div class="pkg-head">
          <div class="pkg-name">
            {{ p.package_name || ('策略 #' + p.package_id) }}
            <span class="status-pill" :class="STATUS_CLS[p.package_status] || 'gray'">{{ p.package_status_label }}</span>
          </div>
          <div class="pkg-bid">
            <span class="bid-label">{{ p.ocpc_bid_type_label }}</span>
            <span class="bid-value">{{ fmtMoney(p.ocpc_bid) }}</span>
            <span class="bid-unit">/ 转化</span>
          </div>
        </div>

        <div class="pkg-body">
          <!-- 转化口径：决定百度算法看不看得到（尤其电话） -->
          <div class="pkg-field">
            <div class="field-label">转化口径
              <el-tooltip placement="top" content="OCPC 算法只能优化它能看到的转化。这里列出该策略统计的「数据来源 + 目标转化类型」。">
                <span class="dim">ⓘ</span>
              </el-tooltip>
            </div>
            <div class="field-body">
              <template v-if="p.dataflows.length">
                <div v-for="(df, i) in p.dataflows" :key="i" class="df-row">
                  <span class="df-source">{{ df.data_flow_label }}</span>
                  <span v-for="t in df.trans_types" :key="t.code" class="trans-pill" :class="{ phone: t.code === 2 || t.code === 30 }">
                    {{ t.label }}
                  </span>
                </div>
              </template>
              <span v-else class="dim">未配置转化口径</span>
              <div class="phone-flag" :class="p.covers_phone ? 'ok' : 'warn'">
                {{ p.covers_phone ? '✓ 已覆盖电话转化' : `⚠ 未覆盖电话转化，请核对${tenantName}的转化目标` }}
              </div>
            </div>
          </div>

          <!-- 绑定计划 -->
          <div class="pkg-field">
            <div class="field-label">绑定计划</div>
            <div class="field-body">
              <template v-if="p.bound_campaigns.length">
                <span v-for="c in p.bound_campaigns" :key="c.campaign_id" class="camp-pill">
                  {{ c.campaign_name || ('#' + c.campaign_id) }}
                </span>
              </template>
              <span v-else class="dim">未绑定计划</span>
            </div>
          </div>

          <!-- 包级转化量（绑定计划合计，判断这个包喂没喂饱） -->
          <div class="pkg-field">
            <div class="field-label">绑定计划转化量</div>
            <div class="field-body">
              <span class="conv-num">近 7 天 <b>{{ fmtInt(p.conv_7d) }}</b></span>
              <span class="conv-num">近 30 天 <b>{{ fmtInt(p.conv_30d) }}</b></span>
              <span v-if="p.conv_7d == null" class="dim">（未绑定计划，无法归集）</span>
            </div>
          </div>

          <div v-if="p.assist_trans_types.length" class="pkg-field">
            <div class="field-label">深度转化</div>
            <div class="field-body">
              <span v-for="(t, i) in p.assist_trans_types" :key="i" class="trans-pill">{{ t }}</span>
              <span v-if="p.ocpc_deep_cpa != null" class="conv-num">深度出价 {{ fmtMoney(p.ocpc_deep_cpa) }}</span>
            </div>
          </div>
        </div>
        <div class="pkg-foot">同步于 {{ formatUtcTimestamp(p.synced_at) }}</div>
      </div>
    </div>

    <!-- 空状态：当前客户未开 OCPC 的解释 -->
    <div v-else-if="data && !loading" class="empty-panel">
      <div class="empty-title">当前账户没有任何 oCPC 出价策略</div>
      <div class="empty-text">
        {{ tenantName }}目前以关键词 CPC 出价投放，未启用 oCPC（目标转化出价）。<br />
        oCPC 让你设「目标转化成本」、由百度算法自动出价，但它<b>靠转化数据喂模型</b>：
        转化量太少模型学不动，效果可能不如手动调价。<br />
        是否值得开，先看上方近 7/30 天的电话转化量够不够。开通与调价能力在后续版本提供。
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }

.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.stat-label { font-size: 11px; color: var(--sem-text-sub); }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }
.status-dist { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.dist-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #f3f4f6; color: var(--sem-text-sub); }

.pkg-list { display: flex; flex-direction: column; gap: 12px; }
.pkg-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.pkg-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid #f3f4f6; background: #fafbfc;
}
.pkg-name { font-size: 15px; font-weight: 600; color: var(--sem-text); }
.status-pill { font-size: 11px; padding: 1px 9px; border-radius: 10px; font-weight: 600; margin-left: 10px; }
.status-pill.green { background: #e5f4ed; color: var(--sem-success); }
.status-pill.amber { background: #fef1e1; color: #ba7517; }
.status-pill.red { background: #fdeaea; color: var(--sem-danger); }
.status-pill.gray { background: #f3f4f6; color: var(--sem-text-sub); }
.pkg-bid { text-align: right; }
.bid-label { font-size: 11px; color: var(--sem-text-sub); margin-right: 8px; }
.bid-value { font-size: 20px; font-weight: 700; color: var(--sem-primary); font-variant-numeric: tabular-nums; }
.bid-unit { font-size: 11px; color: #9ca3af; margin-left: 3px; }

.pkg-body { padding: 6px 18px 12px; }
.pkg-field { display: flex; gap: 14px; padding: 10px 0; border-bottom: 1px dashed #f3f4f6; }
.pkg-field:last-child { border-bottom: none; }
.field-label { font-size: 12px; color: var(--sem-text-sub); width: 110px; flex-shrink: 0; padding-top: 2px; }
.field-body { flex: 1; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.df-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; width: 100%; }
.df-source { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #eff4fb; color: var(--sem-primary); font-weight: 500; }
.trans-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #f3f4f6; color: var(--sem-text-sub); }
.trans-pill.phone { background: #e5f4ed; color: var(--sem-success); font-weight: 600; }
.phone-flag { width: 100%; font-size: 11px; margin-top: 2px; }
.phone-flag.ok { color: var(--sem-success); }
.phone-flag.warn { color: #ba7517; }
.camp-pill { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #f3f4f6; color: var(--sem-text); }
.conv-num { font-size: 12px; color: var(--sem-text); font-variant-numeric: tabular-nums; }
.conv-num b { color: var(--sem-text); }
.pkg-foot { padding: 8px 18px; font-size: 11px; color: #9ca3af; background: #fafbfc; border-top: 1px solid #f3f4f6; }
.dim { color: #9ca3af; font-size: 12px; }

.empty-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 36px; text-align: center; }
.empty-title { font-size: 15px; font-weight: 600; color: var(--sem-text); margin-bottom: 12px; }
.empty-text { font-size: 13px; color: var(--sem-text-sub); line-height: 1.9; }
</style>
