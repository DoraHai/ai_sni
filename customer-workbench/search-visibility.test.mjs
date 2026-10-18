import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';
import {createSearchVisibilityClient,visibilityConfig,visibilityAdvisor} from './js/search-visibility-client.mjs';
import {renderSearchVisibility,visibilityLink} from './js/search-visibility-view.mjs';
import {visibilityTime} from './js/search-visibility-view.mjs';
import {createSearchVisibilityPanel} from './js/search-visibility-panel.mjs';
import {createPlatformConsoleClient} from './js/platform-console-client.mjs';
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
const user={id:7,tenant_id:1,permissions:{'geo.assets':'edit','geo.content':'edit'}};
const context={connected:true,tenantId:1,projectId:10,userId:7,revision:1};
const base='/api/v1/geo/projects/10/search-visibility';
async function hostFixture(level='edit',admin=false){
  const calls=[],me={...user,tenant_id:admin?null:1,permissions:{'geo.assets':level,'geo.content':level,...(admin?{'settings.accounts':'edit','settings.customers':'edit'}:{})}};
  let s={token:'synthetic-session',userId:7,tenantId:1,projectId:10,revision:1};
  const host=createGeoHostAdapter({origin:'https://fixture.test',getSession:()=>s,fetchImpl:async(path,options)=>{
    calls.push({path:new URL(path).pathname,options});const p=new URL(path).pathname;
    if(p==='/api/v1/auth/me')return response({user:me});
    if(p==='/api/v1/auth/modules')return response({tenant_id:me.tenant_id,modules:[{module_code:'geo',available:true}]});
    if(p==='/api/v1/geo/tenants')return response({tenants:[{id:1,name:'合成客户'}]});
    if(p==='/api/v1/geo/projects')return response({projects:[{id:10,tenant_id:1,status:'active'}]});
    return response({state:'ready',latest:null,weeks:[]});
  }});
  await host.initialize();calls.length=0;return {host,calls,change:()=>{s={...s,revision:2};}};
}
test('verified GEO transport permits only exact project search routes and methods',async()=>{
  const {host,calls}=await hostFixture();
  for(const [path,method,body] of [[base,'GET'],[base+'/config','GET'],[base+'/config','PUT','{}'],[base+'/run','POST'],[base+'/runs/2','GET'],[base+'/runs/2/csv','GET']])await host.transport(path+'?tenant_id=1',{method,body});
  assert.equal(calls.length,6);
  for(const path of [base.replace('/10/','/11/')+'?tenant_id=1',base+'?tenant_id=2',base+'?tenant_id=1&tenant_id=1',base+'?tenant_id=1&api_key=x','/api/v1/geo/search-visibility/usage','/api/v1/sem/search-visibility'])await assert.rejects(host.transport(path),/DENIED|MISMATCH/);
  await assert.rejects(host.transport(base+'/config?tenant_id=1',{method:'PUT',body:'{"api_key":"synthetic"}'}),/BODY_DENIED/);
  await assert.rejects(host.transport(base+'/run?tenant_id=1',{method:'POST',body:'{"project_id":11}'}),/BODY_DENIED/);
  await assert.rejects(host.transport(base+'/runs/2?tenant_id=1',{method:'DELETE'}),/ROUTE_DENIED/);
  assert.equal(calls.length,6);host.dispose();
});
test('customer transport rejects settings, runs and global usage before network',async()=>{
  const {host,calls}=await hostFixture('view');
  await host.transport(base+'?tenant_id=1');
  for(const [path,method] of [[base+'/config','GET'],[base+'/config','PUT'],[base+'/run','POST']])await assert.rejects(host.transport(path+'?tenant_id=1',{method}),/PERMISSION_DENIED/);
  assert.equal(calls.length,1);host.dispose();
});
test('client freezes request scope and clears delayed old-context results',async()=>{
  let c={...context},release;
  const client=createSearchVisibilityClient({getContext:()=>c,transport:()=>new Promise(r=>release=r)});
  const pending=client.overview();c={...c,projectId:11};release(response({state:'ready',latest:null,weeks:[]}));
  await assert.rejects(pending,/项目或身份已变化/);
});
test('client POST is sent once and an unknown outcome never retries',async()=>{
  let count=0;const client=createSearchVisibilityClient({getContext:()=>context,transport:async()=>{count++;throw Error('network');}});
  await assert.rejects(client.run(),/不会重复提交/);assert.equal(count,1);
});
test('client CSV refuses JSON state and accepts only actual CSV',async()=>{
  let csv=false;const client=createSearchVisibilityClient({getContext:()=>context,transport:async()=>csv?new Response('\ufeff类型,结果',{headers:{'content-type':'text/csv;charset=utf-8'}}):response({state:'not_open'})});
  await assert.rejects(client.csv(3),/暂未开放/);csv=true;assert.equal((await client.csv(3)).type,'text/csv;charset=utf-8');
  assert.throws(()=>client.csv('../other'),/有效的检查记录/);
});
test('config limits, defaults, URLs and fields are explicit',()=>{
  const config=visibilityConfig({domains:'example.com\nexample.com',brand_terms:'品牌\n品牌',core_terms:'工业',enabled:true});
  assert.equal(config.customer_visible,false);assert.deepEqual(config.domains,['example.com']);assert.equal(config.enabled,true);
  for(const input of [{domains:'https://example.com'},{brand_terms:'词\n'.repeat(6)},{core_terms:'字'.repeat(129)},{zh_url:'javascript:alert(1)'},{extra_article_urls:'https://user:password@example.com'}])assert.throws(()=>visibilityConfig(input));
  assert(!('api_key' in visibilityConfig({api_key:'synthetic'})));
  assert(visibilityAdvisor(user));assert(!visibilityAdvisor({permissions:{'geo.content':'edit'}}));
});
const data={state:'ready',latest:{id:3,status:'succeeded',finished_at:'2026-10-18 06:05',result:{summary:{indexed:true,indexed_count:12,brand_hit:1,brand_total:2,core_hit:2,core_total:3,articles_alive:4,articles_total:5},items:[
  {kind:'brand',query:'品牌词',best_rank:2,results:[{rank:1,title:'前排官网',url:'https://example.org'},{rank:2,title:'你的页面',url:'https://example.com'}]},
  {kind:'core',query:'工业词',best_rank:null,results:[]},
]}},weeks:[{week:'2026-10-12',status:'succeeded',summary:{brand_hit:1,core_hit:2}}]};
test('view shows plain-language three metrics, trend, exact rank and raw links',()=>{
  const html=renderSearchVisibility({data},{advisor:true});
  for(const text of ['是 · 约 12 页','3 / 5 个','4 / 5 篇','第 2 名','前 20 名没有','前排官网','最近 8 周','北京时间','下载表格（CSV）','不等于 DeepSeek 回答里会提到你'])assert(html.includes(text),text);
  assert(!html.includes('stopped_reason'));assert(!html.includes('rerank_score'));assert(html.includes('rel="noopener noreferrer"'));
});
test('customer hidden, pending, empty and failed views remain honest',()=>{
  assert.equal(renderSearchVisibility({data:{state:'not_open'}}), '');
  assert.match(renderSearchVisibility({data:{state:'not_enabled'}},{advisor:true}),/这项检查还没开始/);
  assert.match(renderSearchVisibility({data:{state:'ready',latest:null,weeks:[]}},{advisor:true}),/还没有检查记录/);
  const failed=structuredClone(data);failed.latest.status='failed';failed.latest.error='仅顾问错误细节';
  failed.latest.result.items[1].error='仅顾问错误细节';
  assert.match(renderSearchVisibility({data:failed},{advisor:true}),/仅顾问错误细节/);
  // Customer data is already redacted by the server; renderer also never displays error details.
  const html=renderSearchVisibility({data:failed},{advisor:false});assert(!html.includes('仅顾问错误细节'));
  assert(!html.includes('立即跑一次'));assert(!html.includes('项目设置'));assert(html.includes('本次未确认'));
  const pending=structuredClone(data);pending.latest.status='running';assert.match(renderSearchVisibility({data:pending},{advisor:true}),/检查中/);
});
test('provider titles, queries and links cannot inject HTML or script URLs',()=>{
  const value=structuredClone(data);value.latest.result.items[0].query='<img src=x onerror=alert(1)>';
  const html=renderSearchVisibility({data:value},{advisor:true});assert(!html.includes('<img'));assert(html.includes('&lt;img'));
  assert(!visibilityLink('javascript:alert(1)','坏链接').includes('href='));assert(!visibilityLink('https://user:secret@example.com','坏链接').includes('href='));
});
test('global settings administrator with GEO view uses the same configuration and run gate',async()=>{
  const {host,calls}=await hostFixture('view',true);
  for(const [suffix,method,body] of [['','GET'],['/config','GET'],['/config','PUT','{}'],['/run','POST']])await host.transport(base+suffix+'?tenant_id=1',{method,body});
  assert.equal(calls.length,4);
  await assert.rejects(host.transport('/api/v1/geo/workbench/onsite-tasks?tenant_id=1',{method:'PUT',body:'{}'}),/ROUTE_DENIED/);
  host.dispose();
});
test('settings read failure preserves a successfully read overview; reset synchronously clears it',async()=>{
  const node={innerHTML:''};const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async path=>path.includes('/config?')?response({detail:'not available'},403):response(data)},getUser:()=>user,document:{visibilityState:'visible'}});
  panel.renderInto(node);await panel.refresh();
  assert(node.innerHTML.includes('sv-metrics'));assert(node.innerHTML.includes('项目设置暂时打不开'));
  panel.reset();assert(!node.innerHTML.includes('sv-metrics'));assert(!node.innerHTML.includes('品牌词'));panel.dispose();
});
test('incomplete query and unattempted failed metrics stay explicit; time always uses Beijing',()=>{
  const incomplete=structuredClone(data);incomplete.latest.result.summary.index_query_ok=false;
  assert.match(renderSearchVisibility({data:incomplete},{advisor:true}),/部分域名本次未查完/);
  incomplete.latest.status='failed';incomplete.latest.result.items=[];
  const html=renderSearchVisibility({data:incomplete},{advisor:true});assert(html.includes('尚未确认'));
  assert.equal(visibilityTime('2026-10-17T22:05:00Z'),'2026-10-18 06:05');
  assert.equal(visibilityTime('2026-10-18 06:05'),'2026-10-18 06:05');
  assert.match(renderSearchVisibility({data:null,message:'读取失败'},{advisor:true}),/暂时无法读取/);
  assert(!renderSearchVisibility({data:{state:'not_enabled'}},{advisor:false}).includes('项目开关'));
});
test('global usage requires initialized admin and rejects delayed data after identity changes',async()=>{
  const me={id:7,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}},session={token:'synthetic',user:me,authRevision:1,refreshUser(value){this.user=value;}};
  const calls=[];let delay=false;
  const client=createPlatformConsoleClient({session,fetchImpl:async path=>{
    calls.push(path);
    if(path.endsWith('/me'))return response({user:me});
    if(path.endsWith('/snapshot'))return response({schema:1,mode:'read_only_inventory',sources:{},costs:{}});
    const result={requests:3,billable:1,cost_cny:.005,reserved_cny:0,limit_cny:30};
    if(delay)return {ok:true,status:200,json:async()=>{session.authRevision++;return result;}};
    return response(result);
  }});
  await assert.rejects(client.searchVisibilityUsage(),/NOT_AUTHORIZED/);
  await client.initialize();assert.equal((await client.searchVisibilityUsage()).requests,3);
  assert.equal(calls.at(-1),'/api/v1/geo/search-visibility/usage');
  delay=true;await assert.rejects(client.searchVisibilityUsage(),/STALE/);
});

