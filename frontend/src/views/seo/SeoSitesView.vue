<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createSeoSite, deleteSeoSite, fetchSeoSites, updateSeoSite } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { currentSeoSiteId, notifySeoSitesChanged } from './seoSiteContext'

const loading=ref(false),visible=ref(false),sites=ref([]),editing=ref(null)
const router=useRouter()
const deletingId=ref(null)
const form=reactive({name:'',domain:'',status:'active'})
async function load(){if(!currentTenantId.value)return;loading.value=true;try{sites.value=(await fetchSeoSites(currentTenantId.value)).sites||[]}catch(e){ElMessage.error(e.message)}finally{loading.value=false}}
function openAnalytics(row){currentSeoSiteId.value=row.id;router.push('/seo/site/analytics')}
function open(row=null){editing.value=row;Object.assign(form,{name:row?.name||'',domain:row?.domain||'',status:row?.status==='archived'?'paused':(row?.status||'active')});visible.value=true}
async function save(){if(!form.name||!form.domain)return ElMessage.warning('请填写网站名称和域名');try{let created=null;if(editing.value)await updateSeoSite(editing.value.id,currentTenantId.value,form);else created=await createSeoSite({tenant_id:currentTenantId.value,...form});visible.value=false;ElMessage.success('SEO 网站已保存');await load();if(created?.id)currentSeoSiteId.value=created.id;notifySeoSitesChanged()}catch(e){ElMessage.error(e.message)}}
async function remove(row){
  if(deletingId.value!==null)return
  const tenantId=currentTenantId.value,userId=session.user?.id
  const sameScope=()=>tenantId===currentTenantId.value&&userId===session.user?.id
  deletingId.value=row.id
  try{
    await ElMessageBox.confirm(`确定删除网站“${row.name}”（${row.canonical_domain}）？该网站在本系统内的关键词、排名历史、页面、文章、会话、任务及其他关联 SEO 数据将一并永久删除，无法恢复。不会删除外部网站，也不会撤回已发布到外部平台的文章。`, '删除网站及关联数据', {confirmButtonText:'确认永久删除',cancelButtonText:'取消',type:'warning',closeOnClickModal:false})
    if(!sameScope())return
    await deleteSeoSite(row.id,tenantId,row.canonical_domain)
    if(!sameScope())return
    if(currentSeoSiteId.value===row.id)currentSeoSiteId.value=null
    ElMessage.success('网站及关联 SEO 数据已删除')
    await load()
    notifySeoSitesChanged()
  }catch(e){if(e!=='cancel'&&e!=='close'&&sameScope())ElMessage.error(e.message||String(e))}
  finally{deletingId.value=null}
}
watch(currentTenantId,load);onMounted(load)
</script>
<template><div class="asset-page" v-loading="loading"><header><div><h2>SEO 网站管理</h2><p>关键词、排名、页面和内容将逐步按网站隔离。</p></div><el-button v-if="!session.isAdvisorSession" type="primary" @click="open()">添加网站</el-button></header><el-table :data="sites" border><el-table-column prop="name" label="网站名称"/><el-table-column prop="canonical_domain" label="主域名"/><el-table-column label="状态" width="110"><template #default="{row}">{{row.status==='active'?'已启用':'已暂停'}}</template></el-table-column><el-table-column label="操作" width="230"><template #default="{row}"><el-button link type="primary" @click="open(row)">编辑</el-button><el-button link type="primary" @click="openAnalytics(row)">数据源设置</el-button><el-button link type="danger" :disabled="deletingId!==null" :loading="deletingId===row.id" @click="remove(row)">删除</el-button></template></el-table-column></el-table><el-empty v-if="!loading&&!sites.length" description="尚未添加 SEO 网站"/><el-dialog v-model="visible" :title="editing?'编辑网站':'添加网站'" width="520px"><el-form label-width="90px"><el-form-item label="网站名称"><el-input v-model="form.name"/></el-form-item><el-form-item label="网站域名"><el-input v-model="form.domain" placeholder="www.example.com"/></el-form-item><el-form-item v-if="editing" label="状态"><el-select v-model="form.status"><el-option label="启用" value="active"/><el-option label="暂停" value="paused"/></el-select></el-form-item></el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template></el-dialog></div></template>
<style scoped>.asset-page{padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}h2{margin:0 0 7px}p{margin:0;color:#6b7280}</style>
