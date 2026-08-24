<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createSeoSite, deleteSeoSite, fetchSeoSites, updateSeoSite } from '../../api/moduleAssets'
import { currentTenantId } from '../../store/session'

const loading=ref(false),visible=ref(false),sites=ref([]),editing=ref(null)
const form=reactive({name:'',domain:'',status:'active'})
async function load(){if(!currentTenantId.value)return;loading.value=true;try{sites.value=(await fetchSeoSites(currentTenantId.value)).sites||[]}catch(e){ElMessage.error(e.message)}finally{loading.value=false}}
function open(row=null){editing.value=row;Object.assign(form,{name:row?.name||'',domain:row?.domain||'',status:row?.status||'active'});visible.value=true}
async function save(){if(!form.name||!form.domain)return ElMessage.warning('请填写网站名称和域名');try{if(editing.value)await updateSeoSite(editing.value.id,currentTenantId.value,form);else await createSeoSite({tenant_id:currentTenantId.value,...form});visible.value=false;ElMessage.success('SEO 网站已保存');await load()}catch(e){ElMessage.error(e.message)}}
async function remove(row){
  try{
    await ElMessageBox.prompt(`删除后无法恢复。请输入主域名 ${row.canonical_domain} 确认删除。`, '删除 SEO 网站', {confirmButtonText:'删除',cancelButtonText:'取消',inputPattern:new RegExp(`^${row.canonical_domain.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}$`),inputErrorMessage:'输入的主域名不一致',type:'warning'})
    await deleteSeoSite(row.id,currentTenantId.value)
    ElMessage.success('SEO 网站已删除')
    await load()
  }catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message||String(e))}
}
watch(currentTenantId,load);onMounted(load)
</script>
<template><div class="asset-page" v-loading="loading"><header><div><h2>SEO 网站管理</h2><p>关键词、排名、页面和内容将逐步按网站隔离。</p></div><el-button type="primary" @click="open()">添加网站</el-button></header><el-table :data="sites" border><el-table-column prop="name" label="网站名称"/><el-table-column prop="canonical_domain" label="主域名"/><el-table-column prop="status" label="状态" width="110"/><el-table-column label="操作" width="150"><template #default="{row}"><el-button link type="primary" @click="open(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column></el-table><el-empty v-if="!loading&&!sites.length" description="尚未添加 SEO 网站"/><el-dialog v-model="visible" :title="editing?'编辑网站':'添加网站'" width="520px"><el-form label-width="90px"><el-form-item label="网站名称"><el-input v-model="form.name"/></el-form-item><el-form-item label="网站域名"><el-input v-model="form.domain" placeholder="www.example.com"/></el-form-item><el-form-item v-if="editing" label="状态"><el-select v-model="form.status"><el-option label="启用" value="active"/><el-option label="暂停" value="paused"/><el-option label="归档" value="archived"/></el-select></el-form-item></el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template></el-dialog></div></template>
<style scoped>.asset-page{padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}h2{margin:0 0 7px}p{margin:0;color:#6b7280}</style>
