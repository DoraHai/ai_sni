import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';
import {createGeoProjectClient} from './js/geo-project-client.mjs';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {geoHome,geoResource,geoExecutions,geoWeekly,geoSafeLink,geoObservation} from './js/geo-project-view.mjs';
import {geoFixture,weekly,observation} from './tests/geo-client-fixture.mjs';
const response=(data,status=200)=>new Response(JSON.stringify(data),{status});
const context={connected:true,tenantId:1,projectId:10,userId:7,revision:1};
const base='/api/v1/geo/projects/10/client/';
const resources=['overview','visibility','questions','questions/3','answers','answers/5','content','content/7','content/7/variants','content/7/variants/11','content/7/articles/9','deliveries'];
async function hostFixture(){
  const calls=[];let session={token:'synthetic',userId:7,tenantId:1,projectId:10,revision:1};let notify;
  const user={id:7,tenant_id:1,permissions:{'geo.assets':'view','geo.content':'view'}};
  const host=createGeoHostAdapter({origin:'https://fixture.test',getSession:()=>session,subscribeSession:fn=>{notify=fn;return ()=>{};},fetchImpl:async(path,options)=>{
    const u=new URL(path);calls.push({path,options});
    if(u.pathname==='/api/v1/auth/me')return response({user});
    if(u.pathname==='/api/v1/auth/modules')return response({tenant_id:1,modules:[{module_code:'geo',available:true}]});
    if(u.pathname==='/api/v1/geo/tenants')return response({tenants:[{id:1,name:'合成客户'}]});
    if(u.pathname==='/api/v1/geo/projects')return response({projects:[{id:10,tenant_id:1,status:'active'}]});
    return response(geoFixture(u.pathname.endsWith('executions')?'executions':u.pathname.split('/client/')[1]));
  }});await host.initialize();calls.length=0;return {host,calls,change(){session={...session,projectId:11,revision:2};notify();}};
}
test('A–L and executions are exact GET routes; all invalid scope/query/body/write requests stop before transport',async()=>{
  const {host,calls}=await hostFixture();
  for(const resource of resources)await host.transport(base+resource+'?tenant_id=1');
  await host.transport('/api/v1/geo/projects/10/executions?tenant_id=1');
  await host.transport(base+'answers?tenant_id=1&week_end=2026-10-19&question_id=3&engine_key=a.b-c_d&source_kind=real&eligibility=qualified&limit=100&cursor=opaque');
  const accepted=calls.length;
  for(const resource of resources)for(const method of ['POST','PUT','PATCH','DELETE'])await assert.rejects(host.transport(base+resource+'?tenant_id=1',{method}),/DENIED/);
  for(const path of [base+'overview/',base+'overview/settings',base+'content/7/variants/11/retry',base+'questions/0',base+'answers/9007199254740992',base.replace('/10/','/11/')+'overview','/api/v1/geo/projects/10/service-plan','/api/v1/geo/integration/read/answers','https://fixture.test'+base+'overview',base+'%6fverview'])await assert.rejects(host.transport(path+'?tenant_id=1'),/DENIED/);
  for(const query of ['tenant_id=2','tenant_id=1&tenant_id=1','tenant_id=1&business_id=1','tenant_id=1&project_id=10','tenant_id=1&limit=101','tenant_id=1&limit=0','tenant_id=1&limit=1e1','tenant_id=1&cursor=','tenant_id=1&cursor='+ 'x'.repeat(4097),'tenant_id=1&status=paused','tenant_id=1&q='+ 'x'.repeat(101),'tenant_id=1&week_end=tomorrow'])await assert.rejects(host.transport(base+'questions?'+query),/DENIED|MISMATCH/);
  for(const resource of resources)await assert.rejects(host.transport(base+resource+'?tenant_id=1',{body:'{}'}),/BODY_DENIED/);
  assert.equal(calls.length,accepted);assert(calls.every(c=>c.options.method==='GET'));host.dispose();
});
test('project client checks all response scopes, closed weeks, pagination, and executions project',async()=>{
  const {host}=await hostFixture();const c=createGeoProjectClient({transport:host.transport,getContext:host.getContext});
  for(const resource of [...resources,'executions'])assert(await c.read(resource));host.dispose();
  for(const mutate of [v=>v.tenant_id=2,v=>v.project_id=11,v=>v.schema_version='old',v=>v.read_only=false,v=>v.basis.period.closed=false,v=>v.basis.period.timezone='UTC',v=>v.basis.period.week_end='2026-10-12']){
    const value=structuredClone(geoFixture('overview'));mutate(value);
    const client=createGeoProjectClient({getContext:()=>context,transport:async()=>response(value)});
    await assert.rejects(client.read('overview',{week_end:'2026-10-19'}),/RESPONSE_INVALID/);
  }
  const client=createGeoProjectClient({getContext:()=>context,transport:async()=>response({...geoFixture('executions'),project_id:11})});await assert.rejects(client.read('executions'),/RESPONSE_INVALID/);
});
test('identity, client invalidation and late JSON prevent old responses from becoming readable',async()=>{
  for(const mode of ['scope','revision','invalidate']){
    let ctx={...context},release;const client=createGeoProjectClient({getContext:()=>ctx,transport:async()=>({ok:true,status:200,json:()=>new Promise(r=>release=r)})});
    const pending=client.read('overview');await Promise.resolve();
    if(mode==='scope')ctx={...ctx,projectId:11};else if(mode==='revision')ctx={...ctx,revision:2};else client.invalidate();
    release(geoFixture('overview'));await assert.rejects(pending,/CONTEXT_CHANGED/);
  }
});
test('404/405/409/503 and arbitrary error bodies become only safe error codes',async()=>{
  for(const [status,code] of [[404,'GEO_NOT_OPEN'],[405,'GEO_NOT_OPEN'],[409,'GEO_SCOPE_CHANGED'],[503,'GEO_READ_FAILED']]){
    const client=createGeoProjectClient({getContext:()=>context,transport:async()=>response({detail:'PRIVATE_INTERNAL_ERROR'},status)});
    await assert.rejects(client.read('overview'),e=>e.code===code&&!e.message.includes('PRIVATE'));
  }
});
test('null metrics, qualified true zero, observation fractions, confirmations and native delivery distinctions',()=>{
  assert.match(geoWeekly(weekly()),/检测数据还不够/);assert(!geoWeekly(weekly()).includes('0%'));
  assert.match(geoWeekly(weekly(true)),/>0%/);assert(!geoWeekly(weekly()).includes('undefined'));
  for(const [x,y] of [[1,1],[0,1],[0,0]]){const text=geoObservation(observation(x,y));assert(!text.includes('%'));assert.match(text,y?new RegExp(`${x}/${y}`):/尚无/);}
  const content=geoResource('content/7',geoFixture('content/7'));assert.match(content,/历史版本已确认，当前版本尚无有效确认记录/);assert(!content.includes('<img'));
  const html=geoResource('deliveries',geoFixture('deliveries'));for(const text of ['原生发布登记','原生投递回执','尚无有效匹配证据','不代表正式客户验收','回执不等于'])assert(html.includes(text));
  assert(!geoResource('answers/5',geoFixture('answers/5')).includes('<script>'));
  const executions=geoExecutions(geoFixture('executions'));for(const text of ['仅最近 20 项','仅最多 200 个问题','单项证据仅为已加载预览'])assert(executions.includes(text));assert(!executions.includes('DO_NOT_DISPLAY'));assert(!geoExecutions(geoFixture('executions'),true).includes('DO_NOT_DISPLAY'));
  const slots=Object.fromEntries(['overview','visibility','executions'].map(r=>[r,{value:geoFixture(r)}]));const home=geoHome(slots);assert.match(home,/当前待确认.*1 项稿件/);assert.match(home,/仅最近20项/);assert.match(home,/月度计划/);assert.match(home,/上海时区已结束完整周/);
});
test('content and citation links reject scripts, signed/query URLs, local hosts and embedded credentials',()=>{
  for(const url of ['javascript:alert(1)','data:text/html,test','file:///a','https://user:pass@example.com','https://example.com/a?token=fixture','http://127.1/a','http://0x7f000001','http://[::1]','http://intranet','http://host.local/a','http://a.internal/a'])assert(!geoSafeLink(url).includes('href='),url);
  assert.match(geoSafeLink('https://example.com/a#heading'),/href="https:\/\/example.com\/a"/);
});
test('panel pins server week, hides empty tabs and clears immediately on reset including late bootstrap responses',async()=>{
  const calls=[],held=[];let delay=false;
  const node={innerHTML:''};const panel=createGeoProjectPanel({host:{getContext:()=>context,transport:async path=>{calls.push(path);const r=path.includes('/client/')?path.split('/client/')[1].split('?')[0]:'executions';if(delay)return new Promise(resolve=>held.push(()=>resolve(response(geoFixture(r)))));return response(geoFixture(r));}}});
  panel.renderInto(node);await panel.refresh();assert.match(node.innerHTML,/本期要点/);assert.match(node.innerHTML,/交付记录/);
  for(const path of calls.filter(p=>/client\/(visibility|questions)/.test(p)))assert.match(path,/week_end=2026-10-19/);
  delay=true;const pending=panel.refresh();await Promise.resolve();panel.reset();held.forEach(fn=>fn());await pending;
  assert(!node.innerHTML.includes('合成内容任务'));assert(!node.innerHTML.includes('当前归属问题 3'));panel.dispose();
});
