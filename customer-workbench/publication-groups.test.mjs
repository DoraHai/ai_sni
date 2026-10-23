import test from 'node:test';
import assert from 'node:assert/strict';
import {createPublicationGroupsClient,validatePublicationPage,publicationGroupQuery,publicationGroupKey,publicationDetailKey,appendUnique} from './js/publication-groups-client.mjs';
import {publicationLink,publicationDetailView} from './js/publication-groups-panel.mjs';
import {publicationPage,receiptId,completePublicationPage} from './tests/publication-groups-fixture.mjs';
import {geoClientRoute,geoClientQuery} from './js/geo-client-routes.mjs';
import {createHostSessionAdapter} from './js/host-session-adapter.mjs';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';
import {geoHome,geoResource} from './js/geo-project-view.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {publicationListView} from './js/seo-data-view.mjs';
const ctx={connected:true,userId:7,tenantId:1,siteId:9,projectId:10,revision:1};
test('external success/failure never changes native evidence totals, legacy push receipts or project KPIs',async()=>{
  const deliveries=geoFixture('deliveries'),slots=Object.fromEntries(['overview','visibility','executions'].map(k=>[k,{value:geoFixture(k)}]));
  const seo={items:[{publication:{id:91,status:'published'},content:{id:88,title:'原生稿件'}}],total:1};
  const before=JSON.stringify({deliveries,slots,seo}),views=[geoResource('deliveries',deliveries),geoHome(slots),publicationListView(seo)];
  for(const module of ['seo','geo'])for(const external_records of [0,2,200]){
    const client=createPublicationGroupsClient({module,getContext:()=>ctx,transport:async()=>{
      const v=publicationPage(module);v.counts[module==='seo'?'external':'external_records']=external_records;return Response.json(completePublicationPage(v));
    }});
    const page=await client.read();assert.equal(page.counts.native_records,2);
    assert.equal(JSON.stringify({deliveries,slots,seo}),before);
    assert.deepEqual([geoResource('deliveries',deliveries),geoHome(slots),publicationListView(seo)],views);
  }
  assert.equal(deliveries.data.counts.published_records,1);
  assert.ok(deliveries.data.items.some(r=>r.record_type==='receipt'));
  assert.match(views[0],/原生投递回执/);
});
test('exact module/tenant/scope/article identity, source primary-key dedup, versions and URL/title collisions',()=>{
  const keys=[publicationGroupKey('seo',ctx,88),publicationGroupKey('geo',ctx,88),publicationGroupKey('seo',{...ctx,tenantId:2},88),publicationGroupKey('seo',{...ctx,siteId:10},88),publicationGroupKey('seo',ctx,89)];
  assert.equal(new Set(keys).size,5);
  const rows=publicationPage('geo',{article_id:88}).items;
  const result=appendUnique(rows,rows,r=>publicationDetailKey('geo',r));
  assert.equal(result.length,4);assert.equal(result[0].article_version_id,900);
  assert.equal(new Set(result.map(r=>r.url)).size,1);
  for(const unsafe of [0,-1,1.1,Number.MAX_SAFE_INTEGER+1,'88'])assert.throws(()=>publicationGroupKey('geo',ctx,unsafe));
  assert.equal(validatePublicationPage(publicationPage('geo',{article_id:88}),'geo',ctx,{article_id:88}).items.length,4);
  const collision=publicationPage('geo',{article_id:88});collision.items[0].task_id=900;
  assert.throws(()=>validatePublicationPage(collision,'geo',ctx,{article_id:88}));
});
test('client only requests exact scoped GET, rejects unsafe parameters and validates all response scope',async()=>{
  for(const module of ['seo','geo']){
    const calls=[],client=createPublicationGroupsClient({module,getContext:()=>ctx,transport:async(path,options)=>{calls.push({path,options});return Response.json(publicationPage(module,{article_id:88}));}});
    await client.read({article_id:88});assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.body,undefined);
    assert.equal(calls[0].path,module==='seo'?'/api/v1/seo/workbench/publication-groups?tenant_id=1&site_id=9&article_id=88':'/api/v1/geo/projects/10/client/publication-groups?tenant_id=1&article_id=88');
    for(const params of [{bucket:'invalid'},{scope_id:10},{site_id:9},{task_id:88},{article_id:9007199254740992},{article_id:'08'},{limit:101},{bucket:'unlinked',article_id:88},{cursor:''},{owner_user_id:7}])await assert.rejects(client.read(params),/PUBLICATION_QUERY_DENIED/);
    for(const mutate of [v=>v.context.tenant_id=2,v=>v.context.scope_id=19,v=>v.context.module='unknown',v=>v.context.bucket='unlinked',v=>v.read_only=false,v=>{if(module==='seo')v.completeness='incomplete';else v.completeness.complete=false},v=>v.counts[module==='seo'?'native':'native_records']=-1,v=>v.items[0].group_article_id=89,v=>v.items[0].external_receipt_id=receiptId(9)]){
      const v=publicationPage(module,{article_id:88});mutate(v);assert.throws(()=>validatePublicationPage(v,module,ctx,{article_id:88}));
    }
    client.invalidate();
  }
});
test('5101 groups and 101 details paginate independently without merging same URL or title',async()=>{
  const all=Array.from({length:5101},(_,i)=>({group_article_id:6000-i,title:'同名',content_id:6000-i,task_id:null,module:'seo',tenant_id:1,scope_id:9,native_count:1,external_count:0}));
  const client=createPublicationGroupsClient({module:'seo',getContext:()=>ctx,transport:async path=>{
    const p=new URL(path,'https://fixture.test').searchParams,offset=Number(p.get('cursor')||0),v=publicationPage();
    v.items=all.slice(offset,offset+100);v.counts.articles=5101;v.has_more=offset+100<all.length;v.next_cursor=v.has_more?String(offset+100):null;return Response.json(completePublicationPage(v));
  }});
  let groups=[],cursor;
  do{const page=await client.read({limit:100,...(cursor?{cursor}:{})});groups=appendUnique(groups,page.items,r=>publicationGroupKey('seo',ctx,r.group_article_id));cursor=page.next_cursor;}while(cursor);
  assert.equal(groups.length,5101);
  const row=publicationPage('geo',{article_id:88}).items[0],details=Array.from({length:101},(_,i)=>({...row,native_publication_id:i+1}));
  assert.equal(appendUnique(details.slice(0,100),details.slice(99),r=>publicationDetailKey('geo',r)).length,101);
  const detailClient=createPublicationGroupsClient({module:'geo',getContext:()=>ctx,transport:async path=>{
    const query=new URL(path,'https://fixture.test').searchParams,offset=Number(query.get('cursor')||0),v=publicationPage('geo',{article_id:88});
    v.items=details.slice(offset,offset+100);v.has_more=offset+100<101;v.next_cursor=v.has_more?'100':null;
    return Response.json(completePublicationPage(v));
  }});
  const first=await detailClient.read({article_id:88,limit:100});
  const last=await detailClient.read({article_id:88,limit:100,cursor:first.next_cursor});
  assert.equal(appendUnique(first.items,last.items,r=>publicationDetailKey('geo',r)).length,101);
});
test('context switch, invalidate and async JSON prevent late response from crossing permissions',async()=>{
  for(const switchContext of [true,false]){
    let c={...ctx},finish;
    const client=createPublicationGroupsClient({module:'seo',getContext:()=>c,transport:()=>new Promise(resolve=>finish=resolve)});
    const pending=client.read();if(switchContext)c={...c,revision:2};else client.invalidate();finish(Response.json(publicationPage()));
    await assert.rejects(pending,/PUBLICATION_CONTEXT_CHANGED/);
  }
  let c={...ctx},finish;
  const client=createPublicationGroupsClient({module:'seo',getContext:()=>c,transport:async()=>({ok:true,json:()=>new Promise(resolve=>finish=resolve)})});
  const pending=client.read();await Promise.resolve();c={...c,siteId:19};finish(publicationPage());await assert.rejects(pending,/PUBLICATION_CONTEXT_CHANGED/);
});
test('failure is explicit and external reports never become native verification badges',async()=>{
  for(const status of [403,409,422,503]){
    const client=createPublicationGroupsClient({module:'seo',getContext:()=>ctx,transport:async()=>new Response('',{status})});
    await assert.rejects(client.read(),e=>e.status===status);
  }
  const row=publicationPage('geo',{article_id:88}).items[2];
  for(const status of ['success','failed','pending_review','unknown']){
    const html=publicationDetailView({...row,status,verification:{status:'核验通过'}});
    assert.match(html,/操作人报告/);assert.match(html,/正文暂不可核验/);assert.doesNotMatch(html,/核验通过/);
  }
  for(const url of ['javascript:alert(1)','data:text/html,test','https://user:pass@example.test','//example.test'])assert.doesNotMatch(publicationLink(url),/<a /);
  assert.match(publicationLink('https://example.com/?a=1&b=2'),/a=1&amp;b=2/);
  for(const query of ['token=synthetic','%61ccess_token=synthetic','Api_Key=synthetic','pwd=synthetic']){
    const html=publicationLink('https://example.com/?'+query);
    assert.doesNotMatch(html,/<a |synthetic/);
  }
  assert.doesNotMatch(publicationDetailView({...row,channel:'<img src=x onerror=alert(1)>'}),/<img/);
});
test('GEO new route query matrix accepts only scoped GET projection queries',()=>{
  const path='/api/v1/geo/projects/10/client/publication-groups',route=geoClientRoute(path);
  assert.ok(route);assert.ok(geoClientQuery(new URL('https://fixture.test'+path+'?tenant_id=1&bucket=linked&article_id=88&limit=100&cursor=detail1'),route,ctx));
  for(const query of ['tenant_id=2','tenant_id=1&tenant_id=1','tenant_id=1&bucket=invalid','tenant_id=1&scope_id=10','tenant_id=1&project_id=10','tenant_id=1&bucket=unlinked&article_id=88','tenant_id=1&article_id=9007199254740992'])assert.equal(geoClientQuery(new URL('https://fixture.test'+path+'?'+query),route,ctx),false);
  for(const path of ['/api/v1/geo/projects/10/client/publication-groups/','/api/v1/geo/projects/10/client/%70ublication-groups','/api/v1/geo/distribution/v2/publication-groups'])assert.equal(geoClientRoute(path),null);
});
async function hostFor(module,permissions){
  let session={token:'synthetic-only',userId:7,tenantId:1,siteId:9,projectId:10,revision:1},calls=[];
  const fetchImpl=async raw=>{
    const path=new URL(raw).pathname;calls.push(path);
    return Response.json(path==='/api/v1/auth/me'?{user:{id:7,tenant_id:1,permissions}}:path==='/api/v1/auth/modules'?{tenant_id:1,modules:[{module_code:module,available:true}]}:path==='/api/v1/auth/tenants'?{module:'seo',tenants:[{id:1}]}:path.endsWith('/sites')?{tenant_id:1,sites:[{id:9,status:'active'}],selection_policy:{selectable_statuses:['active']}}:path.endsWith('/tenants')?{tenants:[{id:1}]}:path==='/api/v1/geo/projects'?{projects:[{id:10,tenant_id:1,status:'active'}]}:publicationPage(module));
  };
  const host=(module==='seo'?createHostSessionAdapter:createGeoHostAdapter)({origin:'https://fixture.test',getSession:()=>session,fetchImpl,readOnly:true});
  await host.initialize();calls.length=0;return {host,calls};
}
test('host adapters expose exactly two new GET routes; reject internal, label, method/path/query bypass',async()=>{
  for(const module of ['seo','geo']){
    const {host,calls}=await hostFor(module,{[module+'.content']:'view',[module==='seo'?'seo.site':'geo.assets']:'view'});
    const path=module==='seo'?'/api/v1/seo/workbench/publication-groups?tenant_id=1&site_id=9':'/api/v1/geo/projects/10/client/publication-groups?tenant_id=1';
    await host.transport(path);assert.equal(calls.length,1);
    for(const bad of [path+'&bucket=invalid',path+'&owner_user_id=7',path+'&tenant_id=1',path.replace('publication-groups','publication-groups/'),path.replace('publication-groups','%70ublication-groups'),`/api/v1/${module}/distribution/v2/publication-groups?tenant_id=1&scope_id=9`,`/api/v1/${module}/distribution/v2/receipts/${receiptId(1)}/label?tenant_id=1`])await assert.rejects(host.transport(bad));
    for(const method of ['POST','PATCH','PUT','DELETE'])await assert.rejects(host.transport(path,{method}));
    assert.equal(calls.length,1);host.dispose();
  }
  const {host,calls}=await hostFor('seo',{'seo.content':'view'});await assert.rejects(host.transport('/api/v1/seo/workbench/publication-groups?tenant_id=1&site_id=9'),/PERMISSION_DENIED/);assert.equal(calls.length,0);host.dispose();
});
