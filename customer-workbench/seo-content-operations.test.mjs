import test from 'node:test';import assert from 'node:assert/strict';
import {createSeoWorkflowClient} from './js/seo-workflow-client.mjs';
function fixture(){
  const context={connected:true,userId:7,tenantId:1,siteId:9,revision:1},calls=[];
  const asset={id:88,tenant_id:1,site_id:9,title:'标题',outline:'提纲',draft:'旧底稿',humanized_content:'当前正文',keyword_ids:[21],version_count:3,status:'drafting'};
  const data={content:{...asset,body:asset.humanized_content,payload_hash:'a'.repeat(64)},confirmation:{status:'stale',approval_is_publication:false},allowed_actions:{edit_content:true,submit_review:true},permission_basis:{active_site_advisor_assignment:true}};
  let response=null;
  const client=createSeoWorkflowClient({getContext:()=>context,transport:async(path,options)=>{
    const body=options.body&&JSON.parse(options.body);calls.push({path,...options,body});if(response)return response(path,options);
    let payload=path.includes('/delivery?')?data:{items:[asset],total:1,page:1,page_size:50};
    if(options.method==='PATCH')payload={...asset,...body,version_count:4};
    if(path.includes('/submit-review?'))payload={...asset,status:'review'};
    return {ok:true,status:200,json:async()=>structuredClone(payload)};
  }});
  return {client,context,calls,asset,data,setResponse:r=>response=r};
}
test('exact read preserves humanized source; edit and submit bind the server version',async()=>{
  const f=fixture();await f.client.delivery(88);const edit=await f.client.editor(88);assert.equal(edit.field,'humanized_content');assert.match(f.calls[1].path,/content_id=88/);
  await f.client.saveContent(88,{title:'新标题',outline:'新提纲',body:'新正文'});assert.deepEqual(f.calls[2].body,{version_count:3,title:'新标题',outline:'新提纲',humanized_content:'新正文'});await assert.rejects(f.client.submitReview(88),/DELIVERY_REQUIRED/);
  await f.client.delivery(88);await f.client.submitReview(88);assert.deepEqual(f.calls.at(-1).body,{version_count:3,note:null});
});
test('denied role, protected state, changed raw version and foreign scope prevent edits',async()=>{
  for(const mutate of [f=>f.data.permission_basis.active_site_advisor_assignment=false,f=>f.data.allowed_actions.edit_content='true',f=>f.data.content.status='ready',f=>f.asset.version_count=4,f=>f.asset.site_id=19,f=>f.asset.humanized_content='different']){
    const f=fixture();mutate(f);await f.client.delivery(88);await assert.rejects(f.client.editor(88));assert(f.calls.every(v=>v.method==='GET'));
  }
});
test('unknown result and 409/403/503 invalidate editor and never replay writes',async()=>{
  for(const status of [0,409,403,503]){
    const f=fixture();await f.client.delivery(88);await f.client.editor(88);f.setResponse(()=>{if(!status)throw Error('lost response');return {ok:false,status,json:async()=>({detail:'rejected'})};});
    await assert.rejects(f.client.saveContent(88,{title:'保存',outline:'',body:'正文'}),e=>status?e.status===status:e.code==='WRITE_OUTCOME_UNKNOWN');
    await assert.rejects(f.client.saveContent(88,{title:'再试',outline:'',body:'正文'}),/DELIVERY_REQUIRED/);assert.equal(f.calls.filter(v=>v.method==='PATCH').length,1);
  }
});
test('late exact read is discarded on customer switch',async()=>{
  const f=fixture();await f.client.delivery(88);f.setResponse(()=>({ok:true,status:200,json:async()=>{f.context.tenantId=2;return {items:[f.asset],total:1};}}));await assert.rejects(f.client.editor(88),/CONTEXT_CHANGED/);assert(f.calls.every(v=>v.method==='GET'));
});
test('publication reads verify ownership and never expose a completion write method',async()=>{
  const f=fixture();await f.client.delivery(88);f.setResponse(()=>({ok:true,status:200,json:async()=>({items:[{id:91,tenant_id:2,content_id:88,source_version:3}]})}));await assert.rejects(f.client.publications(88),/CONTRACT_MISMATCH/);await assert.rejects(f.client.publicationAttempts(88,91),/PUBLICATIONS_REQUIRED/);assert.equal(f.client.completePublication,undefined);
});
