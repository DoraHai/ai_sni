<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { fetchSeoWorkOrders, updateSeoWorkOrder, fetchSeoBacklinkOutcomes, saveSeoReferral } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean})
const tasks=ref([]), outcomes=ref(null), error=ref(''), busy=ref(false), notes=ref({}), report=ref(null)
let generation=0
const params=()=>({tenant_id:props.tenantId,site_id:props.siteId})
async function load(){
  const ticket=++generation;tasks.value=[];outcomes.value=null;error.value='';report.value=null;notes.value={}
  if(!props.tenantId||!props.siteId)return
  const results=await Promise.allSettled([fetchSeoWorkOrders({...params(),limit:100}),fetchSeoBacklinkOutcomes(params())])
  if(ticket!==generation)return
  if(results[0].status==='fulfilled')tasks.value=results[0].value.filter(t=>t.action_type==='backlink_outreach')
  if(results[1].status==='fulfilled')outcomes.value=results[1].value
  error.value=results.filter(r=>r.status==='rejected').map(r=>r.reason.message).join('；')
}
async function update(task,status){
  if(!props.canEdit||busy.value)return
  const ticket=generation, note=notes.value[task.id]?.trim();busy.value=true;error.value=''
  try{await updateSeoWorkOrder(task.id,{...params(),...(status?{status}:{}),...(note?{note}:{})});if(ticket===generation)await load()}
  catch(e){if(ticket===generation)error.value=e.message}finally{busy.value=false}
}
async function saveReport(){
  if(!props.canEdit||busy.value||!report.value)return
  const ticket=generation;busy.value=true;error.value=''
  try{await saveSeoReferral({...params(),...report.value});if(ticket===generation)await load()}
  catch(e){if(ticket===generation)error.value=e.message}finally{busy.value=false}
}
function editReport(row){report.value={source_url:row.source_url,visits:row.visits??0,conversions:row.conversions??null,date_from:'',date_to:'',source:''}}
watch(()=>[props.tenantId,props.siteId],load);onMounted(load);onBeforeUnmount(()=>generation++)
defineExpose({load})
</script>
<template>
  <section><h3>外链跟进任务</h3><el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <p>跟进和合作沟通由运营执行；完成时系统检查任务创建后的新外链抓取证据及指标增长。展示最近 100 条 SEO 任务中的外链任务。</p>
    <el-table :data="tasks"><el-table-column prop="title" label="任务"/><el-table-column label="状态" width="110"><template #default="{row}">{{({open:"待处理",in_progress:"进行中",done:"已完成",cancelled:"已取消"})[row.status]}}</template></el-table-column><el-table-column label="跟进记录"><template #default="{row}"><p v-for="(note,index) in row.params.followups||[]" :key="index">{{note.at}} · {{note.note}}</p><span v-if="row.completion_evidence">已核实外链 #{{row.completion_evidence.source.backlink_id}}，指标增加 {{row.completion_evidence.change_abs}}</span></template></el-table-column>
      <el-table-column v-if="canEdit" label="操作" min-width="260"><template #default="{row}"><template v-if="!['done','cancelled'].includes(row.status)"><el-input v-model="notes[row.id]" maxlength="2000" placeholder="记录评估、沟通和后续行动"/><el-button :disabled="busy||!notes[row.id]?.trim()" @click="update(row)">保存跟进</el-button><el-button :disabled="busy" @click="update(row,'in_progress')">开始</el-button><el-button :disabled="busy" @click="update(row,'done')">核实并完成</el-button><el-button :disabled="busy" @click="update(row,'cancelled')">取消</el-button></template></template></el-table-column>
    </el-table>
    <template v-if="outcomes"><h3>分发与外链效果</h3><p>{{outcomes.note}}</p>
      <el-table :data="outcomes.items"><el-table-column prop="platform_name" label="平台"/><el-table-column label="发布地址" min-width="200"><template #default="{row}"><a :href="row.source_url" target="_blank" rel="noopener noreferrer">{{row.source_url}}</a></template></el-table-column><el-table-column prop="verified_backlinks" label="已核实外链"/><el-table-column label="引荐访问 / 转化"><template #default="{row}">{{row.visits??'未知'}} / {{row.conversions??'未知'}}<small v-if="row.observation"> · 用户报表 {{row.observation.source}}（{{row.observation.date_from}} 至 {{row.observation.date_to}}）</small></template></el-table-column><el-table-column v-if="canEdit" label="统计"><template #default="{row}"><el-button @click="editReport(row)">录入报表</el-button></template></el-table-column></el-table>
      <div v-if="report"><p>录入分析平台报表；保存会替换该来源上一次统计期间，数据标记为用户提供。</p><el-input v-model="report.source" maxlength="200" placeholder="报表来源，如百度统计导出"/><el-date-picker v-model="report.date_from" value-format="YYYY-MM-DD" placeholder="开始日期"/><el-date-picker v-model="report.date_to" value-format="YYYY-MM-DD" placeholder="结束日期"/><label>访问 <el-input-number v-model="report.visits" :min="0"/></label><label>转化 <el-input-number v-model="report.conversions" :min="0"/></label><el-button :disabled="busy" @click="saveReport">保存统计</el-button></div>
      <h3>外部数据源与调用预算</h3><p>{{outcomes.usage.provider.configured?'DataForSEO 已配置':'DataForSEO 未配置'}} · {{outcomes.usage.note}}</p><el-table :data="outcomes.usage.quotas"><el-table-column label="查询类型"><template #default="{row}">{{row.kind==='backlink_index'?'单站索引':'竞品比较'}}</template></el-table-column><el-table-column prop="limit_calls_24h" label="24 小时调用上限"/><el-table-column prop="reserved_calls" label="已预留"/><el-table-column prop="next_available_at" label="下次可查询时间"/></el-table>
    </template>
  </section>
</template>
<style scoped>section{margin-top:24px}p,small{font-size:12px;color:#64748b}a{overflow-wrap:anywhere}.el-input{margin:8px 0}</style>
