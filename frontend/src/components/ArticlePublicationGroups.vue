<script setup>
import { computed, ref } from 'vue'
import { beijingTime, groupKey, reportedResult, safePublicationUrl } from '../utils/articlePublicationGroups.js'
const props = defineProps({ state: { type: Object, required: true }, scopeSelected: Boolean })
const emit = defineEmits(['refresh', 'more', 'details', 'link'])
const source = ref('all')
const groups = computed(() => props.state.buckets.linked.items.filter(row => source.value === 'all' || (source.value === 'native' ? row.native_count : row.external_count) > 0))
const detail = row => props.state.details[groupKey(row)] || { items: [] }
const visible = row => detail(row).items.filter(item => source.value === 'all' || item.source === source.value)
const external = row => row.source === 'external_report'
function toggle(event, row) { if (event.target.open) emit('details', row) }
</script>
<template>
  <section class="publication-groups" aria-label="按文章查看发布记录">
    <header class="toolbar"><div><h2>按文章查看发布记录</h2><p>原生记录与外部回传分别保留；来源条数与文章篇数不可相加。</p></div><button :disabled="state.busy || !scopeSelected" @click="emit('refresh')">{{ state.busy ? '读取中…' : '刷新记录' }}</button></header>
    <p v-if="!scopeSelected" class="scope-prompt">请先选择网站，再查看该网站的发布记录。</p>
    <p class="note">没选网站的回传不会出现在这里，请到多号通回传收件箱补选网站。</p>
    <p v-if="state.error" class="error" role="alert">读取不完整：{{ state.error }}。请刷新重试；原生记录仍可从下方独立入口查看。</p>
    <p v-if="state.busy" role="status">正在读取当前范围记录…</p>
    <template v-if="state.counts">
      <div class="counts" aria-label="全网站范围统计"><span>原生已发布 <b>{{ state.counts.native }}</b> 条</span><span>外部回传 <b>{{ state.counts.external }}</b> 条</span><span>本范围有记录文章 <b>{{ state.counts.articles }}</b> 篇</span></div>
      <div class="toolbar compact"><label>来源 <select v-model="source"><option value="all">全部来源</option><option value="native">系统原生</option><option value="external_report">外部回传</option></select></label><span>已加载 {{ state.buckets.linked.items.length }} 篇 / 全范围 {{ state.counts.articles }} 篇；当前筛选可见 {{ groups.length }} 篇</span></div>
      <p v-if="!groups.length" class="empty">当前筛选暂无文章记录</p>
      <details v-for="row in groups" :key="groupKey(row)" :data-group-id="row.group_article_id" class="article-group" @toggle="toggle($event, row)">
        <summary><span class="article-title">#{{ row.group_article_id }} {{ row.title || '未提供标题' }}</span><span class="source-counts">系统 {{ row.native_count }} 条 / 外部回传 {{ row.external_count }} 条</span></summary>
        <div class="article-details">
          <p v-if="detail(row).busy" role="status">正在读取明细…</p>
          <p v-if="detail(row).error" role="alert" class="error">读取不完整：{{ detail(row).error }} <button @click="emit('details', row, !!detail(row).loaded)">重试</button></p>
          <p v-if="detail(row).loaded && !visible(row).length" class="empty">当前已加载明细中无此来源，可继续加载。</p>
          <article v-for="item in visible(row)" :key="item.key" class="publication-detail">
            <div class="detail-heading"><span class="tag" :class="{ external: external(item) }">{{ external(item) ? '外部回传' : '系统' }}</span><b>{{ item.channel || '平台未记录' }}</b><span>关联 v{{ item.article_version_no ?? '未记录' }}<template v-if="item.article_version_no && item.article_version_no !== row.current_version_no">；当前 v{{ row.current_version_no }}（历史版本）</template></span></div>
            <a v-if="safePublicationUrl(item.url)" :href="safePublicationUrl(item.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ item.url }}</a><span v-else>公开链接未记录或不可打开</span>
            <p v-if="external(item)" class="report-status">{{ reportedResult(item.status) }} · 正文暂不可核验</p><p v-else>原生状态：{{ item.status === 'published' ? '已发布' : item.status }} · 核验证据另列</p>
            <p class="times" v-if="external(item)">报告时间：{{ beijingTime(item.reported_at) }} · 收到时间：{{ beijingTime(item.received_at) }}（北京时间）</p><p class="times" v-else>发布/登记时间：{{ beijingTime(item.published_at) }}（北京时间）</p>
            <slot v-if="!external(item)" name="native-actions" :item="item" />
          </article>
          <button v-if="detail(row).more" :disabled="detail(row).busy" @click="emit('details', row, true)">继续加载该文章明细</button>
        </div>
      </details>
      <p v-if="state.buckets.linked.error" role="alert" class="error">{{ state.buckets.linked.error }}</p><button v-if="state.buckets.linked.more" :disabled="state.buckets.linked.busy" @click="emit('more', 'linked')">继续加载文章</button>
      <details class="separate-bucket" open>
        <summary>待关联（{{ state.counts.unlinked }} 条）</summary><p>当前客户和网站内，尚未选择稿件的外部回传。</p><p v-if="!state.buckets.unlinked.items.length" class="empty">暂无待关联记录（0）</p>
        <article v-for="item in state.buckets.unlinked.items" :key="item.key" class="publication-detail"><p><span class="tag external">外部回传</span> {{ item.channel || '平台未记录' }} · {{ item.title || '未提供标题' }}</p><a v-if="safePublicationUrl(item.url)" :href="safePublicationUrl(item.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ item.url }}</a><p>{{ reportedResult(item.status) }} · 未关联稿件，不核验正文</p><p class="times">报告时间：{{ beijingTime(item.reported_at) }} · 收到时间：{{ beijingTime(item.received_at) }}（北京时间）</p><button v-if="item.can_link" @click="emit('link', item)">去关联稿件</button><p v-else>请由回传所属顾问或有权管理员处理。</p></article>
        <p v-if="state.buckets.unlinked.error" role="alert" class="error">{{ state.buckets.unlinked.error }}</p><button v-if="state.buckets.unlinked.more" :disabled="state.buckets.unlinked.busy" @click="emit('more', 'unlinked')">继续加载待关联</button>
      </details>
      <details class="separate-bucket"><summary>关联异常（{{ state.counts.invalid }} 条，仅内部）</summary><p>关联异常，需核对；不显示失效目标的文章标题。</p><p v-if="!state.buckets.invalid.items.length">暂无关联异常（0）</p><article v-for="item in state.buckets.invalid.items" :key="item.key" class="publication-detail"><p>外部回传 · {{ item.channel || '平台未记录' }} · 关联目标需重新核对</p><a v-if="safePublicationUrl(item.url)" :href="safePublicationUrl(item.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ item.url }}</a><p>{{ reportedResult(item.status) }} · 正文暂不可核验</p></article><p v-if="state.buckets.invalid.error" role="alert" class="error">{{ state.buckets.invalid.error }}</p><button v-if="state.buckets.invalid.more" :disabled="state.buckets.invalid.busy" @click="emit('more', 'invalid')">继续加载关联异常</button></details>
    </template>
  </section>
