<script setup>
import SeoQaBatchReview from './SeoQaBatchReview.vue'
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { seoQaGet, seoQaPost } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean,questions:{type:Array,default:()=>[]}})
const emit=defineEmits(['changed','open'])
const rows=ref([]),facts=ref([]),busy=ref(false),loading=ref(false),error=ref(''),format=ref('short')
const current=ref(null),history=ref([]),requestId=ref('')
const scopeKey=computed(()=>`${props.tenantId}:${props.siteId}`)
const statusLabels={queued:'排队中',running:'执行中',paused:'已暂停',completed:'本轮处理结束',cancelled:'已取消'}
const itemLabels={pending:'待处理',generating:'生成中',saving:'保存中',done:'草稿已保存（审核状态见下方验收）',failed:'失败 · 可重试'}
let generation=0,refreshing=false
function params(){return {tenant_id:props.tenantId,site_id:props.siteId}}
function detail(e){const d=e?.response?.data?.detail;return typeof d==='string'?d:d?.message||e.message||'操作失败，请稍后重试'}
async function refresh(){
  if(refreshing||!props.tenantId||!props.siteId)return
  const ticket=generation,key=scopeKey.value,id=current.value?.id;refreshing=true
  try{
    const value=await seoQaGet('batches',params())
    if(ticket!==generation||key!==scopeKey.value)return
    history.value=value.items
    if(id){
      const batch=await seoQaGet(`batches/${id}`,params())
      if(ticket===generation&&key===scopeKey.value&&id===current.value?.id){
        const before=current.value.items?.filter(i=>i.state==='done').length||0
        current.value=batch
        if(batch.items.filter(i=>i.state==='done').length>before)emit('changed')
      }
    }
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{refreshing=false}
}
async function selectBatch(id){
  if(busy.value)return
  const ticket=generation,key=scopeKey.value;current.value={id,items:[]};error.value=''
  try{const value=await seoQaGet(`batches/${id}`,params());if(ticket===generation&&key===scopeKey.value&&id===current.value?.id)current.value=value}
  catch(e){if(ticket===generation)error.value=detail(e)}
}
async function prepare(){
  if(!props.canEdit||busy.value||loading.value||!props.questions.length||props.questions.length>20)return
  const ticket=generation,key=scopeKey.value;loading.value=true;error.value=''
  try{
    const value=await seoQaGet('facts',params())
    if(ticket!==generation||key!==scopeKey.value)return
    facts.value=value.filter(f=>f.current)
    rows.value=props.questions.map(q=>({question:{...q},factIds:[]}))
    requestId.value=crypto.randomUUID();current.value=null
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{loading.value=false}
}
async function submit(){
  if(!props.canEdit||busy.value||loading.value||!rows.value.length)return
  if(rows.value.some(r=>!r.factIds.length)){error.value='请为每道问题选择适用事实';return}
  const ticket=generation,key=scopeKey.value;busy.value=true;error.value=''
  try{
    const items=rows.value.map(r=>({question:{id:r.question.id,version:r.question.version},format:format.value,
      facts:r.factIds.map(id=>{const f=facts.value.find(f=>f.id===id);return {id,version:f.version}})}))
    const value=await seoQaPost('batches',{...params(),request_id:requestId.value,items})
    if(ticket===generation&&key===scopeKey.value){current.value=value;rows.value=[];await refresh()}
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{busy.value=false}
}
async function control(action,questionId=null){
  if(!props.canEdit||busy.value||!current.value?.id)return
  const ticket=generation,key=scopeKey.value,id=current.value.id;busy.value=true;error.value=''
  try{
    const value=await seoQaPost(`batches/${id}/control`,{...params(),action,question_id:questionId})
    if(ticket===generation&&key===scopeKey.value&&id===current.value?.id){current.value=value;await refresh()}
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{busy.value=false}
}
async function openQuestion(item){
  const ticket=generation,key=scopeKey.value
  try{const value=await seoQaGet(`questions/${item.question_id}/detail`,params());if(ticket===generation&&key===scopeKey.value)emit('open',value.question)}
  catch(e){if(ticket===generation)error.value=detail(e)}
}
watch(scopeKey,()=>{++generation;rows.value=[];facts.value=[];history.value=[];current.value=null;error.value='';refresh()},{immediate:true})
const poll=setInterval(refresh,10000)
onBeforeUnmount(()=>{++generation;clearInterval(poll)})
</script>
<template>
  <section class="batch-drafts">
    <h3>后台批量生成回答</h3>
    <p>选择 1–20 道问题，逐题选事实并提交后台。关闭页面后继续执行，重新打开可在“本人批次”查看进度。每题消耗 1 次 AI 用量，保存为草稿后仍需逐条核对审核。</p>
    <p>暂停会让当前题完成后停止后续题目；取消不保证撤回已发出的请求。服务重启后继续处理，账号或资料失效会阻止执行。进度每 10 秒刷新。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="batch-actions"><el-button :loading="loading" :disabled="!canEdit||busy||!questions.length||questions.length>20" @click="prepare">用所选问题准备批次（{{ questions.length }}）</el-button><el-select v-model="format" :disabled="busy||!canEdit"><el-option label="短答" value="short"/><el-option label="详答" value="detailed"/><el-option label="步骤" value="steps"/><el-option label="比较" value="comparison"/><el-option label="FAQ" value="faq"/></el-select></div>
    <article v-for="row in rows" :key="row.question.id"><strong>{{ row.question.title }}</strong><el-select v-model="row.factIds" multiple :multiple-limit="20" filterable placeholder="选择本题适用事实" :disabled="busy||!canEdit"><el-option v-for="fact in facts" :key="fact.id" :label="`F${fact.id} · ${fact.title}`" :value="fact.id"/></el-select></article>
    <el-button v-if="rows.length" type="primary" :loading="busy" :disabled="!canEdit||loading" @click="submit">提交后台（{{ rows.length }} 题）</el-button>
    <div class="batch-actions"><strong>本人批次（最近 20 个）</strong><el-button :disabled="busy" @click="refresh">刷新进度</el-button></div>
    <div v-for="batch in history" :key="batch.id" class="batch-actions"><el-button :disabled="busy" @click="selectBatch(batch.id)">#{{ batch.id }} · {{ statusLabels[batch.status] }} · 已保存 {{ batch.items.filter(i=>i.state==='done').length }}/{{ batch.items.length }}</el-button><span>{{ new Date(batch.created_at).toLocaleString('zh-CN') }}</span></div>
    <template v-if="current">
      <h4>批次 #{{ current.id }} · {{ statusLabels[current.status] }}</h4>
      <div class="batch-actions"><el-button v-if="['queued','running'].includes(current.status)" :disabled="busy||!canEdit" @click="control('pause')">暂停后续题目</el-button><el-button v-if="current.status==='paused'" :disabled="busy||!canEdit" @click="control('resume')">恢复后台处理</el-button><el-button v-if="current.items.some(i=>i.state==='failed')&&current.status!=='cancelled'" :disabled="busy||!canEdit" @click="control('retry')">重试失败题目</el-button><el-button v-if="['queued','running','paused'].includes(current.status)" :disabled="busy||!canEdit" @click="control('cancel')">取消批次</el-button></div>
      <article v-for="item in current.items" :key="item.question_id"><strong>{{ item.title }}</strong><span>{{ itemLabels[item.state] }}</span><p v-if="item.error" class="batch-error">{{ item.error }}。资料或问题版本变化时，请刷新规划并重新准备批次。</p><details v-if="item.draft"><summary>生成时正文（历史快照）</summary><pre>{{ item.draft.body }}</pre></details><div class="batch-actions"><el-button v-if="item.state==='failed'&&current.status!=='cancelled'" :disabled="busy||!canEdit" @click="control('retry',item.question_id)">{{ item.draft?'只重试保存（不调用 AI）':'重试本题' }}</el-button><el-button v-if="item.answer_id" @click="openQuestion(item)">打开问题逐条审核</el-button></div></article>
      <SeoQaBatchReview :key="current.id" :tenant-id="tenantId" :site-id="siteId" :batch-id="current.id" :can-edit="canEdit" :disabled="busy" @changed="emit('changed')" @open="row=>emit('open',row)"/>
    </template>
  </section>
</template>
<style scoped>
.batch-drafts{border:1px solid #dce7ec;border-radius:12px;padding:20px;margin:20px 0;background:#fafcfd}.batch-drafts p{font-size:13px;line-height:1.8;color:#657c8b}.batch-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}.batch-actions .el-select{width:160px}.batch-drafts article{border-top:1px solid #dce7ec;padding:16px 0;display:grid;gap:12px}.batch-drafts pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.batch-drafts .batch-error{color:#b34236}.batch-drafts h3{margin:0 0 12px}.batch-actions .el-button{max-width:100%;height:auto;white-space:normal;line-height:1.5}
</style>
