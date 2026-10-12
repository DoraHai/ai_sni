import test from 'node:test';
import assert from 'node:assert/strict';
import {createDistributionClient,distributionContentDigest,validateDistributionScope,validateDistributionTasks,safeDistributionUrl,validateDistributionSchedule,validateDistributionPublication,validateDistributionMonitor} from './js/distribution-client.mjs';
import {distributionTaskMarkup,createAdvisorDistributionPanel,distributionMediaHref} from './js/distribution-panel.mjs';
const scope={module:'seo',tenant_id:4,scope_id:19};
const taskId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',bindingId='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const requestId='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const content={version:'seo_variant_11_r1',title:'合成稿 😀',body:'合成正文。',assets:[]};
const source={schema:1,...scope,variant_id:11,source_revision:content.version,content,platform:'wechat-article',content_digest:await distributionContentDigest(content)};
const session=()=>({token:'synthetic-token',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit'}},authRevision:1,modules:[],logout(){this.token=null;}});
const snapshot=()=>({schema:1,...scope,project:{...scope,state:'paused',revision:0,owner_user_id:null},bindings:[{
  id:bindingId,device_id:taskId,account_id:'synthetic-local-account',platform:'wechat-article',active:true,device_label:'合成设备',last_seen_at:null}],
  capabilities:{automated_publish:false,human_handoff:true,real_channel_verified:false},as_of:Date.now()});
const task=()=>({...scope,id:taskId,variant_id:11,binding_id:bindingId,device_id:taskId,account_id:'synthetic-local-account',
  platform:'wechat-article',source_revision:content.version,action:'preflight',status:'queued',created_at:Date.now(),
  grant_expires_at:Date.now()+3600000,revoked:false,receipt:null});
const response=value=>({ok:true,status:200,json:async()=>structuredClone(value)});
const checkedPublication=()=>({check:{id:requestId,task_id:taskId,actor_id:7,mode:'human',public_url:'https://mp.weixin.qq.com/s/test',
  reported_at:Date.now(),checked_at:Date.now(),status:'verified',code:'ADVISOR_CONFIRMED_PUBLIC_CONTENT',verification:'human-verified'},
  writeback:{event_id:requestId,state:'pending',attempts:1,updated_at:Date.now(),code:'WRITEBACK_UNAVAILABLE',result:null}});

test('publication evidence validates actor, URL, mode and native record separately',()=>{
  const publication=checkedPublication();assert.deepEqual(validateDistributionPublication(publication,taskId,'wechat-article','seo'),publication);
  for(const value of [{...publication,check:{...publication.check,task_id:bindingId}},
    {...publication,check:{...publication.check,public_url:'https://evil.invalid/s/test'}},
    {...publication,check:{...publication.check,verification:'machine-verified'}},
    {...publication,writeback:{...publication.writeback,state:'written'}}])
    assert.throws(()=>validateDistributionPublication(value,taskId,'wechat-article','seo'),{code:'CONTRACT_MISMATCH'});
});

test('human verification needs three checks and sends no client approved body',async()=>{
  const calls=[],value={...task(),action:'publish',status:'succeeded',resolution:{outcome:'published',public_url:'https://mp.weixin.qq.com/s/test',checked_at:Date.now()}};
  const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{
    calls.push({path,body:JSON.parse(options.body)});return response({schema:1,...scope,task_id:taskId,publication:checkedPublication()});}});
  await assert.rejects(client.checkPublication(scope,{task:value,mode:'human',requestId}),{code:'CONTRACT_MISMATCH'});assert.equal(calls.length,0);
  await client.checkPublication(scope,{task:value,mode:'human',preview:{...source,task_id:taskId,external_account_id:'gh_test'},confirmPublic:true,confirmAccount:true,confirmContent:true,requestId});
  assert.equal(calls[0].path,'/api/distribution/v1/publication-check');assert.equal(calls[0].body.expected_public_url,value.resolution.public_url);
  assert(!('content' in calls[0].body));assert(!('content_digest' in calls[0].body));client.dispose();
});

