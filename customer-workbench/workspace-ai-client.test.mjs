import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkspaceAiClient} from './js/workspace-ai-client.mjs';
test('AI retry retains exact payload and rejects mismatched scope, identity and nonadvisory responses',async()=>{
 let ctx={connected:true,tenantId:1,siteId:9,userId:12,revision:1},resolve;
 const calls=[];let result;
 const host={getContext:()=>ctx,transport:async(path,options)=>{calls.push({path,options});return result??new Promise(r=>resolve=r);}};
 const client=createWorkspaceAiClient({host,newId:()=> 'synthetic-id'}),pending=client.prepare('问题',[],88);
 result={ok:true,status:200,json:async()=>({tenant_id:1,site_id:9,request_id:'synthetic-id',provider:'deepseek',answer:'回答',sources:['content','execute'],advisory_only:true})};
 assert.deepEqual((await client.send(pending)).sources,['content']);await client.send(pending);
 assert.equal(calls[0].options.body,calls[1].options.body);
 assert.equal(JSON.parse(calls[0].options.body).content_id,88);
 result={ok:true,status:200,json:async()=>({tenant_id:2,site_id:9,request_id:'synthetic-id',provider:'deepseek',answer:'private',sources:[],advisory_only:true})};
 await assert.rejects(client.send(pending),/AI_CONTRACT_MISMATCH/);
 result=null;const old=client.send(pending);ctx={...ctx,siteId:19};resolve({ok:true,status:200,json:async()=>({})});await assert.rejects(old,/CONTEXT_CHANGED/);
 await assert.rejects(client.send(pending),/CONTEXT_CHANGED/);
});
test('AI throttling exposes safe retry duration and distinct server policy code',async()=>{
 const host={getContext:()=>({connected:true,tenantId:1,siteId:9,userId:12,revision:1}),transport:async()=>new Response(JSON.stringify({detail:{code:'assistant_rate_limited',message:'untrusted server text'}}),{status:429,headers:{'Retry-After':'24'}})};
 const client=createWorkspaceAiClient({host,newId:()=> 'synthetic-id'});
 await assert.rejects(client.send(client.prepare('问题',[])),e=>e.code==='assistant_rate_limited'&&e.status===429&&e.retryAfter===24&&!e.message.includes('untrusted'));
});
