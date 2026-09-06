<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { seoQaGet, seoQaPost, generateSeoQaDraft } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean,questions:{type:Array,default:()=>[]}})
const emit=defineEmits(['changed','open'])
const rows=ref([]),facts=ref([]),busy=ref(false),loading=ref(false),error=ref(''),stop=ref(false)
const format=ref('short')
const scopeKey=computed(()=>`${props.tenantId}:${props.siteId}`)
let generation=0
function detail(e){return typeof e?.response?.data?.detail==='string'?e.response.data.detail:e.message||'操作失败，可重试本题'}
function params(){return {tenant_id:props.tenantId,site_id:props.siteId}}
async function prepare(){
  if(!props.canEdit||busy.value||loading.value||!props.questions.length||props.questions.length>20)return
  const ticket=generation,key=scopeKey.value;loading.value=true;error.value=''
  try{
    const value=await seoQaGet('facts',params())
    if(ticket!==generation||key!==scopeKey.value)return
    facts.value=value.filter(f=>f.current)
    rows.value=props.questions.map(q=>({question:{...q},id:q.id,version:q.version,title:q.title,factIds:[],state:'pending',error:'',draft:null,answerId:null}))
  }catch(e){if(ticket===generation)error.value=detail(e)}finally{loading.value=false}
}
async function run(onlyId=null){
  if(!props.canEdit||busy.value||loading.value)return
  const pending=rows.value.filter(r=>r.state!=='done'&&(onlyId===null||r.id===onlyId))
  if(!pending.length)return
  if(pending.some(r=>!r.draft&&!r.factIds.length)){error.value='请为每道待生成问题选择适用的事实资料';return}
  const ticket=generation,key=scopeKey.value,scope=params(),chosenFormat=format.value
  const active=()=>ticket===generation&&key===scopeKey.value&&props.canEdit
  busy.value=true;stop.value=false;error.value='';let saved=false
  try{
    for(const row of pending){
      if(!active()||stop.value)break
      row.error=''
      try{
        if(!row.draft){
          row.state='generating'
          const refs=row.factIds.map(id=>facts.value.find(f=>f.id===id))
          if(refs.some(f=>!f))throw new Error('事实资料已变化，请重新准备批次')
          const value=await generateSeoQaDraft({...scope,question:{id:row.id,version:row.version},facts:refs.map(f=>({id:f.id,version:f.version})),format:chosenFormat})
          if(!active())break
          if(value.question_id!==row.id||value.expected_question_version!==row.version)throw new Error('生成结果与问题版本不匹配')
          row.draft=value
        }
        if(!active())break
        row.state='saving'
        const {body,fact_ids,expected_facts,expected_question_version}=row.draft
        const value=await seoQaPost('answers',{...scope,question_id:row.id,format:row.draft.format,body,fact_ids,expected_facts,expected_question_version})
        if(!active())break
        row.answerId=value.id;row.state='done';saved=true
      }catch(e){
        if(!active())break
        row.state='failed';row.error=detail(e)
      }
    }
  }finally{
    busy.value=false
    if(saved&&active())emit('changed')
  }
}
function resetRow(row){if(busy.value||!props.canEdit||row.state==='done')return;row.draft=null;row.state='pending';row.error=''}
watch(scopeKey,()=>{++generation;stop.value=true;rows.value=[];facts.value=[];error.value=''})
onBeforeUnmount(()=>{++generation;stop.value=true})
</script>
<template>
  <section class="batch-drafts">
    <h3>批量生成回答草稿</h3>
    <p>先在选题规划中选择 1–20 道问题，再逐题选择适用事实。每题消耗 1 次 AI 用量，依次生成并保存为草稿，之后仍需逐条核对和审核。</p>
    <p>请保持本页打开。离开页面会停止后续题目；已经发出的生成或保存请求可能继续完成，已保存稿件可在问题详情查看。待处理队列不跨页面保存。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="batch-actions"><el-button :loading="loading" :disabled="!canEdit||busy||!questions.length||questions.length>20" @click="prepare">用所选问题准备批次（{{ questions.length }}）</el-button><el-select v-model="format" :disabled="busy||!canEdit"><el-option label="短答" value="short"/><el-option label="详答" value="detailed"/><el-option label="操作步骤" value="steps"/><el-option label="比较" value="comparison"/><el-option label="FAQ" value="faq"/></el-select></div>
    <article v-for="row in rows" :key="row.id">
      <strong>{{ row.title }}</strong>
      <el-select v-model="row.factIds" multiple :multiple-limit="20" filterable placeholder="选择本题适用的事实（最多 20 条）" :disabled="!canEdit||busy||!!row.draft||row.state==='done'"><el-option v-for="fact in facts" :key="fact.id" :label="`F${fact.id} · ${fact.title}`" :value="fact.id"/></el-select>
      <span>{{ {pending:'待生成',generating:'生成中',saving:'保存中',done:'草稿已保存 · 待人工审核',failed:'本题失败'}[row.state] }}</span>
      <p v-if="row.error" class="batch-error">{{ row.error }}</p>
      <details v-if="row.draft"><summary>查看生成正文</summary><pre>{{ row.draft.body }}</pre></details>
      <div class="batch-actions"><el-button v-if="row.state==='failed'" :disabled="!canEdit||busy" @click="run(row.id)">{{ row.draft?'只重试保存（不调用 AI）':'重试本题生成' }}</el-button><el-button v-if="row.state==='failed'&&row.draft" :disabled="!canEdit||busy" @click="resetRow(row)">放弃本稿并重新选资料</el-button><el-button v-if="row.answerId" :disabled="busy" @click="emit('open',row.question)">打开问题逐条审核</el-button></div>
    </article>
    <div v-if="rows.length" class="batch-actions"><el-button type="primary" :loading="busy" :disabled="!canEdit||loading||rows.every(r=>r.state==='done')" @click="run()">生成／继续未完成题目</el-button><el-button v-if="busy" @click="stop=true">完成当前题后暂停</el-button><span>已保存 {{ rows.filter(r=>r.state==='done').length }} / {{ rows.length }}</span></div>
  </section>
</template>
<style scoped>
.batch-drafts{border:1px solid #dce7ec;border-radius:12px;padding:20px;margin:20px 0;background:#fafcfd}.batch-drafts p{font-size:13px;line-height:1.8;color:#657c8b}.batch-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}.batch-actions .el-select{width:160px}.batch-drafts article{border-top:1px solid #dce7ec;padding:16px 0;display:grid;gap:12px}.batch-drafts pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.batch-drafts .batch-error{color:#b34236}.batch-drafts h3{margin:0 0 12px}
</style>
