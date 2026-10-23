<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { createInboxState } from './distributionInboxState.js'
import { beijingTime } from '../../utils/articlePublicationGroups.js'

// Both shells use identity APIs, with explicit business sessions only on writes.
const props = defineProps({
  api: { type: Object, required: true }, identity: { type: String, required: true },
  targets: { type: Array, default: () => [] }, // authorized {tenantId,name,modules,scopes?}
  owners: { type: Array, default: () => [] }, // only personnel administrators receive these
  receiptId: { type: String, default: '' },
})
const emit = defineEmits(['linked', 'refresh-targets'])
const revision = ref(0)
const model = createInboxState(props.api, () => { revision.value += 1 })
const state = computed(() => { revision.value; return { ...model.state } })
const filterLabel = computed(() => ({ pending: '待标客户', active: '已标客户', archived: '已归档' }[state.value.filter] || '回传记录'))
const deviceStates = { active: '使用中', revoked: '已停用', expired: '已过期' }
const rows = computed(() => state.value.focusedReceipt ? [state.value.focusedReceipt, ...state.value.items.filter(row => row.id !== state.value.focusedReceipt.id)] : state.value.items)
const inboxElement = ref(null)
watch(() => state.value.focusedReceipt?.id, async id => {
  if (!id) return
  await nextTick()
  const element = inboxElement.value?.querySelector(`[data-receipt-id="${id}"]`)
  element?.focus(); element?.scrollIntoView?.({ block: 'center' })
})
const targetId = ref({})
const moduleId = ref({})
const scopeId = ref({})
const articleId = ref({})
const publishedAccount = ref({})
const query = ref('')
const results = { success: '操作人报告成功 · 页面尚未核验', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }
function targetFor(row) { return props.targets.find(t => t.tenantId === Number(targetId.value[row.id])) }
function targetChanged(row) {
  const target = targetFor(row)
  moduleId.value[row.id] = target?.modules?.length === 1 ? target.modules[0] : ''
  moduleChanged(row)
}
function moduleChanged(row) {
  const scopes = scopesFor(row)
  scopeId.value[row.id] = scopes.length === 1 ? scopes[0].id : ''
  articleId.value[row.id] = ''
}
function assignmentLabel(row) {
  const assignment = row.assignment
  const target = props.targets.find(t => t.tenantId === assignment.tenantId)
  const scope = (target?.scopes || []).find(s => s.module === assignment.module && s.id === assignment.scopeId)
  const kind = assignment.module === 'geo' ? '项目' : '网站'
  return {
    customer: target?.name || `客户 #${assignment.tenantId}`,
    module: assignment.module.toUpperCase(),
    scope: assignment.scopeId == null ? `${kind}待补` : scope?.name || `${kind} #${assignment.scopeId}`,
    missingScope: assignment.scopeId == null,
  }
}
function scopesFor(row) {
  const target = row.assignment && !row.assignment.hidden ? props.targets.find(t => t.tenantId === row.assignment.tenantId) : targetFor(row)
  return (target?.scopes || []).filter(s => s.module === (row.assignment?.module || moduleId.value[row.id]))
}
function articlesFor(row) { return scopesFor(row).find(s => s.id === Number(scopeId.value[row.id] ?? row.assignment?.scopeId))?.articles || [] }
function label(row) {
  const target = targetFor(row)
  const module = moduleId.value[row.id]
  if (!target || !target.modules.includes(module)) return
  return model.label(row, { tenantId: target.tenantId, module, scopeId: Number(scopeId.value[row.id]) || null,
    ...(articleId.value[row.id] ? { article: articlesFor(row).find(a => a.id === Number(articleId.value[row.id])) } : {}),
    ...(Object.hasOwn(publishedAccount.value, row.id) ? { publishedAccount: publishedAccount.value[row.id] } : {}) })
}
async function update(row) {
  const assignment = row.assignment
  const selectedArticle = articleId.value[row.id] === undefined ? (assignment.articleId ? { id: assignment.articleId, version: assignment.articleVersion, digest: assignment.articleDigest } : null)
    : articlesFor(row).find(a => a.id === Number(articleId.value[row.id]))
  const saved = await model.label(row, { tenantId: assignment.tenantId, module: assignment.module,
    scopeId: Number(scopeId.value[row.id] ?? assignment.scopeId) || null, article: selectedArticle,
    publishedAccount: publishedAccount.value[row.id] ?? assignment.publishedAccount })
  if (saved?.assignment && !saved.assignment.hidden) emit('linked', saved)
}
async function reset() {
  model.clear(); targetId.value = {}; moduleId.value = {}; scopeId.value = {}; articleId.value = {}; publishedAccount.value = {}
  if (props.identity) {
    await model.refresh()
    if (props.receiptId) await model.focusReceipt(props.receiptId)
  }
}
watch(() => [props.identity, props.receiptId], reset, { immediate: true })
watch(() => props.targets, () => { targetId.value = {}; moduleId.value = {}; scopeId.value = {}; articleId.value = {}; publishedAccount.value = {} }, { deep: true })
onBeforeUnmount(model.clear)
</script>

