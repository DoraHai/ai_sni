import test from 'node:test';
import assert from 'node:assert/strict';
import {createDistributionClient,distributionContentDigest} from './js/distribution-client.mjs';
import {createAdvisorDistributionPanel,seoOfflineEntryMarkup} from './js/distribution-panel.mjs';
const row={module:'seo',tenant_id:1,scope_id:1,tenant_name:'诺德',scope_name:'诺德网站'};
const session=()=>({token:'fixture',authRevision:1,user:{id:3,tenant_id:1,permissions:{'seo.site':'edit','seo.content':'edit'}},logout(){this.token='';}});

test('advisor distribution is local text and offline links, without service or session initialization',async()=>{
 const s={...session(),isAdvisorSession:true,tenantId:1};let rows=[row,{...row,scope_id:6},{...row,tenant_id:2}];
 const panel=createAdvisorDistributionPanel({session:s,browser:{},scopesForAdvisor:()=>rows,
   fetchImpl:()=>assert.fail('Advisor must not request distribution'),subscribeSession:()=>assert.fail('No distribution client subscription')});
 assert.equal(panel.html(),'');
 await panel.initialize(['seo','geo']);
 assert.match(panel.html(),/审核通过的稿件由多号通或人工发布，发完在分发记录里回填链接或导入回执。/);
 for(const site of [1,6])assert.match(panel.html(),new RegExp(`tenant_id=1&amp;site_id=${site}`));
 assert.doesNotMatch(panel.html(),/tenant_id=2|data-distribution=|<select|<input|会话或权限已变化|本页暂无已分配项目/);
 panel.click({target:{closest:()=>({dataset:{distribution:'refresh'}})}});
 panel.change({target:{name:'distribution_scope',value:'seo:1:6'}});
 panel.filterModule('geo');assert.doesNotMatch(panel.html(),/导出发布单/);
 panel.filterModule('seo');rows=[];
 assert.match(panel.html(),/这个客户目前没有待发布的稿件。/);
 assert.match(panel.html(),/<a href="\/seo\/distribution">导出发布单 \/ 导入回执/);
 s.user.permissions['seo.content']='view';assert.doesNotMatch(panel.html(),/href=/);
 panel.invalidate();assert.equal(panel.html(),'');panel.dispose();
});

for(const tenantId of [null,1])test(`non-advisor distribution keeps discovery and original empty text (${tenantId===null?'admin':'customer'})`,async()=>{
 const s={...session(),isAdvisorSession:false};s.user.tenant_id=tenantId;const calls=[];
 const panel=createAdvisorDistributionPanel({session:s,browser:{},fetchImpl:async path=>{
   calls.push(path);return Response.json({schema:1,module:'seo',items:[]});
 }});
 try{
   await panel.initialize(['seo']);
   assert.deepEqual(calls,['/api/distribution/v1/bound-scopes?module=seo']);
   assert.match(panel.html(),/本页暂无已分配项目。可读取其他任务页后选择项目。/);
   assert.doesNotMatch(panel.html(),/这个客户目前没有待发布的稿件/);
 }finally{panel.dispose();}
});

test('reviewing a draft shows the existing warning before unchecked publication authorizations without submitting work',async()=>{
 const content={version:'rev1',title:'审核稿',body:'正文',assets:[]},calls=[];
 const source={schema:1,module:'seo',tenant_id:1,scope_id:1,variant_id:1,platform:'wechat-article',source_revision:'rev1',content,content_digest:await distributionContentDigest(content)};
 const scope={schema:1,...row,project:{module:'seo',tenant_id:1,scope_id:1,state:'running',revision:3,owner_user_id:3},bindings:[{id:'12345678-1234-4567-8123-123456789abc',device_id:'device1',account_id:'account1',platform:'wechat-article',active:true,device_label:'测试设备',last_seen_at:null}],as_of:1,capabilities:{automated_publish:false,human_handoff:true,real_channel_verified:false}};
 let changed=()=>{};
 const panel=createAdvisorDistributionPanel({session:session(),browser:{},onChange:()=>changed(),fetchImpl:async(path,options)=>{
   calls.push({path,method:options.method});
   if(path.includes('/bound-scopes?'))return Response.json({schema:1,module:'seo',items:[row]});
   if(path.includes('/scope?'))return Response.json(scope);
   if(path.includes('/sources?'))return Response.json({...source,items:[{variant_id:1,source_revision:'rev1',platform:'wechat-article',title:'审核稿'}]});
   if(path.includes('/source?'))return Response.json(source);
   return Response.json({detail:{code:'not_integrated'}},{status:404});
 }});
 try{
   await panel.initialize(['seo']);
   assert.doesNotMatch(panel.html(),/只看不点/);
   const completed=new Promise(resolve=>{changed=()=>{if(panel.html().includes('name="distribution_reviewed"'))resolve();};});
   panel.click({target:{closest:()=>({dataset:{distribution:'preview'},disabled:false})}});
   await completed;
   const html=panel.html(),warning='这三步会把稿件交出去做真实发布。操作前请先得到负责人同意；在未得到同意前，只看不点。';
   assert(html.includes(`<p class="alert" role="alert">${warning}</p>`));
   assert(html.indexOf(warning)<html.indexOf('name="distribution_reviewed"'));
   for(const name of ['distribution_reviewed','distribution_manual'])assert.match(html,new RegExp(`name="${name}"(?![^>]*checked)`));
   for(const action of ['preflight','handoff','publish'])assert.match(html,new RegExp(`data-distribution="${action}" disabled`));
   assert(calls.every(call=>call.method==='GET'));
   panel.invalidate();assert.doesNotMatch(panel.html(),/只看不点/);
 }finally{panel.dispose();}
});
test('bound projects remain selectable with no onsite tasks or automation projects',async()=>{
 const calls=[],s=session(),scope={schema:1,...row,project:{module:'seo',tenant_id:1,scope_id:1,state:'paused',revision:3,owner_user_id:3},bindings:[],as_of:1,capabilities:{automated_publish:false,human_handoff:true,real_channel_verified:false}};
 const panel=createAdvisorDistributionPanel({session:s,browser:{},scopesForAdvisor:()=>[],fetchImpl:async path=>{calls.push(path);return Response.json(path.includes('/bound-scopes?')?{schema:1,module:'seo',items:[row]}:path.includes('/scope?')?scope:{detail:{code:'not_integrated'}},{status:path.includes('/bound-scopes?')||path.includes('/scope?')?200:404});}});
 await panel.initialize(['seo']);assert.match(panel.html(),/诺德网站/);assert.match(panel.html(),/暂停/);
 assert.match(panel.html(),/\/seo\/distribution\?tenant_id=1&amp;site_id=1/);
 assert(calls.includes('/api/distribution/v1/scope?module=seo&tenant_id=1&scope_id=1'));panel.invalidate();assert.doesNotMatch(panel.html(),/诺德网站/);panel.dispose();
});

