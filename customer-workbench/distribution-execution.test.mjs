import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createDistributionClient} from './js/distribution-client.mjs';
import {distributionExecutionMarkup,distributionTaskMarkup,distributionHandoffInvestigationMarkup,distributionHandoffRetryMarkup} from './js/distribution-panel.mjs';
const scope={module:'seo',tenant_id:4,scope_id:19},id='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const session=()=>({token:'synthetic',user:{id:7,tenant_id:4,permissions:{'seo.site':'edit','seo.content':'edit'}},logout(){}});
const progress=()=>({schema:1,...scope,automatic_publish:false,permissions:[{binding_id:id,stage:'handoff',enabled:true,revision:1}],waits:[{queue_id:id,checked_at:1,reason:'CAPABILITY_UNAVAILABLE'}],items:[{id,queue_id:id,plan_id:id,binding_id:id,task_id:id,draft_version:'draft_1',source_revision:'source_1',content_digest:'a'.repeat(64),capability_digest:'b'.repeat(64),stage:'handoff',status:'awaiting-human',revoked:false,receipt:null}]});
test('frozen MHT directory keeps posts, image notes, videos and answers distinct',async()=>{
 const manifest=JSON.parse(await readFile(new URL('../docs/fixtures/mht-distribution-capabilities-v1.json',import.meta.url),'utf8'));
 const groups=new Map();for(const c of manifest.channels){const platform_id=c.platform==='website-cms'?'website':c.platform;const row=groups.get(platform_id)||{platform_id,label:c.name,content_types:[],v1_platform:null,native_intake:false,automatic_publish:false,real_channel_verified:false,status:'not-integrated',missing:[]};row.content_types.push(c.contentType);groups.set(platform_id,row);}
 const client=createDistributionClient({session:session(),fetchImpl:async()=>({ok:true,status:200,json:async()=>({schema:1,...scope,items:[...groups.values()]})})});
 const directory=(await client.platformDirectory(scope)).items;const html=distributionExecutionMarkup(directory,progress(),[],false);
 assert.equal(directory.length,12);assert.deepEqual(groups.get('weibo').content_types,['post']);assert.deepEqual(groups.get('douyin').content_types,['video']);assert.match(html,/图文笔记/);assert.match(html,/帖子/);assert.match(html,/回答/);assert.doesNotMatch(html,/undefined/);client.dispose();
});
test('handoff configuration is a single scoped consent without a publication grant',async()=>{
 const calls=[];const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{calls.push(JSON.parse(options.body));return {ok:true,status:200,json:async()=>({schema:1,permission:progress().permissions[0]})};}});
 await client.configureHandoff(scope,{binding_id:id,enabled:true,stage:'handoff',confirm_reviewed_handoff:true,expected_revision:0,request_id:id});
 assert.equal(calls.length,1);assert.equal(calls[0].tenant_id,4);assert(!('confirm_manual_publication' in calls[0]));assert(!('content' in calls[0]));client.dispose();
});
test('execution progress rejects foreign scope and invented automated publication',async()=>{
 for(const patch of [{tenant_id:5},{automatic_publish:true},{items:[{...progress().items[0],stage:'publish'}]}]){
 const client=createDistributionClient({session:session(),fetchImpl:async()=>({ok:true,status:200,json:async()=>({...progress(),...patch})})});await assert.rejects(client.executionProgress(scope),{code:'CONTRACT_MISMATCH'});client.dispose();}
});
test('view separates manual handoff from publication and explains missing capabilities',()=>{
 const html=distributionExecutionMarkup([],progress(),[{id,account_id:'owned_account'}],false);
 assert.match(html,/等待人工发稿或处理/);assert.match(html,/能力证明缺失/);assert.match(html,/停用自动素材交接/);assert.doesNotMatch(html,/data-distribution="publish"/);assert.match(html,/交接和预检完成不代表已发布/);
});
test('all eleven channel IDs remain candidates and never extend device v1',async()=>{
 const ids=['wechat-official','wechat-channels','xiaohongshu','zhihu','bilibili','douyin','weibo','linkedin','toutiao','baijiahao','kuaishou'];
 const client=createDistributionClient({session:session(),fetchImpl:async()=>({ok:true,status:200,json:async()=>({schema:1,...scope,items:ids.map(platform_id=>({platform_id,label:platform_id,content_types:['article'],v1_platform:null,native_intake:false,automatic_publish:false,real_channel_verified:false,status:'not-integrated',missing:['冻结协议未接线']}))})})});
 assert.equal((await client.platformDirectory(scope)).items.length,11);client.dispose();
});
test('unknown handoff requires explicit fixed-version investigation and retry sends no publication',async()=>{
 const calls=[];const value={task_id:id,source_revision:'source_1',content_digest:'a'.repeat(64),outcome:'not-published',confirm_platform_checked:true,confirm_executor_stopped:true,confirm_no_publication:true,request_id:id};
 const client=createDistributionClient({session:session(),fetchImpl:async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {ok:true,status:200,json:async()=>path.endsWith('/retry')?{handoffVersion:1,task_id:'dddddddd-dddd-4ddd-8ddd-dddddddddddd',previous_task_id:id,attempt:2,result:'HANDOFF_REDISPATCHED',publicationVerified:false}:{handoffVersion:1,task_id:id,outcome:'not-published',checked_at:1,evidence:'advisor-reported',result:'HANDOFF_NOT_PUBLISHED',publicationVerified:false}};}});
 await assert.rejects(client.resolveHandoff(scope,{...value,confirm_no_publication:false}));assert.equal(calls.length,0);
 await client.resolveHandoff(scope,value);const {outcome,confirm_platform_checked,...retry}=value;await client.retryHandoff(scope,retry);
 assert.equal(calls[0].path,'/api/distribution/handoff/v1/advisor/resolution');assert.equal(calls[1].path,'/api/distribution/handoff/v1/advisor/retry');assert(calls.every(c=>c.body.content_digest===value.content_digest&&!('confirm_manual_publication' in c.body)));client.dispose();
});
test('handoff completion and bounded recovery UI never claim publication or unlock unknown directly',()=>{
 const task={id,action:'handoff',status:'succeeded',platform:'wechat-article',source_revision:'source_1',content_digest:'a'.repeat(64),handoff_attempt:1};
 assert.match(distributionTaskMarkup(task),/素材交接完成，仍未发布/);assert.doesNotMatch(distributionTaskMarkup(task),/人工回填发布/);
 const unknown={...task,status:'unknown'};assert.equal(distributionHandoffRetryMarkup(unknown,false),'');assert.match(distributionHandoffInvestigationMarkup(unknown,false),/handoff_unpublished/);
 assert.equal(distributionHandoffInvestigationMarkup({...task,status:'awaiting-human',handoff_investigable:false},false),'');
 assert.match(distributionHandoffInvestigationMarkup({...task,status:'awaiting-human',handoff_investigable:true},false),/交接授权已过期/);
 assert.match(distributionHandoffRetryMarkup({...task,status:'canceled'},true),/disabled/);assert.match(distributionHandoffRetryMarkup({...task,status:'failed',handoff_attempt:3},false),/已达上限/);
});
