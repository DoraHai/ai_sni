<script setup>
import { beijingTime, publicationPlatform, reportedResult, safePublicationUrl } from '../utils/articlePublicationGroups.js'
const props = defineProps({ state: { type: Object, required: true }, scopeSelected: Boolean })
const emit = defineEmits(['refresh', 'more', 'previous', 'filter', 'link'])
function filter(key, value) { emit('filter', { month: props.state.month, source: props.state.source, [key]: value || null }) }
</script>
<template>
  <section class="publication-records-table" aria-label="统一发布记录">
    <div class="toolbar">
      <label>月份 <input aria-label="记录月份" type="month" :value="state.month || ''" @change="filter('month', $event.target.value)" /></label>
      <label>来源 <select aria-label="记录来源" :value="state.source" @change="filter('source', $event.target.value)"><option value="all">全部</option><option value="native">系统发布</option><option value="external_report">多号通回传</option></select></label>
      <button :disabled="state.busy || !scopeSelected" @click="emit('refresh')">{{ state.busy ? '读取中…' : '刷新记录' }}</button>
    </div>
    <p v-if="!scopeSelected" class="note">请先选择网站，再查看该网站的发布记录。</p>
    <p class="note">没选网站的回传不会出现在这里，请到多号通回传收件箱补选网站。回传不计入原生指标或稿件验收。</p>
    <p v-if="state.error" class="error" role="alert">读取不完整：{{ state.error }}。请刷新重试。</p>
    <p v-if="state.busy" role="status">正在读取当前范围记录…</p>
    <nav class="pagination" aria-label="发布记录分页">
      <button :disabled="state.busy || state.page <= 1" @click="emit('previous')">上一页</button>
      <span>第 {{ state.page }} / {{ Math.max(1, Math.ceil((state.total || 0) / 20)) }} 页 · 共 {{ state.total ?? '—' }} 条 · 每页 20 条 · 最新在前</span>
      <button :disabled="state.busy || !state.more" @click="emit('more')">下一页</button>
    </nav>
    <div class="table-scroll">
      <table><thead><tr><th>文章</th><th>平台</th><th>连接</th><th>发布链接</th><th>发布依据</th><th>时间（北京时间）</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in state.items" :key="item.key" :data-record-key="item.key">
          <td data-label="文章"><div>{{ item.invalid ? '关联目标需重新核对' : item.title || '未提供标题' }}</div></td>
          <td data-label="平台"><div>{{ publicationPlatform(item.channel) }}</div></td>
          <td data-label="连接"><div>{{ item.account || (item.source === 'native' && item.publish_mode === 'manual' ? '人工登记' : '未记录账号') }}</div></td>
          <td data-label="发布链接"><div><a v-if="safePublicationUrl(item.url)" :href="safePublicationUrl(item.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ item.url }}</a><span v-else>链接未记录或不可打开</span></div></td>
          <td data-label="发布依据"><div><template v-if="item.source === 'native'">系统发布<small><slot name="native-evidence" :item="item" /></small><span v-if="item.also_reported" class="tag">也有多号通回传</span></template><template v-else><span class="tag">多号通回传</span><small>{{ reportedResult(item.status) }} · 正文暂不可核验</small></template></div></td>
          <td data-label="时间（北京时间）" class="time"><div>{{ beijingTime(item.event_at) }}</div></td>
          <td data-label="操作"><div><slot v-if="item.source === 'native'" name="native-actions" :item="item" /><button v-else-if="item.can_link" @click="emit('link', item)">去关联稿件</button><span v-else>—</span></div></td>
        </tr><tr v-if="!state.items.length && !state.busy && !state.error"><td colspan="7" class="empty">当前筛选暂无发布记录</td></tr></tbody>
      </table>
    </div>
  </section>
</template>
<style scoped>
.publication-records-table{color:#23354d;overflow-wrap:anywhere}.toolbar,.pagination{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:14px 0}.toolbar label{display:flex;align-items:center;gap:8px}.toolbar button{margin-left:auto}.pagination span{flex:1;font-size:13px;color:#68778c}button,select,input{background:#fff;border:1px solid #cdd8e5;border-radius:6px;padding:8px 10px;font:inherit;color:#234569}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #82b5ee;outline-offset:2px}.note{color:#68778c;font-size:13px;line-height:1.7}.error{color:#a83232;background:#fff5f5;padding:12px;border-radius:6px}.table-scroll{width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:13px}th,td{text-align:left;padding:14px 10px;border-bottom:1px solid #e3eaf2;vertical-align:top;line-height:1.6}th{background:#f5f8fc;color:#53657e}th:nth-child(1){width:19%}th:nth-child(2){width:8%}th:nth-child(3){width:10%}th:nth-child(4){width:20%}th:nth-child(5){width:16%}th:nth-child(6){width:14%}th:nth-child(7){width:13%}a{color:#2463a6}.tag{display:inline-block;background:#fff3df;color:#875c0a;border-radius:4px;padding:2px 6px;margin:2px 0}small{display:block;color:#68778c}.empty{text-align:center;color:#7b8797}.time{font-variant-numeric:tabular-nums}
@media(max-width:650px){.toolbar{align-items:stretch}.toolbar button{margin-left:0}.toolbar label{font-size:13px}.pagination span{min-width:140px}table,tbody,tr,td{display:block;width:auto}thead{display:none}tr{border:1px solid #dbe3ed;border-radius:8px;margin:12px 0;padding:8px}td{border:0;padding:7px 4px;display:grid;grid-template-columns:95px minmax(0,1fr);gap:8px}td:before{content:attr(data-label);font-weight:600;color:#65758b}td.empty{display:block}.table-scroll{overflow:visible}}
</style>
