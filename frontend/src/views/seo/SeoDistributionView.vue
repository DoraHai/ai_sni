<script setup>
import { computed,onMounted,reactive,ref,watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchSeoContentAssets,updateSeoContentAsset } from '../../api/seo'
import { currentTenantId,session } from '../../store/session'

const loading=ref(false),saving=ref(false),error=ref(''),dialog=ref(false),items=ref([]),query=ref(''),filter=ref('全部')
const form=reactive({content_id:null,page_url:'',status:'published'})
const canEdit=computed(()=>!session.isLoggedIn||session.canEdit('seo.content'))
const published=computed(()=>items.value.filter(item=>item.status==='published'&&item.page_url))
const pending=computed(()=>items.value.filter(item=>item.status!=='published'||!item.page_url))
const host=value=>{if(!value)return'';try{return new URL(value).hostname.replace(/^www\./,'')}catch{return''}}
const channels=computed(()=>{const groups=new Map();published.value.forEach(item=>{const domain=host(item.page_url);if(!domain)return;const group=groups.get(domain)||{id:domain,name:domain,count:0,last:'',items:[]};group.count+=1;group.items.push(item);const stamp=item.published_at||item.updated_at||'';if(stamp>group.last)group.last=stamp;groups.set(domain,group)});return [...groups.values()].sort((a,b)=>b.count-a.count)})
const visibleChannels=computed(()=>channels.value.filter(item=>(!query.value||item.name.toLowerCase().includes(query.value.toLowerCase()))&&(filter.value==='全部'||filter.value==='已连接')))
const coverage=computed(()=>items.value.length?Math.round(published.value.length/items.value.length*100):0)
const date=value=>value?new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'尚未同步'
async function load(){if(!currentTenantId.value){error.value='请先选择客户';items.value=[];return}loading.value=true;try{items.value=(await fetchSeoContentAssets({tenantId:currentTenantId.value})).items;error.value=''}catch(e){error.value=e.message}finally{loading.value=false}}
function open(item=null){Object.assign(form,{content_id:item?.id||null,page_url:item?.page_url||'',status:'published'});dialog.value=true}
async function save(){if(!form.content_id)return ElMessage.warning('请选择内容资产');if(!form.page_url.trim())return ElMessage.warning('请填写完整发布地址');try{new URL(form.page_url.trim())}catch{return ElMessage.warning('发布地址格式不正确')}saving.value=true;try{await updateSeoContentAsset({contentId:form.content_id,tenantId:currentTenantId.value,payload:{page_url:form.page_url.trim(),status:form.status,published_at:form.status==='published'?new Date().toISOString():null}});dialog.value=false;ElMessage.success('发布记录已更新');await load()}catch(e){ElMessage.error(e.message)}finally{saving.value=false}}
watch(currentTenantId,load);onMounted(load)
</script>

