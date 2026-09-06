<script setup>
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import { seoQaGet, seoQaPost, extractSeoQaDocument, analyzeSeoQaQuality, previewSeoQaFile } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean,mode:{type:String,default:'extract'},answerId:Number,contentVersion:Number,questionVersion:Number,blocked:Boolean})
const emit=defineEmits(['changed'])
const source=reactive({source_name:'',source_url:'',text:''})
const result=ref(null),history=ref([]),chosen=ref([]),busy=ref(false),reading=ref(false),error=ref(''), fileWarnings=ref([])
const scopeKey=computed(()=>`${props.tenantId}:${props.siteId}:${props.mode}:${props.answerId||''}`)
const current=computed(()=>props.mode==='extract'||(result.value?.current!==false&&result.value?.answer_id===props.answerId&&result.value?.content_version===props.contentVersion&&result.value?.question_version===props.questionVersion&&!props.blocked))
const issueLabels={missing_answer:'问题覆盖不足',missing_condition:'适用条件不全',unsupported_claim:'引用支持不足',contradiction:'可能与资料矛盾'}
let generation=0
function message(e){const d=e?.response?.data?.detail;return typeof d==='string'?d:Array.isArray(d)?d.map(x=>x.msg).join('；'):d?.message||e.message||'操作失败'}
function params(){return {tenant_id:props.tenantId,site_id:props.siteId}}
async function analyze(){
  if(!props.canEdit||busy.value||reading.value||props.blocked||!props.tenantId||!props.siteId)return
  const ticket=++generation,key=scopeKey.value
  busy.value=true;error.value='';result.value=null;chosen.value=[]
  try{
    const value=props.mode==='extract'?await extractSeoQaDocument({...params(),...source,source_url:source.source_url||null}):await analyzeSeoQaQuality({...params(),answer_id:props.answerId,content_version:props.contentVersion})
    if(ticket===generation&&key===scopeKey.value)result.value=value
  }catch(e){if(ticket===generation&&key===scopeKey.value)error.value=message(e)}finally{busy.value=false}
}
async function loadHistory(){
  if(busy.value||reading.value||!props.tenantId||!props.siteId)return
  const ticket=generation,key=scopeKey.value;busy.value=true;error.value=''
  try{const value=await seoQaGet('research/history',{...params(),kind:props.mode,...(props.mode==='quality'?{answer_id:props.answerId}:{})});if(ticket===generation&&key===scopeKey.value)history.value=value.items}
  catch(e){if(ticket===generation&&key===scopeKey.value)error.value=message(e)}finally{busy.value=false}
}
async function recover(row){
  if(busy.value||reading.value||!row.has_result)return
  const ticket=++generation,key=scopeKey.value;busy.value=true;error.value='';chosen.value=[];result.value=null
  try{
    const value=await seoQaGet(`research/history/${row.id}`,params())
    if(ticket!==generation||key!==scopeKey.value)return
    if(value.action!==`qa_${props.mode}`||(props.mode==='quality'&&value.answer_id!==props.answerId))throw new Error('分析记录不属于当前类型或回答')
    result.value=value
  }catch(e){if(ticket===generation&&key===scopeKey.value)error.value=message(e)}finally{busy.value=false}
}
async function accept(){
  if(!props.canEdit||busy.value||reading.value||props.mode!=='extract'||!result.value||!chosen.value.length)return
  const ticket=generation,key=scopeKey.value;busy.value=true;error.value=''
  try{const value=await seoQaPost(`research/${result.value.operation_id}/accept`,{...params(),indices:[...chosen.value]});if(ticket===generation&&key===scopeKey.value){result.value={...result.value,accepted:value.accepted};chosen.value=[];emit('changed')}}
  catch(e){if(ticket===generation&&key===scopeKey.value)error.value=message(e)}finally{busy.value=false}
}
async function readText(event){
  const file=event.target.files?.[0];event.target.value=''
  if(!file||!props.canEdit||busy.value||reading.value)return
  const ticket=generation,key=scopeKey.value;reading.value=true;error.value=''
  try{
    let text,warnings=[]
    if(/\.(pdf|docx)$/i.test(file.name)){
      if(file.size>5*1024*1024)throw new Error('PDF / DOCX 文件不能超过 5MB')
      const value=await previewSeoQaFile(params(),file);text=value.text;warnings=value.warnings||[]
    }else{
      if(!/\.(txt|md)$/i.test(file.name)||file.size>120000)throw new Error('请选择 5MB 以内 PDF/DOCX，或 120KB 以内 UTF-8 TXT/Markdown')
      text=(await file.text()).replace(/^\uFEFF/,'')
    }
    if(text.includes('\uFFFD')||text.includes('\u0000'))throw new Error('无法按 UTF-8 文本读取，请转换编码后重试')
    if(text.length>30000)throw new Error('原文最多 3 万字，请按章节拆分')
    if(ticket===generation&&key===scopeKey.value){source.text=text;source.source_name=file.name.slice(0,240);source.source_url='';fileWarnings.value=warnings}
  }catch(e){if(ticket===generation&&key===scopeKey.value)error.value=message(e)}finally{reading.value=false}
}
watch(scopeKey,()=>{++generation;result.value=null;history.value=[];chosen.value=[];error.value='';fileWarnings.value=[];Object.assign(source,{source_name:'',source_url:'',text:''})})
watch(()=>[source.text,source.source_name,source.source_url],()=>{result.value=null;chosen.value=[]})
onBeforeUnmount(()=>{++generation})
</script>
<template>
  <section class="qa-research">
    <h3>{{ mode==='extract'?'从资料提取问题与事实':'AI 深度质量分析' }}</h3>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <p class="research-note">每次分析消耗一次 SEO AI 用量，提交内容会交给当前配置的 AI 服务。分析不自动改稿、审核或发布；历史取回不再次扣费。</p>
    <template v-if="mode==='extract'">
      <el-form label-position="top" :disabled="!canEdit||busy||reading">
        <el-form-item label="资料名称"><el-input v-model="source.source_name" maxlength="240" placeholder="例如：产品手册 v2 · 使用条件章节"/></el-form-item>
        <el-form-item label="原文网址（可选）"><el-input v-model="source.source_url" maxlength="2000"/></el-form-item>
        <el-form-item label="资料原文"><input type="file" accept=".txt,.md,.pdf,.docx" :disabled="!canEdit||busy||reading" @change="readText"/><el-input v-model="source.text" type="textarea" :rows="8" maxlength="30000" show-word-limit placeholder="粘贴产品手册或官网原文，保留条件、单位及出处。支持 PDF、DOCX、UTF-8 TXT/Markdown。请先核对解析原文，再点击提取候选；扫描件需先 OCR。"/></el-form-item>
      </el-form>
      <p class="research-note">读取文件不消耗 AI 用量。PDF/DOCX 会上传到服务器临时解析，不保存原文件；最多 5MB、PDF 100 页、原文 3 万字。</p>
      <p v-if="reading">正在解析文件，请稍候…</p>
      <p v-for="warning in fileWarnings" :key="warning" class="research-warning">{{ warning }}</p>
    </template>
    <p v-else class="research-note">检查问题遗漏、适用条件、断言与引用支持关系。仅分析已保存版本；正文最多 2 万字，引用原文合计最多 3 万字。</p>
    <p v-if="blocked" class="research-warning">请先保存修改并修复事实关联，再分析当前版本。</p>
    <div class="research-actions"><el-button :loading="busy" :disabled="!canEdit||reading||blocked||(mode==='extract'&&(!source.source_name.trim()||source.text.trim().length<30))" @click="analyze">{{ mode==='extract'?'提取候选（1 次用量）':'分析已保存回答（1 次用量）' }}</el-button><el-button :disabled="busy||reading" @click="loadHistory">查看本人历史分析</el-button></div>
    <div v-for="row in history" :key="row.id" class="research-actions"><span>{{ new Date(row.created_at).toLocaleString('zh-CN') }} · {{ {running:'处理中',succeeded:'已完成',refunded:'已退款'}[row.status]||row.status }}</span><el-button :disabled="busy||!row.has_result" @click="recover(row)">取回结果</el-button></div>
    <template v-if="result">
      <p class="research-note">{{ result.meaning }}</p>
      <template v-if="mode==='extract'">
        <p>资料：{{ result.source_name }}<span v-if="result.source_url"> · {{ result.source_url }}</span></p>
        <p class="research-note">引用位置为提交原文中的字符区间（从 0 开始，不含结束位置）。入库前请逐条核对原文与问题；建议问题不代表真实搜索需求。</p>
        <el-empty v-if="!result.candidates.length" description="没有提取到有原文依据的候选"/>
        <article v-for="row in result.candidates" :key="row.index"><el-checkbox :model-value="chosen.includes(row.index)" @change="checked=>chosen=checked?[...chosen,row.index]:chosen.filter(i=>i!==row.index)" :disabled="!canEdit||busy||!!result.accepted?.[row.index]">{{ row.question }}</el-checkbox><blockquote>{{ row.quote }}</blockquote><small>原文位置 {{ row.start }}–{{ row.end }}</small><p v-if="result.accepted?.[row.index]">已入库：问题 #{{ result.accepted[row.index].question_id }} · 事实 F{{ result.accepted[row.index].fact_id }}</p></article>
        <el-button type="primary" :disabled="!canEdit||busy||!chosen.length" @click="accept">确认所选原文并入库（{{ chosen.length }}）</el-button>
      </template>
      <template v-else>
        <p>分析稿件版本 {{ result.content_version }} · 问题版本 {{ result.question_version }}</p>
        <p v-if="!current" class="research-warning">分析版本与当前内容不一致或存在未保存/证据问题，请重新分析；以下仅作历史参考。</p>
        <el-empty v-if="!result.issues.length" description="本次 AI 未提出问题，不代表已证明回答完整或事实真实"/>
        <article v-for="(issue,i) in result.issues" :key="i"><strong>{{ issueLabels[issue.kind] }}</strong><blockquote v-if="issue.quote">{{ issue.quote }}</blockquote><p>{{ issue.reason }}</p><p>修改建议：{{ issue.suggestion }}</p><small>对照事实：{{ issue.fact_ids.length?issue.fact_ids.map(id=>'F'+id).join('、'):'未指定，请人工核对' }}</small></article>
      </template>
    </template>
  </section>
</template>
<style scoped>
.qa-research{margin:20px 0;padding:20px;border:1px solid #dce7ec;border-radius:12px;background:#fafcfd;color:#18334a}.qa-research h3{margin:0 0 16px}.research-note{font-size:13px;color:#657c8b;line-height:1.8}.research-warning{color:#a96108;line-height:1.7}.research-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}.qa-research article{padding:16px 0;border-top:1px solid #e1e9ee}.qa-research blockquote{white-space:pre-wrap;overflow-wrap:anywhere;margin:12px 0;padding:12px;border-left:3px solid #9fc8ce;background:white;line-height:1.8}.qa-research p{overflow-wrap:anywhere}.qa-research small{color:#657c8b}.qa-research :deep(.el-checkbox){height:auto;align-items:flex-start}.qa-research :deep(.el-checkbox__label){white-space:normal;line-height:1.6}.qa-research input[type=file]{max-width:100%;margin-bottom:12px}@media(max-width:600px){.qa-research{padding:14px}}
</style>