test('publication preview accepts only the frozen scope, version and digest',async()=>{
  const value={...source,task_id:taskId,external_account_id:'gh_test'};
  for(const patch of [{}, {task_id:bindingId}, {content:{...content,body:'changed'}}]){
    const c=createDistributionClient({session:session(),fetchImpl:async()=>response({...value,...patch})});
    if(Object.keys(patch).length)await assert.rejects(c.publicationSource(scope,task()),{code:'CONTRACT_MISMATCH'});
    else assert.equal((await c.publicationSource(scope,task())).content.body,content.body);
    c.dispose();
  }
});

test('publication images check actual bytes, type and SHA before creating a Blob',async()=>{
  const bytes=Uint8Array.from([137,80,78,71,13,10,26,10]);
  const sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
  const asset={id:'reviewed_1',sha256:sha,mediaType:'image/png',bytes:bytes.length};
  for(const changed of [{}, {sha256:'0'.repeat(64)}, {bytes:9}, {mediaType:'image/jpeg'}]){
    const c=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{
      assert.equal(path,`/api/distribution/v1/publication-assets/${taskId}/reviewed_1?module=seo&tenant_id=4&scope_id=19`);
      assert.equal(options.credentials,'omit');return new Response(bytes,{headers:{'Content-Type':'image/png'}});
    }});
    if(Object.keys(changed).length)await assert.rejects(c.publicationAsset(scope,task(),{...asset,...changed}),{code:'CONTRACT_MISMATCH'});
    else assert.deepEqual(new Uint8Array(await (await c.publicationAsset(scope,task(),asset)).arrayBuffer()),bytes);
    c.dispose();
  }
});

test('machine matching text remains pending human without a native record',()=>{
  const publication={check:{...checkedPublication().check,mode:'machine',status:'needs-human',
    code:'PUBLIC_TEXT_AND_ACCOUNT_MATCHED',verification:null},writeback:null};
  assert.deepEqual(validateDistributionPublication(publication,taskId,'wechat-article','seo'),publication);
  const markup=distributionTaskMarkup({...task(),action:'publish',status:'succeeded',publication});
  assert.match(markup,/仍需顾问核验/);assert.doesNotMatch(markup,/发布已核验/);
});

const monitor=()=>({module:'seo',publication_id:22,basis:'page-capture',state:'captured',evidence_source:'manual',
  observed_at:Date.now(),next_check_at:null,evidence_id:88,code:'MANUAL_CAPTURE'});
test('monitor observations reject other identities, extra private fields and unproven outcomes',()=>{
  const value=monitor();assert.deepEqual(validateDistributionMonitor(value,'seo',22),value);
  for(const patch of [{module:'geo'}, {publication_id:23}, {basis:'public-text'}, {state:'indexed'},
    {state:'observed'}, {observed_at:null}, {secret:'private'}, {evidence_source:'verified-by-ai'}])
    assert.throws(()=>validateDistributionMonitor({...value,...patch},'seo',22),{code:'CONTRACT_MISMATCH'});
});
test('live monitor is a fixed scoped GET and preserves the initial writeback result',async()=>{
  const publication=checkedPublication();publication.writeback={...publication.writeback,state:'written',code:'WRITEBACK_WRITTEN',
    result:{module:'seo',publication_id:22,monitor_state:'pending',verification:'human-verified',idempotent:false}};
  const value={...task(),publication};const initial=structuredClone(publication);let calls=0;
  const c=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{
    calls++;assert.equal(options.method,'GET');assert.equal(options.credentials,'omit');
    assert.equal(path,`/api/distribution/v1/publication-monitor?module=seo&tenant_id=4&scope_id=19&task_id=${taskId}`);
    return response({schema:1,...scope,task_id:taskId,as_of:Date.now(),monitor:monitor()});
  }});
  await assert.rejects(c.publicationMonitor(scope,task()),{code:'CONTRACT_MISMATCH'});
  const latest=await c.publicationMonitor(scope,value);assert.equal(calls,1);assert.deepEqual(value.publication,initial);
  const markup=distributionTaskMarkup({...value,publication:{...publication,monitor:latest.monitor}});
  assert.match(markup,/首次登记：待原模块检查/);assert.match(markup,/已取得页面截图/);assert.match(markup,/人工上传证据/);
  assert.match(markup,/收录和 AI 引用另行监测/);assert.doesNotMatch(markup,/收录成功|AI 引用成功/);c.dispose();
});