<template>
  <div class="distribution-page" v-loading="loading">
    <section class="distribution-hero">
      <div><span>CONTENT DISTRIBUTION</span><h1>分发平台</h1><p>维护内容的真实发布渠道和落地地址，统一追踪待分发、已发布与渠道覆盖状态。</p></div>
      <button v-if="canEdit" class="btn primary" @click="open()">＋ 登记发布</button>
    </section>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <section class="channel-summary">
      <div><span>内容资产</span><strong>{{items.length}}</strong><small>当前客户全部内容</small></div>
      <div><span>已发布</span><strong>{{published.length}}</strong><small>已回填有效地址</small></div>
      <div><span>待分发</span><strong>{{pending.length}}</strong><small>尚未完成发布闭环</small></div>
      <div><span>发布覆盖率</span><strong>{{coverage}}%</strong><small>{{channels.length}} 个真实渠道域名</small></div>
    </section>
    <section class="channel-toolbar">
      <button v-for="name in ['全部','已连接','未连接']" :key="name" class="btn" :class="{active:filter===name}" @click="filter=name">{{name}}</button>
      <input v-model="query" class="search" placeholder="搜索平台或域名">
      <button class="btn" @click="load">检查发布状态</button>
    </section>
    <div class="channel-section-title"><h2>已连接平台</h2><span>{{channels.length}} 个渠道来自真实发布记录</span></div>
    <section v-if="visibleChannels.length" class="channel-grid">
      <article v-for="item in visibleChannels" :key="item.id" class="channel-card">
        <div class="channel-card-head"><span class="channel-logo">{{item.name.slice(0,1).toUpperCase()}}</span><div class="channel-name"><strong>{{item.name}}</strong><small>自有或内容渠道</small></div><span class="connection-state">已连接</span></div>
        <div class="channel-card-body"><dl class="channel-meta"><dt>发布内容</dt><dd>{{item.count}} 篇</dd><dt>接入方式</dt><dd>发布地址回填</dd><dt>最近同步</dt><dd>{{date(item.last)}}</dd></dl><div class="channel-capabilities"><span>原创</span><span>文章改写</span><span>链接回流</span></div><div class="channel-card-actions"><button @click="open(item.items[0])">查看并更新</button><button @click="load">刷新记录</button><span class="mini-switch on" aria-label="已启用"/></div></div>
      </article>
    </section>
    <div v-else-if="filter!=='未连接'" class="channel-empty"><b>暂无已连接平台</b><span>为已完成内容登记发布地址后，这里会自动按域名生成渠道卡片。</span><button v-if="canEdit" class="btn primary" @click="open()">登记第一条发布记录</button></div>
    <template v-if="filter==='全部'||filter==='未连接'">
      <div class="channel-section-title"><h2>待接入</h2><span>不展示原型中的演示账号</span></div>
      <div class="channel-empty compact"><b>尚未配置平台账号接入</b><span>当前版本支持真实发布链接回填；平台授权、自动发布与连接测试将在接口接通后显示。</span></div>
    </template>
    <div class="channel-section-title"><h2>待分发内容</h2><span>{{pending.length}} 篇需要处理</span></div>
    <section class="pending-panel">
      <div v-for="item in pending.slice(0,8)" :key="item.id" class="pending-row"><div><strong>{{item.title}}</strong><small>{{item.content_type}} · {{item.author||'未分配负责人'}}</small></div><span>{{item.status}}</span><button v-if="canEdit" @click="open(item)">登记发布 →</button></div>
      <div v-if="!pending.length" class="channel-empty compact"><b>暂无待分发内容</b><span>所有内容都已形成发布记录。</span></div>
    </section>
    <el-dialog v-model="dialog" title="登记内容发布" width="620px"><el-form label-position="top"><el-form-item label="内容资产"><el-select v-model="form.content_id" filterable><el-option v-for="item in items" :key="item.id" :label="item.title" :value="item.id"/></el-select></el-form-item><el-form-item label="发布地址"><el-input v-model="form.page_url" placeholder="https://example.com/article"/></el-form-item><el-form-item label="发布状态"><el-select v-model="form.status"><el-option label="已发布" value="published"/><el-option label="人工审核" value="review"/></el-select></el-form-item></el-form><template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template></el-dialog>
  </div>
</template>

<style>@import url('../../../public/deal-sniper-prototype/seo/assets/seo-content-v1.css');</style>
<style scoped>
.distribution-page{min-height:100%;padding:22px 26px 36px;background:#f5f7fb;color:#1f2735}.distribution-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:16px;padding:24px 28px;border:1px solid #e0e4ea;border-radius:10px;background:#fff}.distribution-hero span{color:#2563eb;font-size:10px;font-weight:800;letter-spacing:1.5px}.distribution-hero h1{margin:6px 0 5px;font-size:26px}.distribution-hero p{margin:0;color:#737c8b;font-size:12px}.btn{padding:7px 11px;border:1px solid #dce1e8;border-radius:6px;background:#fff;color:#596270;font-size:11px;font-weight:650;cursor:pointer}.btn.primary{border-color:#2563eb;background:#2563eb;color:#fff}.btn.active{border-color:#a9c0f2;background:#eef4ff;color:#1d4ed8}.search{min-width:240px;margin-left:auto;padding:8px 11px;border:1px solid #dce1e8;border-radius:6px;background:#fff;font-size:11px;outline:none}.channel-logo{background:#2563eb}.mini-switch.on{display:inline-block;background:#2563eb}.mini-switch.on:after{left:17px}.channel-empty{display:flex;min-height:160px;align-items:center;justify-content:center;flex-direction:column;gap:7px;border:1px dashed #d8dde6;border-radius:8px;background:#fff;color:#89919e;text-align:center}.channel-empty b{color:#596270;font-size:13px}.channel-empty span{max-width:560px;font-size:10.5px;line-height:1.7}.channel-empty.compact{min-height:100px}.pending-panel{overflow:hidden;border:1px solid #dde2e9;border-radius:8px;background:#fff}.pending-row{display:grid;grid-template-columns:minmax(0,1fr) 90px 100px;align-items:center;gap:12px;padding:12px 14px;border-bottom:1px solid #edf0f3}.pending-row:last-child{border:0}.pending-row strong,.pending-row small{display:block}.pending-row strong{font-size:12px}.pending-row small{margin-top:3px;color:#89919e;font-size:10px}.pending-row>span{color:#9a6211;font-size:10px}.pending-row button{border:0;background:none;color:#1d4ed8;font-size:10.5px;font-weight:700;cursor:pointer}.el-select{width:100%}@media(max-width:1000px){.channel-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){.distribution-page{padding:14px}.channel-summary,.channel-grid{grid-template-columns:1fr}.channel-toolbar{flex-wrap:wrap}.search{width:100%;margin-left:0}.pending-row{grid-template-columns:1fr auto}}
</style>
