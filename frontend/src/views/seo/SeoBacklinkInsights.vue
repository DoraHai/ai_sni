<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { importSeoBacklinkCsv, fetchSeoBacklinkAnalysis, fetchSeoBacklinkIndexStatus, querySeoBacklinkIndex } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean})
const emit=defineEmits(['changed'])
const analysis=ref(null),provider=ref(null),input=ref(null),file=ref(null),preview=ref(null),dialog=ref(false),busy=ref(false),message=ref(''),error=ref('')
let generation=0
const params=()=>({tenantId:props.tenantId,siteId:props.siteId})
async function load(){
  const ticket=++generation;analysis.value=null;provider.value=null;preview.value=null;dialog.value=false;file.value=null;error.value='';message.value=''
  if(!props.tenantId||!props.siteId)return
  const responses=await Promise.allSettled([fetchSeoBacklinkAnalysis(params()),fetchSeoBacklinkIndexStatus(params())])
  if(ticket!==generation)return
  if(responses[0].status==='fulfilled')analysis.value=responses[0].value
  else error.value=responses[0].reason.message
  if(responses[1].status==='fulfilled')provider.value=responses[1].value
  else error.value+=` 索引服务状态读取失败：${responses[1].reason.message}`
  return true
}
function template(){
  const blob=new Blob(['\uFEFF来源页面,目标页面,锚文本\r\nhttps://media.example/article,https://your-site.example/page,资料来源\r\n'],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='外链导入模板.csv';link.click();URL.revokeObjectURL(url)
}
async function chooseFile(event){
  const selected=event.target.files?.[0];event.target.value=''
  if(!selected||busy.value||!props.canEdit)return
  if(selected.size>2*1024*1024){error.value='CSV 文件不能超过 2 MB';return}
  const ticket=generation;busy.value=true;error.value=''
  try{const value=await importSeoBacklinkCsv({...params(),file:selected});if(ticket===generation){file.value=selected;preview.value=value;dialog.value=true}}
  catch(e){if(ticket===generation)error.value=e.message}
  finally{busy.value=false}
}
async function commit(){
  if(busy.value||!props.canEdit||!file.value||!preview.value||preview.value.errors.length)return
  const ticket=generation,request={...params(),file:file.value,dryRun:false};busy.value=true
  try{
    const result=await importSeoBacklinkCsv(request)
    if(ticket!==generation)return
    if(!(await load()))return
    emit('changed');message.value=`已导入 ${result.created} 条待核验外链，跳过 ${result.existing} 条已有记录。`
  }catch(e){if(ticket===generation)error.value=e.message}
  finally{busy.value=false}
}
async function queryIndex(){
  if(busy.value||!props.canEdit||!provider.value?.configured)return
  const ticket=generation,payload={tenant_id:props.tenantId,site_id:props.siteId};busy.value=true;error.value=''
  try{
    const result=await querySeoBacklinkIndex(payload)
    if(ticket!==generation)return
    if(!(await load()))return
    emit('changed')
    message.value=result.state==='completed'?`${result.cached?'使用最近查询结果：':''}收到 ${result.received} 条候选，新入库 ${result.created} 条。请继续核验。`:result.state==='running'?'查询已登记，稍后刷新查看；未重复调用供应商。':result.message||'查询未完成，请检查供应商状态'
  }catch(e){if(ticket===generation)error.value=e.message}
  finally{busy.value=false}
}
watch(()=>[props.tenantId,props.siteId],load);onMounted(load);onBeforeUnmount(()=>generation++)
</script>
<template>
  <section class="suite-panel insights"><header><div><h2>外链数据入口</h2><small>导入已有清单，或从供应商索引获取候选，再用公开页面核验。</small></div><el-button :disabled="busy" @click="load">刷新分析</el-button></header>
    <div class="actions"><input ref="input" type="file" accept=".csv,text/csv" hidden @change="chooseFile"><el-button @click="template">下载 CSV 模板</el-button><el-button v-if="canEdit" :disabled="busy" @click="input?.click()">导入外链清单</el-button><el-button v-if="canEdit" :disabled="busy||!provider?.configured" @click="queryIndex">查询供应商索引（按调用计费）</el-button></div>
    <p>{{provider?.message || '正在读取索引服务状态…'}}</p><p v-if="provider?.last_query">最近查询：{{provider.last_query.attempted_at}} · {{provider.last_query.state==='completed'?'已完成':provider.last_query.state==='failed'?'未完成':'请求已登记'}}</p>
    <el-alert v-if="message" :title="message" type="info" :closable="false"/><el-alert v-if="error" :title="error" type="warning" :closable="false"/>
  </section>
  <section v-if="analysis" class="suite-panel insights"><header><div><h2>外链结构与变化</h2><small>基于当前资产和保留的抓取证据，不等于全网外链总量或搜索引擎权重。</small></div></header>
    <div class="facts"><span>待核验 <b>{{analysis.pending}}</b></span><span>抓取异常 <b>{{analysis.unavailable}}</b></span><span>引荐域名 <b>{{analysis.referring_domains}}</b></span><span>最大来源占比 <b>{{analysis.top_domain_share}}%</b></span></div>
    <el-tabs><el-tab-pane v-for="[key,label] in [['domains','来源域名'],['anchors','锚文本'],['targets','目标页面'],['attributes','链接属性']]" :key="key" :label="label"><el-table :data="analysis[key]" max-height="300" empty-text="暂无数据"><el-table-column prop="name" :label="label" show-overflow-tooltip/><el-table-column prop="count" label="数量" width="100"/></el-table></el-tab-pane><el-tab-pane label="近 30 天变化"><p>新增按首次发现时间统计；丢失按本版本开始记录的状态变化统计，不回推未知历史。</p><el-table :data="[...(analysis.trend||[])].reverse()" max-height="300"><el-table-column prop="date" label="日期"/><el-table-column prop="new" label="首次发现"/><el-table-column prop="lost" label="转为丢失"/></el-table></el-tab-pane></el-tabs>
  </section>
  <el-dialog v-model="dialog" title="外链导入预览" width="800px" :close-on-click-modal="!busy"><template v-if="preview"><p>读取 {{preview.total}} 行，有效 {{preview.items.length}} 条，文件内重复 {{preview.duplicates}} 条，错误 {{preview.errors.length}} 行。错误修复前不会写入。</p><el-table v-if="preview.errors.length" :data="preview.errors" max-height="180"><el-table-column prop="line" label="行号" width="70"/><el-table-column prop="reason" label="问题"/></el-table><el-table :data="preview.items" max-height="280"><el-table-column prop="source_url" label="来源页面" show-overflow-tooltip/><el-table-column prop="target_url" label="目标页面" show-overflow-tooltip/><el-table-column prop="anchor_text" label="锚文本"/></el-table></template><template #footer><el-button :disabled="busy" @click="dialog=false">关闭</el-button><el-button type="primary" :loading="busy" :disabled="!preview?.items.length||!!preview?.errors.length" @click="commit">导入为待核验外链</el-button></template></el-dialog>
</template>
<style scoped>.insights{margin:18px 0}.actions,.facts{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:14px 0}.facts b{font-size:20px;margin-left:8px}p,small{color:#64748b;font-size:13px}</style>
