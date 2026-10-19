<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createInboxState } from './distributionInboxState.js'

// Deliberately not registered in the live router until shared storage is cleared.
// Both shells can mount this identity-level view with explicit session adapters.
const props = defineProps({
  api: { type: Object, required: true }, identity: { type: String, required: true },
  targets: { type: Array, default: () => [] }, // authorized {tenantId,name,modules,scopes?}
})
const revision = ref(0)
const model = createInboxState(props.api, () => { revision.value += 1 })
const state = computed(() => { revision.value; return { ...model.state } })
const targetId = ref({})
const moduleId = ref({})
const scopeId = ref({})
const results = { success: '操作人报告成功 · 页面尚未核验', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }
function targetFor(row) { return props.targets.find(t => t.tenantId === Number(targetId.value[row.id])) }
function targetChanged(row) {
  const target = targetFor(row)
  moduleId.value[row.id] = target?.modules?.length === 1 ? target.modules[0] : ''
  scopeId.value[row.id] = ''
}
function label(row) {
  const target = targetFor(row)
  const module = moduleId.value[row.id]
  if (!target || !target.modules.includes(module)) return
  return model.label(row, { tenantId: target.tenantId, module, scopeId: Number(scopeId.value[row.id]) || null })
}
function reset() {
  model.clear(); targetId.value = {}; moduleId.value = {}; scopeId.value = {}
  if (props.identity) void model.refresh()
}
watch(() => props.identity, reset, { immediate: true })
watch(() => props.targets, () => { targetId.value = {}; moduleId.value = {}; scopeId.value = {} }, { deep: true })
onBeforeUnmount(model.clear)
</script>

<template>
  <main class="inbox">
    <h1>多号通回传</h1>
    <p v-if="state.error" role="alert">{{ state.error }}</p>
    <section aria-labelledby="pair-title">
      <h2 id="pair-title">电脑配对</h2>
      <p>不用先选客户或平台。此码需要多号通0.3.7，旧版请先升级。</p>
      <button :disabled="state.busy" @click="model.pair">生成配对码</button>
      <p v-if="state.pairing"><code>{{ state.pairing.pairingCode }}</code> · 10分钟内一次有效</p>
    </section>
    <section aria-labelledby="receipts-title">
      <h2 id="receipts-title">待标客户（{{ state.count }}）</h2>
      <p v-if="!targets.length">暂无可标注的客户，请联系超管授权</p>
      <p v-if="!state.items.length">暂无待标客户记录</p>
      <article v-for="row in state.items" :key="row.id">
        <p>{{ row.platform }} · {{ row.title || '未提供标题' }}</p>
        <a v-if="row.publicUrl" :href="row.publicUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.publicUrl }}</a>
        <p>发布账号：{{ row.reportedAccount || '未提供' }} · {{ results[row.result] || '结果未知' }}</p>
        <p>操作人报告时间：{{ row.occurredAt }} · 收到时间：{{ row.receivedAt }}</p>
        <p v-if="row.duplicate">自己的收件箱中有相同链接，请核对</p>
        <p v-if="row.assignment?.hidden">客户归属不可查看</p>
        <template v-else-if="row.assignment">
          <p>外部回传 · 已标客户；改标请先撤销，再选择新客户或模块。</p>
          <button :disabled="state.busy" @click="model.unlabel(row)">撤销标注</button>
        </template>
        <template v-else>
          <label>客户 <select v-model="targetId[row.id]" :disabled="state.busy" @change="targetChanged(row)">
            <option value="">请选择客户</option>
            <option v-for="target in targets" :key="target.tenantId" :value="target.tenantId">{{ target.name }}</option>
          </select></label>
          <label v-if="targetFor(row)?.modules.length > 1">模块
            <select v-model="moduleId[row.id]" :disabled="state.busy"><option value="">请选择 SEO/GEO</option><option v-for="module in targetFor(row).modules" :key="module" :value="module">{{ module.toUpperCase() }}</option></select>
          </label>
          <details><summary>网站或项目（可稍后补）</summary>
            <select v-model="scopeId[row.id]" :disabled="state.busy"><option value="">范围待补</option>
              <option v-for="scope in (targetFor(row)?.scopes || []).filter(s => s.module === moduleId[row.id])" :key="scope.id" :value="scope.id">{{ scope.name }}</option>
            </select>
            <p>未关联稿件，不核验正文，不计入稿件验收。</p>
          </details>
          <button :disabled="state.busy || !targetId[row.id] || !moduleId[row.id]" @click="label(row)">标注客户</button>
        </template>
      </article>
    </section>
    <section aria-labelledby="devices-title">
      <h2 id="devices-title">设备列表</h2>
      <p>停用后停止接收后续回传，已收到的记录保留。本地移除不等于服务端停用。</p>
      <p v-for="device in state.devices" :key="device.id">{{ device.label }} · {{ device.state }}
        <button :disabled="state.busy || ['revoked', 'expired'].includes(device.state)" @click="model.revoke(device)">停用</button>
      </p>
    </section>
  </main>
</template>

<style scoped>
.inbox { max-width: 1000px; margin: auto; padding: 24px; color: #172b45; }
section { margin: 24px 0; padding: 20px; border: 1px solid #dbe3ef; border-radius: 12px; background: #fff; }
article { padding: 16px 0; border-top: 1px solid #dbe3ef; overflow-wrap: anywhere; }
button, select { padding: 8px 12px; margin: 4px 12px 4px 0; }
code { font-size: 1.1em; overflow-wrap: anywhere; }
[role=alert] { color: #a12828; }
</style>
