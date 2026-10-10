import test from 'node:test';
import assert from 'node:assert/strict';
import {createOnsiteAiPoller} from './js/onsite-ai-poller.mjs';
import {createOnsiteClient} from './js/onsite-client.mjs';
import {onsiteView} from './js/onsite-view.mjs';

const nonce='ca8d119b-e64c-4176-bbb2-3ac4240a59d0';
const task=(state='queued',revision=1)=>({id:77,module:'seo',tenant_id:1,scope_id:9,
  title:'站内任务',workflow:{module:'seo',revision,phase:'draft',items:[],history:[],source:{},
    ai_run:{request_id:nonce,state}},request_run:{request_id:nonce,state},
  allowed_actions:['save_proposal'],capabilities:{ai_planning:{enabled:true,can_generate:true}}});
function fixture(options={}){
  let row=task(),context={connected:true,tenantId:1,siteId:9,userId:7,revision:1},allowed=true,time=0,id=0;
  const timers=new Map(),reads=[],applied=[],errors=[];
  const poller=createOnsiteAiPoller({getTask:()=>row,getContext:()=>context,canRead:()=>allowed,
    read:async(...args)=>{reads.push(args);return options.read?options.read(...args):task('ready',2);},
    apply:data=>{applied.push(data);row=data;poller.sync();},onError:error=>{errors.push(error);poller.sync();},
    schedule:fn=>{timers.set(++id,fn);return id;},cancel:key=>timers.delete(key),now:()=>time,
    ...(options.maxDuration?{maxDuration:options.maxDuration}:{})});
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  return {poller,reads,applied,errors,timers,flush,setRow:r=>row=r,setContext:c=>context={...context,...c},
    allow:b=>allowed=b,async tick(){const [key,fn]=timers.entries().next().value;timers.delete(key);time+=3000;fn();await flush();}};
}
test('queued requests update through running to ready using only bounded reads',async()=>{
  let count=0;const f=fixture({read:async()=>task(++count===1?'running':'ready',count+1)});
  f.poller.sync();f.poller.sync();assert.equal(f.timers.size,1);
  await f.tick();assert.equal(f.applied[0].workflow.ai_run.state,'running');
  await f.tick();assert.equal(f.applied[1].workflow.ai_run.state,'ready');
  assert.deepEqual(f.reads,[[77,nonce],[77,nonce]]);assert.equal(f.timers.size,0);
});
test('unsaved input pauses reads and a newly started edit prevents applying an in-flight reply',async()=>{
  let release;const f=fixture({read:()=>new Promise(resolve=>release=resolve)});
  f.allow(false);f.poller.sync();await f.tick();assert.equal(f.reads.length,0);
  f.allow(true);await f.tick();f.allow(false);release(task('ready',2));await f.flush();
  assert.equal(f.applied.length,0);assert.equal(f.timers.size,1);f.poller.dispose();
});
test('responses cannot follow a customer or user scope change',async()=>{
  for(const change of [{tenantId:2},{userId:8},{connected:false}]){
    let release;const f=fixture({read:()=>new Promise(resolve=>release=resolve)});
    f.poller.sync();await f.tick();f.setContext(change);release(task('ready',2));await f.flush();
    assert.equal(f.applied.length,0);assert.equal(f.errors.length,0);f.poller.dispose();
  }
});
test('a late result cannot replace a newly selected request or survive disposal',async()=>{
  for(const dispose of [false,true]){
    let release;const f=fixture({read:()=>new Promise(resolve=>release=resolve)});
    f.poller.sync();await f.tick();
    if(dispose)f.poller.dispose();else f.setRow({...task(),workflow:{...task().workflow,ai_run:{request_id:nonce.replace('ca8d','ba8d'),state:'queued'}}});
    release(task('ready',2));await f.flush();assert.equal(f.applied.length,0);f.poller.dispose();
  }
});
test('three read failures stop polling without restarting on render',async()=>{
  const f=fixture({read:async()=>{throw Error('network');}});f.poller.sync();
  await f.tick();await f.tick();await f.tick();
  assert.equal(f.errors.length,1);assert.equal(f.reads.length,3);assert.equal(f.timers.size,0);
  f.poller.sync();assert.equal(f.timers.size,0);
});
test('permission or contract failure stops immediately and the duration limit does not reset on render',async()=>{
  for(const code of ['PERMISSION_DENIED','CONTEXT_CHANGED','CONTRACT_MISMATCH','AI_REQUEST_SUPERSEDED']){
    const f=fixture({read:async()=>{throw Object.assign(Error(code),{code});}});f.poller.sync();await f.tick();
    assert.equal(f.reads.length,1);assert.equal(f.timers.size,0);assert.equal(f.errors.length,1);
  }
  const f=fixture({maxDuration:6000,read:async()=>task('running')});f.poller.sync();await f.tick();f.poller.sync();await f.tick();
  assert.equal(f.reads.length,1);assert.equal(f.errors[0].code,'AI_POLL_LIMIT');assert.equal(f.timers.size,0);
});
for(const module of ['seo','geo']){
  test(module+' accepts 202 queued and keeps polling separate from writable state',async()=>{
    const context={connected:true,tenantId:1,siteId:9,projectId:10,userId:7,revision:1},calls=[];
    let row={...task('ready'),module,scope_id:module==='seo'?9:10,workflow:{...task().workflow,module,ai_run:null}};
    const client=createOnsiteClient({module,getContext:()=>context,transport:async(path,opt)=>{
      calls.push({path,opt});
      if(opt.method==='POST'){const body=JSON.parse(opt.body);row={...row,workflow:{...row.workflow,ai_run:{request_id:body.request_id,state:'queued'}}};
        return {ok:true,status:202,json:async()=>row};}
      const data=path.includes('/ai-requests/')?{...row,workflow:{...row.workflow,revision:2,ai_run:{...row.workflow.ai_run,state:'ready'}},request_run:{...row.workflow.ai_run,state:'ready'}}:
        {module,tenant_id:1,scope_id:row.scope_id,can_create:true,items:[row]};
      return {ok:true,status:200,json:async()=>data};
    }});
    await client.list();const queued=await client.propose(77);assert.equal(queued.workflow.ai_run.state,'queued');
    const ready=await client.readAi(77,queued.workflow.ai_run.request_id);
    assert.equal(ready.workflow.revision,2);
    await assert.rejects(()=>client.propose(77),/AI_PLANNING_UNAVAILABLE/);
    assert.equal(calls.filter(c=>c.opt.method==='POST').length,1);
    assert.equal(calls.at(-1).path,`/api/v1/${module}/workbench/onsite-tasks/77/ai-requests/${queued.workflow.ai_run.request_id}?tenant_id=1&${module==='seo'?'site_id=9':'project_id=10'}`);
    client.adopt(ready);
  });
}
test('queued status cannot offer another generation even with inconsistent server capability',()=>{
  const row=task();const html=onsiteView({items:[row],can_create:false},row,false);
  assert.match(html,/已排队/);assert.match(html,/未保存输入/);assert(!html.includes('data-action="onsite-ai-proposal"'));
});