const adminUser={id:7,tenant_id:null,permissions:{'geo.assets':'view','geo.content':'view','settings.accounts':'edit','settings.customers':'edit'}};
const customerUser={...user,permissions:{'geo.assets':'view','geo.content':'view'}};
for(const [role,identity] of [['customer',customerUser],['advisor',user],['admin',adminUser]]){
  for(const enabled of [false,true])test(`${role}: saved enabled=${enabled} explains who acts and where without exposing codes`,async()=>{
    const calls=[],node={innerHTML:''};
    const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async path=>{
      calls.push(path);return response(path.includes('/config?')?{config:{enabled,customer_visible:false}}:{state:'not_enabled'});
    }},getUser:()=>identity,document:{visibilityState:'visible'}});
    try{
      panel.renderInto(node);await panel.refresh();
      const html=node.innerHTML;
      assert.doesNotMatch(html,/>[^<]*(?:not_enabled|customer_visible|api_key|[A-Z][A-Z0-9]*_[A-Z_]+|HTTP|待启用)/);
      if(role==='customer'){
        assert.match(html,/每周会显示你的品牌在 DeepSeek 搜索里能不能被找到。想开通请联系你的顾问/);
        assert.equal(calls.length,1);assert.doesNotMatch(html,/项目设置|服务器|超管|data-sv="config"/);
      }else{
        assert.equal(calls.length,2);
        assert.match(html,enabled?/项目已开启，但平台的搜索服务还没接通/:/还没开启。点击本块右上方「项目设置」，打开「每周核对这个项目」并点击「保存项目设置」。搜索服务接通后，每周一北京时间早上 6 点会自动检查一次/);
        if(enabled)assert.match(html,role==='admin'?/超管联系技术人员在服务器上配置搜索服务/:/需要超管处理，请联系超管/);
        assert.equal(html.includes('console=platform&amp;page=costs')||html.includes('console=platform&page=costs'),role==='admin');
      }
    }finally{panel.dispose();}
  });
}

