<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { seoQaGet, seoQaPost } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,batchId:Number,canEdit:Boolean,disabled:Boolean})
const emit=defineEmits(['changed','open'])
const result=ref(null),loading=ref(false),acting=ref(false),error=ref(''),exportMessage=ref(''),filter=ref('all'),notes=ref({}),rowErrors=ref({})
const scopeKey=computed(()=>`${props.tenantId}:${props.siteId}:${props.batchId}`)
const buckets={all:'全部',draft:'待提交',review:'待审核',needs_fix:'需修复',approved:'已审核',not_saved:'尚不可验收'}
const labels={planned:'草稿',drafting:'草稿',review:'待审核',ready:'已审核',published:'已有发布记录'}
const shown=computed(()=>result.value?.items.filter(r=>filter.value==='all'||r.bucket===filter.value)||[])
let generation=0
function params(){return {tenant_id:props.tenantId,site_id:props.siteId}}
function detail(e){const d=e?.response?.data?.detail;return typeof d==='string'?d:d?.message||e.message||'操作失败，请刷新后重试'}
function key(row){return `${row.answer_id}:${row.content_version}:${row.status}`}
function href(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null}catch{return null}}
async function load(force=false){
  if((loading.value&&!force)||!props.batchId||!props.siteId||!props.tenantId)return
  const ticket=generation,scope=scopeKey.value;loading.value=true;error.value=''
  try{const value=await seoQaGet(`batches/${props.batchId}/review`,params());if(ticket===generation&&scope===scopeKey.value)result.value=value}
  catch(e){if(ticket===generation)error.value=detail(e)}finally{if(ticket===generation)loading.value=false}
}
async function review(row,action){
  if(!props.canEdit||props.disabled||acting.value||loading.value||!row.available)return
  if(action==='submit'&&(!['planned','drafting'].includes(row.status)||row.problems.length))return
  if(['approve','reject'].includes(action)&&row.status!=='review')return
  if(action==='approve'&&(row.problems.length||row.can_approve===false))return
  const rowKey=key(row),note=(notes.value[rowKey]||'').trim()
  if(action==='reject'&&!note){rowErrors.value[rowKey]='退回时请填写修改意见';return}
  const ticket=generation,scope=scopeKey.value;acting.value=true;rowErrors.value[rowKey]=''
  try{
    await seoQaPost(`batches/${props.batchId}/answers/${row.answer_id}/review`,{...params(),action,note:note||null,content_version:row.content_version,question_version:row.question_version})
    if(ticket===generation&&scope===scopeKey.value){delete notes.value[rowKey];await load();if(ticket===generation&&scope===scopeKey.value)emit('changed')}
  }catch(e){if(ticket===generation)rowErrors.value[rowKey]=detail(e)}finally{acting.value=false}
}
async function exportBatch(kind){
  if(acting.value||loading.value||props.disabled)return
  const ticket=generation,scope=scopeKey.value;acting.value=true;error.value='';exportMessage.value=''
  try{
    const value=await seoQaGet(`batches/${props.batchId}/export`,{...params(),kind})
    if(ticket!==generation||scope!==scopeKey.value)return
    const bytes=Uint8Array.from(atob(value.content_base64),c=>c.charCodeAt(0))
    const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}))
    const link=document.createElement('a');link.href=url;link.download=value.filename;document.body.appendChild(link)
    try{link.click()}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
    exportMessage.value=`已导出 ${value.included_count} 条，未包含 ${value.excluded_count} 条；快照时间 ${value.as_of}。平台发布前请再次确认有效性。`
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{acting.value=false}
}
async function open(row){
  if(acting.value||loading.value||props.disabled)return
  const ticket=generation,scope=scopeKey.value
  try{const value=await seoQaGet(`questions/${row.question_id}/detail`,params());if(ticket===generation&&scope===scopeKey.value)emit('open',{...value.question, preferred_answer_id:row.answer_id})}
  catch(e){if(ticket===generation)error.value=detail(e)}
}
watch(scopeKey,()=>{++generation;result.value=null;exportMessage.value='';notes.value={};rowErrors.value={};filter.value='all';load(true)},{immediate:true})
onBeforeUnmount(()=>{++generation})
</script>
<template>
  <section class="batch-review">
    <header><h3>批次集中验收</h3><el-button :loading="loading" :disabled="acting||disabled" @click="load">刷新验收内容</el-button></header>
    <p>展示当前保存正文，不使用生成时的历史快照。内容或问题版本变化后需刷新；审核操作不会调用 AI，也不会发布到平台。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="result">
      <p>{{ result.meaning }}</p>
      <div class="review-actions"><el-button :disabled="acting||loading||disabled" @click="exportBatch('approved')">导出已审核交付包</el-button><el-button :disabled="acting||loading||disabled" @click="exportBatch('pending')">导出待处理清单</el-button></div>
      <p v-if="exportMessage" role="status">{{ exportMessage }}</p>
      <div class="review-filters"><el-button v-for="(label,bucket) in buckets" :key="bucket" :type="filter===bucket?'primary':'default'" @click="filter=bucket">{{ label }} {{ bucket==='all'?result.items.length:result.counts[bucket] }}</el-button></div>
      <el-empty v-if="!shown.length" description="当前筛选下没有待处理回答"/>
      <details v-for="row in shown" :key="`${row.question_id}:${row.content_version||0}`" class="review-card">
        <summary>{{ row.title }} · {{ buckets[row.bucket] }}<span v-if="row.available"> · 正文 v{{ row.content_version }}</span></summary>
        <template v-if="row.available">
          <p>当前问题 v{{ row.question_version }} · {{ labels[row.status]||row.status }}</p>
          <p v-if="row.question_changed" class="review-warning">问题在生成后已修改，请按上方当前问题重新核对回答是否适用。</p>
          <p v-if="row.status==='review'&&row.can_approve===false" class="review-warning">提交人不能自审，请另一位有内容编辑权限的实名账号在站点批次中审核。</p><h4>当前回答正文</h4><pre>{{ row.body }}</pre>
          <p v-for="problem in row.problems" :key="problem" class="review-warning">需修复：{{ problem }}</p>
          <h4>保存时的事实引用</h4>
          <blockquote v-for="fact in row.facts" :key="fact.id"><strong>[F{{ fact.id }}] {{ fact.title }} · v{{ fact.version }}</strong><p v-if="!fact.current" class="review-warning">此引用版本已变化、失效或删除</p><pre>{{ fact.statement }}</pre><p>来源：{{ fact.source_name }} <a v-if="href(fact.source_url)" :href="href(fact.source_url)" target="_blank" rel="noopener noreferrer">查看出处</a></p></blockquote>
          <h4>程序质量提示</h4><p>{{ row.quality.meaning }}</p>
          <p v-for="(hint,i) in row.quality.hints" :key="i" class="review-warning">第 {{ hint.paragraph }} 段：{{ hint.message }}<br/>{{ hint.excerpt }}</p>
          <p v-if="row.quality.hints_total>row.quality.hints.length">仅显示前 {{ row.quality.hints.length }} 条，共 {{ row.quality.hints_total }} 条提示。</p>
          <p v-if="!row.quality.hints.length">未发现上述文字特征问题，仍需人工核对。</p>
          <p v-for="check in row.quality.manual_review" :key="check">人工核对：{{ check }}</p>
          <p v-if="row.review_note">上次审核意见：{{ row.review_note }}</p>
          <el-input v-if="['planned','drafting','review'].includes(row.status)" v-model="notes[key(row)]" type="textarea" :rows="2" maxlength="2000" placeholder="审核意见，退回时必填" :disabled="!canEdit||acting||loading||disabled"/>
          <p v-if="rowErrors[key(row)]" class="review-warning">{{ rowErrors[key(row)] }}</p>
          <div class="review-actions"><el-button v-if="['planned','drafting'].includes(row.status)" :disabled="!canEdit||acting||loading||disabled||!!row.problems.length" @click="review(row,'submit')">提交本条审核</el-button><template v-if="row.status==='review'"><el-button type="success" :disabled="!canEdit||acting||loading||disabled||!!row.problems.length||row.can_approve===false" @click="review(row,'approve')">本条审核通过</el-button><el-button :disabled="!canEdit||acting||loading||disabled" @click="review(row,'reject')">退回本条修改</el-button></template><el-button :disabled="acting||loading||disabled" @click="open(row)">{{ ['ready','published'].includes(row.status) ? '打开回答准备分发' : '打开问题编辑' }}</el-button></div>
        </template>
        <p v-else>{{ row.generation_error||row.reason }}。请在批次进度中处理生成或保存失败。</p>
      </details>
    </template>
  </section>
</template>
<style scoped>
.batch-review{border-top:2px solid #d9e5eb;margin-top:24px;padding-top:20px}.batch-review header,.review-filters,.review-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.batch-review header{justify-content:space-between}.batch-review h3{margin:0}.batch-review p{font-size:13px;line-height:1.8;color:#657c8b}.review-filters{margin:18px 0}.review-card{border:1px solid #dce7ec;border-radius:10px;padding:16px;margin:14px 0;background:white}.review-card summary{cursor:pointer;line-height:1.8;font-weight:600;overflow-wrap:anywhere}.batch-review pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8}.batch-review blockquote{margin:12px 0;padding:12px;background:#f5f8fa;border-left:3px solid #9cbfc8}.batch-review .review-warning{color:#a65a16}.review-actions{margin-top:14px}
</style>