</template>
<style scoped>
.publication-groups{color:#23354d;overflow-wrap:anywhere}h2{font-size:18px;margin:0 0 8px}p{margin:8px 0;line-height:1.6}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.toolbar p,.note,.times,.compact{color:#68778c;font-size:13px}button,select{background:white;border:1px solid #cdd8e5;border-radius:6px;padding:8px 12px;font:inherit;color:#234569;cursor:pointer}button:disabled{opacity:.5;cursor:wait}button:focus-visible,summary:focus-visible,select:focus-visible{outline:3px solid #82b5ee;outline-offset:3px}.counts{display:flex;flex-wrap:wrap;gap:12px 26px;padding:16px;background:#f2f6fc;border-radius:8px;margin-bottom:16px}.counts b{color:#164a85;font-size:20px;margin:0 5px}.compact{margin-top:10px}.compact select{margin-left:8px}.article-group{border:1px solid #dbe3ed;border-radius:8px;margin:10px 0}.article-group summary{background:#f8fafc;border-radius:8px}summary{cursor:pointer;padding:15px;font-weight:600;line-height:1.7}.article-title{margin-right:16px}.source-counts{color:#62748a;font-size:13px;font-weight:normal;white-space:nowrap}.article-details{padding:0 18px 16px}.publication-detail{padding:14px 0;border-bottom:1px solid #e8edf4}.detail-heading{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:8px}.tag{background:#e8f0fb;border-radius:4px;padding:3px 8px;color:#24558d;font-size:12px;display:inline-block}.tag.external{background:#fff3df;color:#875c0a}.publication-detail a{color:#2563a1;overflow-wrap:anywhere}.report-status{color:#77582a}.empty{color:#7b8797;padding:10px 0}.error{color:#a83232;background:#fff5f5;padding:10px;border-radius:6px}.separate-bucket{border-top:1px solid #dbe3ed;margin-top:22px}.separate-bucket>p,.separate-bucket>article{margin-left:15px;margin-right:15px}.scope-prompt{background:#f2f6fc;padding:16px}@media(max-width:600px){.toolbar{align-items:flex-start;flex-direction:column;gap:10px}.counts{gap:8px;flex-direction:column}.source-counts{display:block;white-space:normal}.article-details{padding:0 12px 12px}.compact{font-size:12px}}
</style>