test('not-open customer panel has no residual markup, message or settings request',async()=>{
  const calls=[],node={innerHTML:''};
  const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async path=>{
    calls.push(path);return response({state:'not_open',message:'暂未开放'});
  }},getUser:()=>customerUser,document:{visibilityState:'visible'}});
  panel.renderInto(node);await panel.refresh();assert.equal(node.innerHTML,'');assert.equal(calls.length,1);panel.dispose();
});

test('configuration unavailable gives both instructions; refresh clears stale saved state',async()=>{
  const node={innerHTML:''};let enabled=false,denied=false;
  const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async path=>
    path.includes('/config?')?denied?response({},403):response({config:{enabled,customer_visible:false}}):response({state:'not_enabled'})},
    getUser:()=>user,document:{visibilityState:'visible'}});
  try{
    panel.renderInto(node);await panel.refresh();assert.match(node.innerHTML,/还没开启/);
    enabled=true;await panel.refresh();assert.match(node.innerHTML,/项目已开启/);
    denied=true;await panel.refresh();
    assert.match(node.innerHTML,/点击本块右上方「项目设置」.*保存项目设置.*若已经开启，平台的搜索服务还没接通.*联系超管/);
    assert.doesNotMatch(node.innerHTML,/项目已开启|还没开启/);
  }finally{panel.dispose();}
});

