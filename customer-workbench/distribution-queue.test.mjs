import test from 'node:test';
import assert from 'node:assert/strict';
import {createDistributionClient,validateChannelCapability,validateDistributionQueue} from './js/distribution-client.mjs';
const scope={module:'seo',tenant_id:4,scope_id:19};
const binding='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',request='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const session=()=>({token:'synthetic',user:{id:7,tenant_id:null,permissions:{'seo.content':'edit','seo.site':'edit'}},authRevision:1,logout(){}});
const cap=()=>({platform:'wechat-article',content_type:'article',label:'公众号文章',mode:'manual',enabled:true,revision:1,
  executable:false,automated_publish:false,real_channel_verified:false,automatic_steps:['队列登记'],manual_steps:['正式发布'],reason:'REAL_CHANNEL_NOT_ACCEPTED'});
const data=()=>({schema:1,...scope,completed_draft_events_connected:false,items:[{id:request,binding_id:binding,variant_id:11,draft_version:'draft_1',source_revision:null,
  platform:'wechat-article',state:'awaiting-review',reason:'REVIEW_REQUIRED',created_at:1,checked_at:2,next_allowed_at:null}],scans:[]});
test('capability ceiling rejects forged automation and unsafe execution claims',()=>{
  assert.equal(validateChannelCapability(cap()).mode,'manual');
  for(const patch of [{mode:'full-auto'},{executable:true},{automated_publish:true},{real_channel_verified:true},{reason:'SUCCESS'}])
    assert.throws(()=>validateChannelCapability({...cap(),...patch}),{code:'CONTRACT_MISMATCH'});
});
test('pending queue keeps draft version independent of source approval and rejects foreign scope',()=>{
  assert.equal(validateDistributionQueue(data(),scope).items[0].source_revision,null);
  for(const value of [{...data(),tenant_id:5},{...data(),completed_draft_events_connected:true},{...data(),items:[{...data().items[0],state:'published'}]}])
    assert.throws(()=>validateDistributionQueue(value,scope),{code:'CONTRACT_MISMATCH'});
});
test('channel selection is scoped and sends no body or execution grant',async()=>{
  const calls=[];const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{
    calls.push({path,body:options.body&&JSON.parse(options.body)});
    return {ok:true,status:200,json:async()=>({schema:1,selection:{binding_id:binding,enabled:true,revision:1}})};
  }});
  await client.selectChannel(scope,{binding_id:binding,content_type:'article',enabled:true,expected_revision:0,request_id:request});
  assert.equal(calls[0].path,'/api/distribution/v1/project-channel');assert.equal(calls[0].body.tenant_id,4);
  assert(!('confirm_manual_publication' in calls[0].body));assert(!('content' in calls[0].body));client.dispose();
});
test('queue read cannot write and revoked permission invalidates current data',async()=>{
  let denied=false;const calls=[];const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{
    calls.push({path,method:options.method});return denied?{ok:false,status:403}:{ok:true,status:200,json:async()=>data()};
  }});
  assert.equal((await client.queue(scope)).items.length,1);denied=true;
  await assert.rejects(client.queue(scope),{code:'PERMISSION_DENIED'});
  assert(calls.every(c=>c.method==='GET'));client.dispose();
});
test('uncertain channel write is never retried or reported as enabled',async()=>{
  let calls=0;const client=createDistributionClient({session:session(),fetchImpl:async()=>{calls++;throw Error('lost response');}});
  await assert.rejects(client.selectChannel(scope,{binding_id:binding,content_type:'article',enabled:true,expected_revision:0,request_id:request}),{code:'WRITE_OUTCOME_UNKNOWN'});
  assert.equal(calls,1);client.dispose();
});
