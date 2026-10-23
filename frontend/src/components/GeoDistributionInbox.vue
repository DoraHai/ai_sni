<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { createInboxState } from './geoDistributionInboxState.js'

// Both shells use identity APIs, with explicit business sessions only on writes.
const props = defineProps({
  api: { type: Object, required: true }, identity: { type: String, required: true },
  targets: { type: Array, default: () => [] }, // authorized {tenantId,name,modules,scopes?}
  owners: { type: Array, default: () => [] }, // only personnel administrators receive these
  focusReceiptId: { type: String, default: '' },
})
const emit = defineEmits(['labelled', 'refresh-targets'])
const revision = ref(0)
const model = createInboxState(props.api, () => { revision.value += 1 })
const state = computed(() => { revision.value; return { ...model.state } })
const visibleItems = computed(() => state.value.focused ? [state.value.focused, ...state.value.items.filter(r => r.id !== state.value.focused.id)] : state.value.items)
const targetId = ref({})
const moduleId = ref({})
const scopeId = ref({})
const articleId = ref({})
const publishedAccount = ref({})
const results = { success: '操作人报告成功 · 页面尚未核验', failed: '失败', risk_control: '平台风控', verification_required: '需验证', pending_review: '审核中', unknown: '结果未知' }
function safeLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : null } catch { return null }
}
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
function scopesFor(row) {
  const target = row.assignment && !row.assignment.hidden ? props.targets.find(t => t.tenantId === row.assignment.tenantId) : targetFor(row)
  return (target?.scopes || []).filter(s => s.module === (row.assignment?.module || moduleId.value[row.id]))
}
function assignmentText(row) {
  const assignment = row.assignment
  if (!assignment || assignment.hidden) return ''
  const target = props.targets.find(t => Number(t.tenantId) === Number(assignment.tenantId))
  const kind = assignment.module === 'geo' ? '项目' : '网站'
  const scope = (target?.scopes || []).find(s => s.module === assignment.module && Number(s.id) === Number(assignment.scopeId))
  const scopeName = assignment.scopeId ? scope?.name || `${kind} #${assignment.scopeId}` : `${kind}待补`
  return `${target?.name || `客户 #${assignment.tenantId}`} · ${assignment.module.toUpperCase()} · ${scopeName}`
}
function articlesFor(row) { return scopesFor(row).find(s => s.id === Number(scopeId.value[row.id] ?? row.assignment?.scopeId))?.articles || [] }
async function label(row) {
  const target = targetFor(row)
  const module = moduleId.value[row.id]
  if (!target || !target.modules.includes(module)) return
  const result = await model.label(row, { tenantId: target.tenantId, module, scopeId: Number(scopeId.value[row.id]) || null,
    ...(articleId.value[row.id] ? { article: articlesFor(row).find(a => a.id === Number(articleId.value[row.id])) } : {}),
    ...(Object.hasOwn(publishedAccount.value, row.id) ? { publishedAccount: publishedAccount.value[row.id] } : {}) })
  if (result) emit('labelled', result)
}
async function update(row) {
  const assignment = row.assignment
  const selectedArticle = articleId.value[row.id] === undefined ? (assignment.articleId ? { id: assignment.articleId, version: assignment.articleVersion, digest: assignment.articleDigest } : null)
    : articlesFor(row).find(a => a.id === Number(articleId.value[row.id]))
  const result = await model.label(row, { tenantId: assignment.tenantId, module: assignment.module,
    scopeId: Number(scopeId.value[row.id] ?? assignment.scopeId) || null, article: selectedArticle,
    publishedAccount: publishedAccount.value[row.id] ?? assignment.publishedAccount })
  if (result) emit('labelled', result)
}
async function reset() {
  model.clear(); targetId.value = {}; moduleId.value = {}; scopeId.value = {}; articleId.value = {}; publishedAccount.value = {}
  const identity = props.identity, focus = props.focusReceiptId
  if (props.identity) {
    await model.refresh()
    if (identity === props.identity && focus === props.focusReceiptId && focus) await model.focus(focus)
  }
}
watch([() => props.identity, () => props.focusReceiptId], reset, { immediate: true })
watch(() => state.value.focused?.id, async id => {
  if (!id) return
  await nextTick()
  const row = document.getElementById(`receipt-${id}`)
  row?.querySelector('details')?.setAttribute('open', '')
  row?.scrollIntoView({ block: 'center' }); row?.focus()
})
watch(() => props.targets, () => { targetId.value = {}; moduleId.value = {}; scopeId.value = {}; articleId.value = {}; publishedAccount.value = {} }, { deep: true })
onBeforeUnmount(model.clear)
</script>