test('run returning not-enabled reloads saved settings once and restores controls',async()=>{
  let overviewState='ready',runs=0;
  const node={innerHTML:''};
  const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async(path,options)=>{
    if(options.method==='POST'){runs++;overviewState='not_enabled';return response({state:'not_enabled'});}
    return response(path.includes('/config?')?{config:{enabled:true,customer_visible:false}}:{state:overviewState,latest:null,weeks:[]});
  }},getUser:()=>adminUser,document:{visibilityState:'visible'}});
  try{
    panel.renderInto(node);await panel.refresh();
    await node.onclick({target:{closest:()=>({dataset:{sv:'run'}})}});
    assert.equal(runs,1);assert.match(node.innerHTML,/项目已开启.*超管联系技术人员在服务器上配置搜索服务/);
    assert.doesNotMatch(node.innerHTML,/data-sv="refresh" disabled|待启用/);
  }finally{panel.dispose();}
});

test('404 and CSV state messages use role-specific plain language and never server detail',async()=>{
  for(const [identity,expected] of [[customerUser,/联系你的顾问/],[user,/项目设置.*保存项目设置.*联系超管/],[adminUser,/项目设置.*服务器上配置搜索服务/]]){
    const node={innerHTML:''};
    const panel=createSearchVisibilityPanel({host:{getContext:()=>context,transport:async()=>response({detail:'INTERNAL_CODE_FAKE'},404)},getUser:()=>identity,document:{visibilityState:'visible'}});
    panel.renderInto(node);await panel.refresh();
    if(identity!==customerUser){assert.match(node.innerHTML,expected);assert.doesNotMatch(node.innerHTML,/INTERNAL_CODE_FAKE|待启用/);}
    else assert.equal(node.innerHTML,'');
    panel.dispose();
  }
  const client=createSearchVisibilityClient({getContext:()=>context,transport:async()=>response({state:'not_enabled'})});
  await assert.rejects(client.csv(3),/这项检查还没开始.*联系你的顾问/);
});