test('SEO offline entry follows the selected project, edit permission and enabled modules',()=>{
 const s=session(),scope={module:'seo',tenant_id:1,scope_id:6};
 assert.match(seoOfflineEntryMarkup(s,['seo'],scope),/tenant_id=1&amp;site_id=6/);
 assert.match(seoOfflineEntryMarkup(s,['seo'],scope),/导出发布单 \/ 导入回执（SEO 分发平台）/);
 assert.match(seoOfflineEntryMarkup(s,['seo'],{...scope,scope_id:9}),/site_id=9/);
 assert.equal(seoOfflineEntryMarkup(s,[],scope),'');
 assert.equal(seoOfflineEntryMarkup(s,['seo'],{...scope,module:'geo'}),'');
 assert.equal(seoOfflineEntryMarkup(s,['seo'],{...scope,tenant_id:2}),'');
 assert.equal(seoOfflineEntryMarkup(s,['seo'],null),'');
 for(const invalid of [null,0,-1,'6','6&tenant_id=2',Number.MAX_SAFE_INTEGER+1])
   assert.doesNotMatch(seoOfflineEntryMarkup(s,['seo'],{...scope,scope_id:invalid}),/href=/);
 s.user.permissions['seo.content']='view';assert.equal(seoOfflineEntryMarkup(s,['seo'],scope),'');
 delete s.user.permissions['seo.content'];assert.equal(seoOfflineEntryMarkup(s,['seo'],scope),'');
});
test('SEO offline entry stays in the current tab to retain transient login',()=>{
 const markup=seoOfflineEntryMarkup(session(),['seo'],{module:'seo',tenant_id:1,scope_id:6});
 assert.match(markup,/<a href="\/seo\/distribution\?tenant_id=1&amp;site_id=6"/);
 assert.doesNotMatch(markup,/\btarget\s*=/i);
 assert.doesNotMatch(markup,/\brel\s*=/i);
});
test('advisor SEO entry follows the selected tenant while leaving the default unchanged',()=>{
 const s={...session(),isAdvisorSession:true,tenantId:2},scope={module:'seo',tenant_id:2,scope_id:6};
 assert.match(seoOfflineEntryMarkup(s,['seo'],scope),/tenant_id=2&amp;site_id=6/);
 assert.equal(s.user.tenant_id,1);
 assert.equal(seoOfflineEntryMarkup(s,['seo'],{...scope,tenant_id:1}),'');
 s.tenantId=null;assert.equal(seoOfflineEntryMarkup(s,['seo'],scope),'');
});

test('discovery rejects cross-tenant rows and late results after account switches',async()=>{
 const s=session();let data={schema:1,module:'seo',items:[{...row,tenant_id:2}]};
 const client=createDistributionClient({session:s,fetchImpl:async()=>Response.json(data)});
 await assert.rejects(()=>client.boundScopes('seo'),/CONTRACT_MISMATCH/);client.dispose();
 let release;const held=new Promise(r=>release=r);
 const pendingClient=createDistributionClient({session:s,fetchImpl:async()=>{await held;return Response.json({schema:1,module:'seo',items:[row]});}});
 const pending=pendingClient.boundScopes('seo');s.user={...s.user,id:4};s.authRevision++;release();await assert.rejects(()=>pending,/CONTEXT_CHANGED/);pendingClient.dispose();
});