<template>
  <main class="inbox">
    <h1>多号通回传</h1>
    <p v-if="state.error" role="alert">{{ state.error }}</p>
    <p v-if="state.conflict" role="alert">版本或归属已变化，请重新读取候选后核对选择。<button type="button" @click="emit('refresh-targets')">重读候选稿件</button></p>
    <section aria-labelledby="pair-title">
      <h2 id="pair-title">电脑配对</h2>
      <p>不用先选客户或平台。此码需要多号通0.3.7，旧版请先升级。</p>
      <button :disabled="state.busy" @click="model.pair">生成配对码</button>
      <p v-if="state.pairing"><code>{{ state.pairing.pairingCode }}</code> · 10分钟内一次有效</p>
    </section>
    <section aria-labelledby="receipts-title">
      <h2 id="receipts-title">待标客户（{{ state.count }}）</h2>
      <label v-if="owners.length">所有者 <select :value="state.ownerUserId || ''" :disabled="state.busy" @change="model.owner($event.target.value)"><option value="">我的收件箱</option><option v-for="owner in owners" :key="owner.id" :value="owner.id">{{ owner.displayName }}{{ owner.active ? '' : '（已停用）' }}</option></select></label>
      <label>查看 <select :value="state.filter" :disabled="state.busy" @change="model.show($event.target.value)"><option value="pending">待标客户</option><option value="active">已标客户（可改标/撤销）</option><option value="archived">已归档</option></select></label>
      <p v-if="!targets.length">暂无可标注的客户，请联系超管授权</p>
      <p v-if="!state.items.length">暂无待标客户记录</p>
      <p v-if="state.focused">已定位到指定回传，以下标记记录独立于列表分页。</p>
      <article v-for="row in visibleItems" :key="row.id" :id="`receipt-${row.id}`" tabindex="-1" :class="{ 'focused-receipt': row.id === state.focused?.id }">
        <strong v-if="row.id === state.focused?.id">当前定位记录</strong>
        <p>{{ row.platform }} · {{ row.title || '未提供标题' }}</p>
        <a v-if="safeLink(row.publicUrl)" :href="safeLink(row.publicUrl)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ row.publicUrl }}</a>
        <p>发布账号：{{ row.reportedAccount || '未提供' }} · {{ results[row.result] || '结果未知' }}</p>
        <p>操作人报告时间：{{ row.occurredAt }} · 收到时间：{{ row.receivedAt }}</p>
        <p v-if="row.duplicate">自己的收件箱中有相同链接，请核对</p>
        <p v-if="row.assignment?.hidden">客户归属不可查看</p>
        <template v-else-if="row.assignment">
          <p class="assignment-target" :class="{ 'scope-missing': !row.assignment.scopeId }">{{ assignmentText(row) }}</p>
          <p>外部回传 · 已标客户；改标请先撤销，再选择新客户或模块。</p>
          <details><summary>修改网站或项目、关联稿件、发布账号</summary>
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
      <button :disabled="state.busy || state.offset === 0" @click="model.page(Math.max(0, state.offset - 50))">上一页</button>
      <button :disabled="state.busy || state.offset + 50 >= state.count" @click="model.page(state.offset + 50)">下一页</button>
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
.assignment-target { font-weight: 600; }
.scope-missing { color: #9a3412; background: #fff7ed; padding: 8px 12px; border-radius: 6px; }
.focused-receipt { outline: 2px solid #818cf8; outline-offset: 6px; border-radius: 6px; }
button, select { padding: 8px 12px; margin: 4px 12px 4px 0; }
code { font-size: 1.1em; overflow-wrap: anywhere; }
[role=alert] { color: #a12828; }
</style>