<template>
  <main ref="inboxElement" class="inbox">
    <h1>多号通回传</h1>
    <p v-if="state.error" role="alert">{{ state.error }}</p>
    <p v-if="state.needsTargetRefresh">版本或归属已变化，请重新读取候选并核对后再保存。<button :disabled="state.busy" @click="emit('refresh-targets'); receiptId && model.focusReceipt(receiptId)">重新读取候选和回执</button></p>
    <section aria-labelledby="pair-title">
      <h2 id="pair-title">电脑配对</h2>
      <p>不用先选客户或平台。此码需要多号通0.3.7，旧版请先升级。</p>
      <button :disabled="state.busy" @click="model.pair">生成配对码</button>
      <p v-if="state.pairing"><code>{{ state.pairing.pairingCode }}</code> · 10分钟内一次有效</p>
      <button v-if="state.pairing" :disabled="state.busy" @click="model.cancelPairing">作废配对码</button>
    </section>
    <section aria-labelledby="receipts-title">
      <h2 id="receipts-title">{{ filterLabel }}（{{ state.count }}）</h2>
      <label v-if="owners.length">所有者 <select :value="state.ownerUserId || ''" :disabled="state.busy" @change="model.owner($event.target.value)"><option value="">我的收件箱</option><option v-for="owner in owners" :key="owner.id" :value="owner.id">{{ owner.displayName }}{{ owner.active ? '' : '（已停用）' }}</option></select></label>
      <label>查看 <select :value="state.filter" :disabled="state.busy" @change="model.show($event.target.value)"><option value="pending">待标客户</option><option value="active">已标客户（可改标/撤销）</option><option value="archived">已归档</option></select></label>
      <input v-model="query" maxlength="100" placeholder="搜索标题、平台、账号或链接" /><button :disabled="state.busy" @click="model.search(query)">搜索</button>
      <p v-if="!targets.length">暂无可标注的客户，请联系超管授权</p>
      <p v-if="!rows.length">暂无{{ filterLabel }}记录</p>
      <article v-for="row in rows" :key="row.id" :data-receipt-id="row.id" tabindex="-1" :class="{ focused: row.id === receiptId }">
        <p v-if="row.id === receiptId">从发布记录定位的回执，请核对后关联稿件。</p>
        <p>{{ row.platform }} · {{ row.title || '未提供标题' }}</p>
        <a v-if="row.publicUrl" :href="row.publicUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.publicUrl }}</a>
        <p>发布账号：{{ row.reportedAccount || '未提供' }} · {{ results[row.result] || '结果未知' }}</p>
        <p>操作人报告时间（北京时间）：{{ beijingTime(row.occurredAt) }} · 收到时间（北京时间）：{{ beijingTime(row.receivedAt) }}</p>
        <p v-if="row.duplicate">自己的收件箱中有相同链接，请核对</p>
        <p v-if="row.assignment?.hidden">客户归属不可查看</p>
        <template v-else-if="row.assignment">
          <p class="assignment-target">{{ assignmentLabel(row).customer }} · {{ assignmentLabel(row).module }} · <span :class="{ 'assignment-scope-missing': assignmentLabel(row).missingScope }">{{ assignmentLabel(row).scope }}</span></p>
          <p>外部回传 · 已标客户；改标请先撤销，再选择新客户或模块。</p>
          <details :open="row.id === receiptId"><summary>修改网站或项目、关联稿件、发布账号</summary>
            <select :value="scopeId[row.id] ?? row.assignment.scopeId ?? ''" :disabled="state.busy" @change="scopeId[row.id] = $event.target.value; articleId[row.id] = ''"><option value="">范围待补</option><option v-for="scope in scopesFor(row)" :key="scope.id" :value="scope.id">{{ scope.name }}</option></select>
            <p>{{ row.assignment.module === 'geo' ? '不选项目的话，这条回传不会出现在项目的发布记录里。' : '不选网站的话，这条回传不会出现在网站的发布记录里。' }}</p>
            <select :value="articleId[row.id] ?? row.assignment.articleId ?? ''" :disabled="state.busy" @change="articleId[row.id] = $event.target.value"><option value="">未关联稿件</option><option v-for="article in articlesFor(row)" :key="article.id" :value="article.id">{{ article.title }}</option></select>
            <input :value="publishedAccount[row.id] ?? row.assignment.publishedAccount ?? ''" maxlength="60" placeholder="发布账号（留空恢复上报值）" @input="publishedAccount[row.id] = $event.target.value" />
            <button :disabled="state.busy" @click="update(row)">保存标注修改</button>
          </details>
          <button :disabled="state.busy" @click="model.unlabel(row)">撤销标注</button>
        </template>
        <template v-else>
          <label>客户 <select v-model="targetId[row.id]" :disabled="state.busy" @change="targetChanged(row)">
            <option value="">请选择客户</option>
            <option v-for="target in targets" :key="target.tenantId" :value="target.tenantId">{{ target.name }}</option>
          </select></label>
          <label v-if="targetFor(row)?.modules.length > 1">模块
            <select v-model="moduleId[row.id]" :disabled="state.busy" @change="moduleChanged(row)"><option value="">请选择 SEO/GEO</option><option v-for="module in targetFor(row).modules" :key="module" :value="module">{{ module.toUpperCase() }}</option></select>
          </label>
          <details><summary>网站或项目（可稍后补）</summary>
            <select v-model="scopeId[row.id]" :disabled="state.busy" @change="articleId[row.id] = ''"><option value="">范围待补</option>
              <option v-for="scope in (targetFor(row)?.scopes || []).filter(s => s.module === moduleId[row.id])" :key="scope.id" :value="scope.id">{{ scope.name }}</option>
            </select>
            <p>{{ moduleId[row.id] === 'geo' ? '不选项目的话，这条回传不会出现在项目的发布记录里。' : '不选网站的话，这条回传不会出现在网站的发布记录里。' }}</p>
            <label>关联稿件 <select v-model="articleId[row.id]" :disabled="state.busy"><option value="">未关联稿件</option><option v-for="article in articlesFor(row)" :key="article.id" :value="article.id">{{ article.title }}</option></select></label>
            <input v-model="publishedAccount[row.id]" maxlength="60" placeholder="发布账号（可留空）" />
            <p>未关联稿件，不核验正文，不计入稿件验收。</p>
          </details>
          <button :disabled="state.busy || !targetId[row.id] || !moduleId[row.id]" @click="label(row)">标注客户</button>
          <button :disabled="state.busy" @click="model.archive(row)">归档</button>
          <button :disabled="state.busy" @click="model.remove(row)">清理内容</button>
        </template>
      </article>
      <p><button :disabled="state.busy || state.offset === 0" @click="model.page(state.offset - 50)">上一页</button><span>{{ state.total }} 条 · 第 {{ Math.floor(state.offset / 50) + 1 }} 页</span><button :disabled="state.busy || state.offset + 50 >= state.total" @click="model.page(state.offset + 50)">下一页</button></p>
    </section>
    <section aria-labelledby="devices-title">
      <h2 id="devices-title">设备列表</h2>
      <p>停用后停止接收后续回传，已收到的记录保留。本地移除不等于服务端停用。</p>
      <p v-for="device in state.devices" :key="device.id">{{ device.label }} · {{ deviceStates[device.state] || '未知状态' }}
        <button :disabled="state.busy || ['revoked', 'expired'].includes(device.state)" @click="model.revoke(device)">停用</button>
      </p>
    </section>
  </main>
</template>

<style scoped>
.inbox { max-width: 1000px; margin: auto; padding: 24px; color: #172b45; }
section { margin: 24px 0; padding: 20px; border: 1px solid #dbe3ef; border-radius: 12px; background: #fff; }
article { padding: 16px 0; border-top: 1px solid #dbe3ef; overflow-wrap: anywhere; }
.focused { background: #f0f6ff; padding: 16px; border: 2px solid #7ca5db; border-radius: 8px; }
.assignment-scope-missing { color: #9a3412; background: #fff7ed; padding: 2px 6px; border-radius: 4px; font-weight: 600; }
button, select { padding: 8px 12px; margin: 4px 12px 4px 0; }
code { font-size: 1.1em; overflow-wrap: anywhere; }
[role=alert] { color: #a12828; }
</style>
