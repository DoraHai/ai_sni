<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { fetchPatrolSelfService, putPatrolSelfService } from '../api/geoContent'
import { beijingTime, blockedLabel, createSelfServiceController, PATROL_PLATFORMS, PLATFORM_STATUS, patrolStatus, RUN_STATUS, toggleAllowed } from '../utils/geoAutopatrol'
import GeoPatrolHistory from './GeoPatrolHistory.vue'
const props = defineProps({ tenantId: Number, collecting: Boolean })
const emit = defineEmits(['manual'])
const state = reactive({ data: null, loading: false, busy: false, error: '' })
const historyOpen = ref(false)
const controller = createSelfServiceController({ state, read: fetchPatrolSelfService, write: putPatrolSelfService })
const data = computed(() => state.data)
const platforms = computed(() => PATROL_PLATFORMS.map(([key, label]) => ({ key, label, status: data.value?.platforms?.find(p => p.engine_key === key)?.status })))
const manualAllowed = computed(() => data.value && !state.loading && !props.collecting && data.value.manual_quota?.used < data.value.manual_quota?.limit)
watch(() => props.tenantId, id => { historyOpen.value = false; controller.setTenant(id) }, { immediate: true, flush: 'sync' })
watch(() => props.collecting, (now, previous) => { if (previous && !now) controller.load() })
onBeforeUnmount(controller.dispose)
</script>
<template>
  <section class="gd-card patrol-card" data-testid="advisor-patrol-card" v-loading="state.loading">
    <div class="gd-hd"><h3>AI 可见度检测</h3><button class="gd-btn" :disabled="state.busy || state.loading" @click="controller.load">刷新检测状态</button></div>
    <div class="gd-bd">
      <el-alert v-if="state.error" :title="state.error" type="warning" :closable="false" class="space" />
      <div class="patrol-line">
        <button class="gd-btn primary" :disabled="!manualAllowed" @click="emit('manual')">{{ collecting ? '检测中…' : '手动检测一次' }}</button>
        <b>今日 {{ data?.manual_quota?.used ?? '—' }}/{{ data?.manual_quota?.limit ?? '—' }}</b><span>手动次数由该客户所有顾问共用</span>
      </div>
      <template v-if="data">
        <div class="patrol-line toggle-line"><b>每天自动检测一次</b><el-switch :model-value="data.enabled" :disabled="state.busy || state.loading || !toggleAllowed(data)" :loading="state.busy" aria-label="每天自动检测一次" @change="controller.toggle" /><span class="gd-badge" :class="data.enabled ? 'green' : 'amber'">{{ patrolStatus(data) }}</span></div>
        <el-alert v-if="data.admin_locked" type="warning" :closable="false" :title="`管理锁：${data.lock_reason || '管理员已锁定'}（最近变更：${beijingTime(data.last_changed_at)} 北京时间）`" class="space" />
        <el-alert v-else-if="data.blocked_reason" :title="blockedLabel(data.blocked_reason)" type="warning" :closable="false" class="space" />
        <p>覆盖：负责人负责的 {{ data.coverage?.project_ids?.length ?? '—' }} 个项目 / {{ data.coverage?.prompt_count ?? '—' }} 个有效问题（最多 {{ data.coverage?.max_prompts ?? '—' }} 题）；其他顾问负责项目不在此轮范围内。</p>
        <div class="platform-grid"><div v-for="platform in platforms" :key="platform.key" :class="['platform', { warning: platform.status !== 'available' }]"><b>{{ platform.label }}</b><span>{{ PLATFORM_STATUS[platform.status] || '状态未知' }}</span></div></div>
        <dl class="patrol-meta">
          <div><dt>开启人 / 时间</dt><dd>{{ data.opened_by?.display_name || '—' }} / {{ beijingTime(data.opened_at) }}</dd></div>
          <div><dt>自动监测负责人</dt><dd>{{ data.owner?.display_name || '—' }}</dd></div>
          <div><dt>最近变更</dt><dd>{{ data.last_changed_by?.display_name || '—' }} / {{ beijingTime(data.last_changed_at) }}</dd></div>
          <div><dt>下次预计（北京时间）</dt><dd>{{ data.enabled ? beijingTime(data.next_run_estimate) : '—' }}</dd></div>
          <div><dt>上次自动结果</dt><dd v-if="data.last_run">{{ beijingTime(data.last_run.finished_at || data.last_run.created_at) }} · {{ RUN_STATUS[data.last_run.status] || '状态未知' }}（成功 {{ data.last_run.success }} / 失败 {{ data.last_run.failed }} / 跳过 {{ data.last_run.skipped }} 格）</dd><dd v-else>尚无自动检测</dd></div>
        </dl>
        <el-alert v-if="!data.enabled && data.in_flight" title="已关闭，旧轮仍在收尾；已经发出的平台请求无法撤回。" type="info" :closable="false" class="space" />
        <div class="patrol-line"><router-link v-if="data.last_run?.id" class="gd-btn" :to="{ path: '/geo/visibility/snapshots', query: { patrol_run_id: data.last_run.id } }">查看本轮明细</router-link><button class="gd-btn" @click="historyOpen = true">查看开关历史</button></div>
      </template>
      <p class="patrol-note">自动每日最多安排一轮，不占手动次数；未配置的平台会跳过。受授权、平台可用性、复测预约和平台总额度限制，预计时间可能延后。API 采样不等于 App 联网排名。时间均为北京时间。</p>
    </div>
    <GeoPatrolHistory v-model:open="historyOpen" :tenant-id="tenantId" />
  </section>
</template>
<style scoped>
.patrol-card { margin-bottom: 12px; }
.gd-btn:disabled { opacity: .5; cursor: not-allowed; }
.patrol-line { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.toggle-line { margin:20px 0 14px; }
.space { margin-bottom:12px; }
.platform-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.platform { padding:12px; background:#f0f8f5; border:1px solid #d6eade; border-radius:8px; display:flex; flex-direction:column; gap:6px; }
.platform.warning { background:#fff8eb; border-color:#f3dfb3; }
.platform span,.patrol-note,.patrol-line>span,dt { color:#67758a; font-size:12px; }
.patrol-meta { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:18px 0; }
dd { margin:5px 0 0; overflow-wrap:anywhere; }
.patrol-note { margin:16px 0 0; line-height:1.7; }
@media(max-width:750px) { .platform-grid,.patrol-meta { grid-template-columns:1fr; } }
</style>
