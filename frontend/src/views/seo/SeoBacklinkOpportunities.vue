<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import SeoBacklinkWorkflow from './SeoBacklinkWorkflow.vue'
import { createSeoWorkOrder } from '../../api/seo'
import { fetchSeoBacklinkOpportunities, querySeoBacklinkOpportunities } from '../../api/seo'
const props=defineProps({tenantId:Number,siteId:Number,canEdit:Boolean})
const competitors=ref(''), result=ref(null), provider=ref(null), busy=ref(false), error=ref('')
const filter=ref(''), minPeers=ref(1), workflow=ref(null), creating=ref(false)
const filtered=computed(()=>(result.value?.items||[]).filter(row=>row.source_domain.includes(filter.value.trim())&&row.competitor_count>=minPeers.value))
async function createTask(row){
  if(!props.canEdit||creating.value)return
  const ticket=generation;creating.value=true;error.value=''
  try{
    await createSeoWorkOrder({tenant_id:props.tenantId,site_id:props.siteId,module:'seo',action_type:'backlink_outreach',title:`评估并获取外链：${row.source_domain}`,assignee_role:'seo_operator',params:{source_url:row.evidence[0].source_url,opportunity_request_id:result.value.request_id}})
    if(ticket===generation)await workflow.value?.load()
  }catch(e){if(ticket===generation)error.value=e.message}finally{creating.value=false}
}
let generation=0
async function load(){
  const ticket=++generation;result.value=null;provider.value=null;error.value=''
  if(!props.tenantId||!props.siteId)return
  try{
    const value=await fetchSeoBacklinkOpportunities({tenantId:props.tenantId,siteId:props.siteId})
    if(ticket!==generation)return
    provider.value=value.provider;result.value=value.result
  }catch(e){if(ticket===generation)error.value=e.message}
}
async function run(){
  if(busy.value||!props.canEdit||!provider.value?.configured)return
  const domains=[...new Set(competitors.value.split(/[\s,，]+/).filter(Boolean))]
  if(!domains.length||domains.length>3){error.value='请输入 1–3 个竞品域名';return}
  const ticket=generation;busy.value=true;error.value=''
  try{
    const value=await querySeoBacklinkOpportunities({tenant_id:props.tenantId,site_id:props.siteId,competitors:domains})
    if(ticket===generation)result.value=value
  }catch(e){if(ticket===generation)error.value=e.message}
  finally{busy.value=false}
}
function download(){
  const blob=new Blob([JSON.stringify(result.value,null,2)],{type:'application/json'})
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='外链竞品差距与来源证据.json';a.click();URL.revokeObjectURL(url)
}
watch(()=>[props.tenantId,props.siteId],()=>{competitors.value='';load()})
onMounted(load);onBeforeUnmount(()=>generation++)
</script>
<template>
  <section class="suite-panel opportunities"><header><div><h2>竞品外链与合作机会</h2><small>比较供应商索引样本，发现值得进一步评估的来源网站。</small></div><el-button :disabled="busy" @click="load">刷新已保存结果</el-button></header>
    <el-input v-model="competitors" type="textarea" :rows="2" placeholder="输入 1–3 个竞品域名，每行一个" :disabled="busy"/>
    <p>每站最多 100 条候选，每个来源域名一条。每次分析查询我方及最多 3 个竞品，最多 4 次付费调用；每网站 24 小时一次，失败也计入限额。独立单站查询另有每日 1 次额度。</p>
    <el-button v-if="canEdit" type="primary" :loading="busy" :disabled="busy||!provider?.configured" @click="run">查询并比较（按供应商计费）</el-button>
    <p v-if="!provider?.configured">外链索引尚未启用。配置服务凭据及开关后可查询，未配置时不会产生付费调用。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <template v-if="result"><p>最近分析：{{result.attempted_at}} UTC · {{result.state==='completed'?'完成':result.state==='partial'?'部分查询失败':'已登记，查询中或执行被中断'}} · {{result.provider}}</p>
      <p>{{result.message||'查询过程中会逐站保存结果，请稍后刷新。'}}</p>
      <el-button @click="download">导出分析与来源证据</el-button>
      <el-table :data="Object.entries(result.samples||{}).map(([domain,value])=>({domain,...value}))"><el-table-column prop="domain" label="查询域名"/><el-table-column label="数据状态"><template #default="{row}">{{row.state==='completed'?`返回 ${row.items.length} 条`:'查询失败，未当作零条'}}</template></el-table-column></el-table>
      <el-input v-model="filter" placeholder="筛选来源域名"/><label>至少覆盖竞品数 <el-input-number v-model="minPeers" :min="1" :max="3"/></label>
      <el-table :data="filtered" empty-text="暂无可展示的差距候选，请先确认各站查询状态"><el-table-column prop="source_domain" label="潜在来源"/><el-table-column prop="competitor_count" label="覆盖竞品数" width="120"/><el-table-column label="供应商来源证据" min-width="300"><template #default="{row}"><div v-for="item in row.evidence" :key="item.source_url+item.competitor"><a :href="item.source_url" target="_blank" rel="noopener noreferrer">{{item.competitor}}：{{item.source_url}}</a></div></template></el-table-column><el-table-column v-if="canEdit" label="跟进"><template #default="{row}"><el-button :disabled="creating" @click="createTask(row)">转为 SEO 任务</el-button></template></el-table-column></el-table>
      <p>这些是机会候选，尚未核实合作价值，也不是我方已获得的外链。来源按主机名比较，不合并不同子域；样本中未出现不能证明全网不存在。</p>
    </template>
    <SeoBacklinkWorkflow ref="workflow" :tenant-id="tenantId" :site-id="siteId" :can-edit="canEdit"/>
  </section>
</template>
<style scoped>.opportunities{margin:18px 0;padding:20px}p,small{color:#64748b;font-size:13px}a{overflow-wrap:anywhere;color:#2658d7}.el-alert,.el-table{margin-top:14px}</style>