test('native writeback retry uses checked event and uncertain responses never auto resend',async()=>{
  let calls=0;const value={...task(),action:'publish',status:'succeeded',publication:checkedPublication()};
  const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{calls++;assert.equal(path,'/api/distribution/v1/publication-writeback');
    assert.equal(JSON.parse(options.body).event_id,requestId);return {ok:false,status:503};}});
  await assert.rejects(client.retryPublicationWriteback(scope,value,requestId),{code:'WRITE_OUTCOME_UNKNOWN'});
  assert.equal(calls,1);client.dispose();
});

test('checked publication and pending native monitoring are not presented as indexing or AI citation success',()=>{
  const publication=checkedPublication();publication.writeback={...publication.writeback,state:'written',code:'WRITEBACK_WRITTEN',
    result:{module:'seo',publication_id:22,monitor_state:'pending',verification:'human-verified',idempotent:false}};
  const markup=distributionTaskMarkup({...task(),action:'publish',status:'succeeded',publication});
  assert.match(markup,/发布已核验/);assert.match(markup,/收录和 AI 引用另行监测/);assert.match(markup,/待原模块检查/);
  assert.doesNotMatch(markup,/机器已核对/);
});

test('scoped reads use fixed origin, omitted cookies and no-store',async()=>{
  const calls=[];const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{calls.push({path,options});return response(snapshot());}});
  assert.equal((await client.scope(scope)).scope_id,19);
  assert.equal(calls[0].path,'/api/distribution/v1/scope?module=seo&tenant_id=4&scope_id=19');
  assert.equal(calls[0].options.credentials,'omit');assert.equal(calls[0].options.cache,'no-store');assert.equal(calls[0].options.redirect,'error');client.dispose();
});
for(const changed of [{tenant_id:5},{module:'geo'},{scope_id:20}])test('reject foreign scope '+JSON.stringify(changed),()=>{
  assert.throws(()=>validateDistributionScope({...snapshot(),...changed},scope),{code:'CONTRACT_MISMATCH'});
});
test('reject foreign task and unsupported capability claims',()=>{
  assert.throws(()=>validateDistributionTasks({schema:1,...scope,items:[{...task(),tenant_id:5}]},scope),{code:'CONTRACT_MISMATCH'});
  const value=snapshot();value.capabilities.automated_publish=true;
  assert.throws(()=>validateDistributionScope(value,scope),{code:'CONTRACT_MISMATCH'});
});
test('source preview validates approved content hash including Unicode',async()=>{
  const client=createDistributionClient({session:session(),fetchImpl:async()=>response(source)});
  assert.deepEqual((await client.preview(scope,11,'wechat-article')).content,content);client.dispose();
  const changed={...source,content:{...content,body:'已被替换'}};
  const other=createDistributionClient({session:session(),fetchImpl:async()=>response(changed)});
  await assert.rejects(other.preview(scope,11,'wechat-article'),{code:'CONTRACT_MISMATCH'});other.dispose();
});
test('session change discards a late read',async()=>{
  const s=session();let release;const client=createDistributionClient({session:s,fetchImpl:()=>new Promise(resolve=>release=resolve)});
  const pending=client.scope(scope);s.user={...s.user,id:8};release(response(snapshot()));
  await assert.rejects(pending,{code:'CONTEXT_CHANGED'});client.dispose();
});
test('ambiguous POST is sent once and never retried automatically',async()=>{
  let count=0;const client=createDistributionClient({session:session(),fetchImpl:async()=>{count++;throw Error('synthetic timeout');}});
  await assert.rejects(client.control(scope,'start',0,requestId),{code:'WRITE_OUTCOME_UNKNOWN'});
  assert.equal(count,1);client.dispose();
});

