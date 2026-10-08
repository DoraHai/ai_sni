import test from 'node:test';import assert from 'node:assert/strict';
import {createConversationClient} from './js/conversation-client.mjs';
import {createHostSessionAdapter} from './js/host-session-adapter.mjs';
import {startFixtureServer} from './tests/fixture-server.mjs';

test('human conversation uses authorized scope, explicit read and same-key recovery after committed response loss',async()=>{
  const f=await startFixtureServer();let session={token:'fixture-customer',userId:12,tenantId:1,siteId:9,revision:1};
  const host=createHostSessionAdapter({origin:f.origin,allowLocalHttp:true,getSession:()=>session});const client=createConversationClient({host});
  try{
    await host.initialize();assert.equal((await client.list(88)).unread,0);const pending=client.prepare(88,'合成客户消息');f.state.messageDropOnce=true;
    await assert.rejects(client.send(pending));const retried=await client.send(pending);assert.equal(retried.replayed,true);assert.equal(f.state.messages.get(1).length,1);
    const writes=f.state.calls.filter(c=>c.path.endsWith('/messages')&&c.method==='POST');assert.equal(writes[0].body.request_id,writes[1].body.request_id);assert.equal(writes[0].body.sender,undefined);
    assert.equal(f.state.calls.filter(c=>c.path.endsWith('/read')).length,0);assert.equal((await client.list(88)).items[0].senderName,'客户实名');
    await client.markRead(88,retried.message.id);assert.equal(f.state.messageRead.get('1:12'),retried.message.id);
    await assert.rejects(client.send({...pending,text:'不同文字'}),e=>e.status===409);
    session={token:'fixture-advisor',userId:7,tenantId:2,siteId:19,revision:2};await host.initialize();await assert.rejects(client.send(pending),/CONTEXT_CHANGED/);
    const before=f.state.calls.length;await assert.rejects(host.transport('/api/v1/seo/workbench/content-assets/88/conversation/messages',{method:'POST',body:JSON.stringify({tenant_id:1,site_id:9,request_id:pending.requestId,body:'越界'})}),/SCOPE_MISMATCH/);assert.equal(f.state.calls.length,before);
  }finally{host.dispose();await f.close();}
});

test('conversation checks foreign metadata and invalid cursors before rendering or writing',async()=>{
  const ctx={connected:true,tenantId:1,siteId:9,userId:12,revision:1};let calls=0;
  const host={getContext:()=>ctx,transport:async()=>{calls++;return {ok:true,json:async()=>({scope:{tenant_id:2,site_id:9,content_id:88},actor:{id:12},semantics:'human_messages_only',allowed_actions:{read:true}})};}};
  const client=createConversationClient({host});await assert.rejects(client.list(88),/CONTRACT_MISMATCH/);assert.equal(calls,1);assert.throws(()=>client.prepare(88,'未读取授权'),/CONVERSATION_READ_REQUIRED/);
});
