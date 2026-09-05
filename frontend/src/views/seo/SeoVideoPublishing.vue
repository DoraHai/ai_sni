<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { seoVideoGet, seoVideoPost } from '../../api/seo'
import { session } from '../../store/session'
const props=defineProps({tenantId:Number,siteId:Number,contents:Array,canEdit:Boolean})
const emit=defineEmits(['authorized'])
const connections=ref([]), publications=ref([]), error=ref(''), busy=ref(false), connectionId=ref(null),contentId=ref(null),title=ref(''),file=ref(null),cover=ref(null),confirm=ref(false)
const recoveryIds=ref({})
const stateLabel=value=>({authorized:'已授权',not_authorized:'未授权',awaiting_consent:'等待用户授权',exchanging:'正在交换授权',refreshing:'正在刷新授权',reauthorize_required:'需要重新授权',uploading:'素材上传中',draft:'素材已就绪',publishing:'已提交，待核实',published:'已发布',manual_required:'需要人工核实'}[value]||'待核实')
let generation=0, uploadRequest=null
const callbackUrl=new URL(window.location.href)
let callbackData=callbackUrl.searchParams.has('state')?{code:callbackUrl.searchParams.get('code'),state:callbackUrl.searchParams.get('state')}:null
if(callbackData){for(const name of ['code','state','error','error_description'])callbackUrl.searchParams.delete(name);history.replaceState(history.state,'',callbackUrl.pathname+callbackUrl.search+callbackUrl.hash)}
const key='seo-video-oauth-v1'
const params=()=>({tenant_id:props.tenantId,site_id:props.siteId})
const scope=()=>`${props.tenantId}:${props.siteId}:${session.user?.id}`
async function load(){
  const ticket=++generation;connections.value=[];publications.value=[];error.value=''
  if(!props.tenantId||!props.siteId)return
  const results=await Promise.allSettled([seoVideoGet('connections',params()),seoVideoGet('publications',params())])
  if(ticket!==generation)return
  if(results[0].status==='fulfilled')connections.value=results[0].value
  if(results[1].status==='fulfilled')publications.value=results[1].value
  error.value=results.filter(r=>r.status==='rejected').map(r=>r.reason.message).join('；')
}
async function operate(fn){
  if(busy.value||!props.canEdit)return
  const captured=scope();busy.value=true;error.value=''
  try{await fn();if(captured===scope())await load()}
  catch(e){if(captured===scope())error.value=e.message}finally{busy.value=false}
}
async function authorize(row){
  await operate(async()=>{
    const captured=scope(),payload={...params(),connection_id:row.connection_id}
    const result=await seoVideoPost('authorize',payload)
    if(captured!==scope())return
    sessionStorage.setItem(key,JSON.stringify({scope:captured,...payload,state:result.state}))
    window.location.assign(result.authorization_url)
  })
}
async function callback(){
  if(!callbackData||!props.tenantId||!props.siteId)return
  const {code,state}=callbackData;callbackData=null
  let pending
  try{pending=JSON.parse(sessionStorage.getItem(key)||'null')}catch{}
  sessionStorage.removeItem(key)
  if(!code||!pending||pending.scope!==scope()||pending.state!==state){error.value='授权回调与当前用户、客户或网站不匹配，请重新授权';emit('authorized');return}
  emit('authorized')
  await operate(()=>seoVideoPost('authorize/complete',{tenant_id:pending.tenant_id,site_id:pending.site_id,connection_id:pending.connection_id,code,state}))
}
function chooseVideo(event){file.value=event.target.files?.[0]||null;uploadRequest=null}
async function upload(){
  const content=props.contents?.find(c=>c.id===contentId.value)
  if(!content||!file.value||!connectionId.value||!title.value.trim()){error.value='请选择账号、已审核内容、MP4 文件并填写标题';return}
  const selected=connections.value.find(c=>c.connection_id===connectionId.value),max=selected?.platform_code==='douyin_video'?48:8
  if(file.value.size>max*1024*1024){error.value=`视频不能超过 ${max} MB`;return}
  uploadRequest??=crypto.randomUUID()
  const data=new FormData()
  for(const [key,value] of Object.entries({...params(),connection_id:connectionId.value,content_id:content.id,source_version:content.version_count||1,request_id:uploadRequest,title:title.value.trim()}))data.append(key,value)
  data.append('file',file.value)
  await operate(()=>seoVideoPost('upload',data))
}
async function publish(row){
  if(!confirm.value){error.value='请先确认下方账号、标题及视频素材，再提交';return}
  const data=new FormData()
  for(const [key,value] of Object.entries({...params(),connection_id:row.connection_id,confirmed:true}))data.append(key,value)
  if(cover.value)data.append('cover',cover.value)
  await operate(()=>seoVideoPost(`publications/${row.id}/publish`,data));confirm.value=false
}
watch(()=>[props.tenantId,props.siteId,session.user?.id],()=>{connectionId.value=null;contentId.value=null;file.value=null;cover.value=null;confirm.value=false;uploadRequest=null;if(callbackData)callback();else load()})
watch(()=>[connectionId.value,contentId.value,title.value],()=>{uploadRequest=null;confirm.value=false})
onMounted(async()=>{if(callbackData)await callback();else await load()})
onBeforeUnmount(()=>generation++)
</script>
<template>
  <section class="suite-panel video-panel"><h2>官方视频发布</h2><p>先在“账号与渠道”创建抖音或快手应用连接，再完成用户授权。仅支持已通过审核的内容资产；视频素材与标题须由运营核对。当前为官方接口集成，真实账号权限与发布效果待集中验收。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-button :disabled="busy" @click="load">刷新账号与任务</el-button>
    <el-table :data="connections"><el-table-column prop="name" label="账号连接"/><el-table-column label="授权状态"><template #default="{row}">{{stateLabel(row.state)}}<small v-if="row.expires_at"> · 到期 {{new Date(Number(row.expires_at)*1000).toLocaleString()}}</small></template></el-table-column><el-table-column v-if="canEdit" label="授权"><template #default="{row}"><el-button :disabled="busy" @click="authorize(row)">用户授权</el-button><el-button :disabled="busy||!row.authorized" @click="operate(()=>seoVideoPost('authorize/refresh',{...params(),connection_id:row.connection_id}))">刷新授权</el-button></template></el-table-column></el-table>
    <template v-if="canEdit"><h3>准备视频素材</h3><el-select v-model="connectionId" placeholder="选择视频账号"><el-option v-for="row in connections" :key="row.connection_id" :value="row.connection_id" :label="row.name"/></el-select><el-select v-model="contentId" placeholder="选择已审核内容"><el-option v-for="row in (contents||[]).filter(c=>['ready','published'].includes(c.status))" :key="row.id" :value="row.id" :label="row.title"/></el-select><el-input v-model="title" maxlength="55" placeholder="视频标题（最多 55 字）"/><label>MP4 视频 <input :key="`${tenantId}:${siteId}`" type="file" accept="video/mp4,.mp4" @change="chooseVideo"/></label><p>抖音单文件最多 48 MB；快手单文件最多 8 MB。上传完成不会自动发布。</p><el-button :disabled="busy" @click="upload">上传并创建视频草稿</el-button>
      <p><label>快手封面（JPG/PNG，最多 3 MB） <input :key="`cover:${tenantId}:${siteId}`" type="file" accept="image/jpeg,image/png" @change="cover=$event.target.files?.[0]||null"/></label></p><el-checkbox v-model="confirm">我已核对本次视频、账号、标题、封面及平台要求，确认提交所选任务</el-checkbox>
    </template>
    <el-table :data="publications"><el-table-column prop="id" label="任务" width="80"/><el-table-column prop="adapted_title" label="视频标题"/><el-table-column label="账号"><template #default="{row}">{{connections.find(c=>c.connection_id===row.connection_id)?.name||row.connection_id}}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{stateLabel(row.status)}}</template></el-table-column><el-table-column prop="external_id" label="作品 ID"/><el-table-column prop="last_error" label="处理说明"/><el-table-column v-if="canEdit" label="操作"><template #default="{row}"><el-button v-if="row.status==='draft'" :disabled="busy||!confirm" @click="publish(row)">提交这条视频</el-button><el-button v-if="row.external_id" :disabled="busy" @click="operate(()=>seoVideoPost(`publications/${row.id}/sync`,{...params(),connection_id:row.connection_id}))">查询审核结果</el-button><a v-if="row.page_url" :href="row.page_url" target="_blank" rel="noopener noreferrer">查看作品</a></template></el-table-column></el-table>
    <div v-for="row in publications.filter(p=>!p.external_id&&['publishing','manual_required'].includes(p.status))" :key="row.id"><template v-if="canEdit"><p>任务 #{{row.id}}：若已在平台找到作品，可填作品 ID；系统先查询当前授权账号并核对标题，不会重新发布。</p><el-input v-model="recoveryIds[row.id]" maxlength="255" placeholder="从官方后台复制作品 ID"/><el-button :disabled="busy||!recoveryIds[row.id]?.trim()" @click="operate(()=>seoVideoPost(`publications/${row.id}/recover`,{...params(),connection_id:row.connection_id,item_id:recoveryIds[row.id].trim()}))">核实并恢复作品关联</el-button></template></div>
    <p>提交成功仅表示平台受理，需查询审核结果。快手播放地址不作为公开作品链接或外链；异常或中断的发布任务先去平台核实，系统不会自动重复发布。</p>
  </section>
</template>
<style scoped>.video-panel{padding:20px}p,small{color:#64748b;font-size:13px}.el-input,.el-table{margin:12px 0}.el-select{margin-right:10px}</style>