test('session change during content hashing prevents a stale authorized write',async()=>{
  const s=session();let calls=0;const client=createDistributionClient({session:s,fetchImpl:async()=>{calls++;return response({});}});
  const pending=client.enqueue(scope,{bindingId,preview:source,action:'preflight',requestId});
  s.user={...s.user,id:8};
  await assert.rejects(pending,{code:'CONTEXT_CHANGED'});assert.equal(calls,0);client.dispose();
});
test('wrong target in POST response is an unknown outcome',async()=>{
  const client=createDistributionClient({session:session(),fetchImpl:async()=>response({schema:1,task:{...task(),variant_id:22}})});
  await assert.rejects(client.enqueue(scope,{bindingId,preview:source,action:'preflight',requestId}),{code:'WRITE_OUTCOME_UNKNOWN'});client.dispose();
});
test('publication requires separate explicit confirmation before any request',async()=>{
  let count=0;const client=createDistributionClient({session:session(),fetchImpl:async()=>{count++;return response({schema:1,task:task()});}});
  await assert.rejects(client.enqueue(scope,{bindingId,preview:source,action:'publish',requestId}),{code:'CONTRACT_MISMATCH'});
  assert.equal(count,0);client.dispose();
});
test('read-only customers and foreign tenants make no advisor calls',async()=>{
  for(const user of [{id:9,tenant_id:4,permissions:{'seo.site':'view','seo.content':'view'}},{...session().user,tenant_id:5}]){
    let count=0;const client=createDistributionClient({session:{...session(),user},fetchImpl:async()=>{count++;return response(snapshot());}});
    await assert.rejects(client.scope(scope),{code:'PERMISSION_DENIED'});assert.equal(count,0);client.dispose();
  }
});
test('403 invalidates visible data and 500 writes remain ambiguous',async()=>{
  const client=createDistributionClient({session:session(),fetchImpl:async()=>({ok:false,status:403})});let invalidations=0;client.subscribe(()=>invalidations++);
  await assert.rejects(client.scope(scope),{code:'PERMISSION_DENIED'});assert.equal(invalidations,1);client.dispose();
  const other=createDistributionClient({session:session(),fetchImpl:async()=>({ok:false,status:503})});
  await assert.rejects(other.control(scope,'start',0,requestId),{code:'WRITE_OUTCOME_UNKNOWN'});other.dispose();
});
test('public links reject credentials, wrong hosts and tracking parameters',()=>{
  assert.equal(safeDistributionUrl('wechat-article','https://mp.weixin.qq.com/s/valid'),true);
  for(const url of ['javascript:alert(1)','https://mp.weixin.qq.com.evil.invalid/s/valid','https://x@mp.weixin.qq.com/s/valid','https://mp.weixin.qq.com/s/valid?secret=bad'])
    assert.equal(safeDistributionUrl('wechat-article',url),false);
});
test('task view escapes content and distinguishes human link from verified publication',()=>{
  const value={...task(),action:'publish',status:'unknown',receipt:{at:Date.now(),code:'HUMAN_PUBLISHED',evidence:'human-reported',publicUrl:'https://mp.weixin.qq.com/s/valid'}};
  assert.match(distributionTaskMarkup(value),/结果待核查/);assert.match(distributionTaskMarkup(value),/尚未通过内容及公开访问核验/);
  const injected={...task(),account_id:'<img src=x onerror=alert(1)>'};
  assert.doesNotMatch(distributionTaskMarkup(injected),/<img/);
});
test('advisor selection uses trusted project labels and hides unsupported write controls initially',async()=>{
  const panel=createAdvisorDistributionPanel({session:session(),browser:{crypto:globalThis.crypto},scopesForAdvisor:()=>[{...scope,tenant_name:'合成客户',scope_name:'合成项目'}],
    fetchImpl:async path=>response(path.includes('/scope?')?snapshot():path.includes('/sources?')?{schema:1,...scope,platform:'wechat-article',items:[{variant_id:11,source_revision:content.version,title:content.title,platform:'wechat-article'}]}:{schema:1,...scope,items:[]})});
  await panel.initialize(['seo']);const html=panel.html();
  assert.match(html,/合成客户/);assert.match(html,/合成项目/);assert.match(html,/开始分发/);
  assert.match(html,/\/api\/seo\/distribution-media\/workspace\?tenant_id=4&amp;site_id=19/);
  assert.doesNotMatch(html,/data-distribution="publish"/);panel.dispose();
});

test('media navigation uses fixed native routes and validated customer scope',()=>{
  assert.equal(distributionMediaHref({...scope,module:'geo'}),'/geo/tasks?tenant_id=4&project_id=19');
  assert.throws(()=>distributionMediaHref({...scope,tenant_id:'4&foreign=5'}),{code:'CONTRACT_MISMATCH'});
});

const accountSchedule=()=>({binding_id:bindingId,policy:{enabled:true,timezone:'Asia/Shanghai',min_interval_seconds:600,daily_limit:5,
  windows:[{start:540,end:1080}],revision:1,paused_reason:null},restriction:null,as_of:Date.now(),reason:'READY',next_allowed_at:Date.now(),available:true,
  system_used_today:0,system_remaining:5,platform_remaining:null,platform_quota_state:'unverified',reservation_task_id:null,effective_daily_limit:5,effective_interval_seconds:600});
test('schedule never substitutes a made up platform quota or unsafe time windows',()=>{
  assert.equal(validateDistributionSchedule(accountSchedule()).platform_remaining,null);
  for(const patch of [{platform_remaining:100},{platform_quota_state:'verified'},{policy:{...accountSchedule().policy,windows:[{start:1200,end:600}]}},
    {reason:'AUTOMATED_PUBLISH_VERIFIED'}])assert.throws(()=>validateDistributionSchedule({...accountSchedule(),...patch}),{code:'CONTRACT_MISMATCH'});
});
test('advisor cannot call global account controls and scoped limits retain caller scope',async()=>{
  let calls=0;const c=createDistributionClient({session:session(),fetchImpl:async(path,{body})=>{
    calls++;assert.equal(path,'/api/distribution/v1/account-restriction');const payload=JSON.parse(body);
    assert.equal(payload.tenant_id,scope.tenant_id);assert.equal(payload.module,scope.module);
    return response({schema:1,schedule:{...accountSchedule(),restriction:{revision:1,daily_limit:2,min_interval_seconds:1200}}});}});
  await assert.rejects(c.accountPolicies(),{code:'PERMISSION_DENIED'});
  await assert.rejects(c.pauseAccount(bindingId,1,'pause',requestId),{code:'PERMISSION_DENIED'});
  assert.equal(calls,0);
  await c.restrictAccount(scope,{binding_id:bindingId,expected_revision:0,daily_limit:2,min_interval_seconds:1200,request_id:requestId,tenant_id:5,module:'geo'});
  assert.equal(calls,1);c.dispose();
});
test('unconfirmed reconciliation cannot write and malformed write acknowledgement is ambiguous',async()=>{
  let calls=0;const c=createDistributionClient({session:session(),fetchImpl:async()=>{calls++;return response({schema:1,task_id:taskId,
    outcome:'published',evidence:'machine-verified',checked_at:Date.now(),public_url:'https://mp.weixin.qq.com/s/fake'});}});
  const v={task_id:taskId,outcome:'not-published',confirm_platform_checked:true,confirm_executor_stopped:false,request_id:requestId};
  await assert.rejects(c.resolveTask(scope,v),{code:'CONTRACT_MISMATCH'});assert.equal(calls,0);
  await assert.rejects(c.resolveTask(scope,{...v,confirm_executor_stopped:true}),{code:'WRITE_OUTCOME_UNKNOWN'});assert.equal(calls,1);c.dispose();
});
