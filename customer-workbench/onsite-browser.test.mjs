import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
for(const module of ['seo','geo']){
 test(module+' onsite workbench safely drafts AI proposals, opens exact task links and completes human steps',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const origin='https://onsite.test',errors=[],writes=[];let aiReads=0;
  const kind=module==='seo'?'title':'structured_content';
  let row={id:77,module,tenant_id:1,scope_id:module==='seo'?9:10,title:'站内任务',
   workflow:{module,revision:1,phase:'draft',items:[{id:'a',kind,target_url:'https://example.com/p',expected:'审核文字',instruction:'核对事实'}],month:'2026-10',work_type:'monthly',domain:'example.com',owner_name:'维护人员',advisor_user_id:7,source:{},history:[]},
   capabilities:{ai_planning:{enabled:true,can_generate:true}},allowed_actions:['save_proposal','cancel'],completion_evidence:null};
  try{
   const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));await p.setRequestInterception(true);
   const ready=revision=>p.waitForFunction(revision=>document.querySelector('.onsite-detail h3')?.textContent.includes('v'+revision)&&document.querySelector('[data-action=onsite-refresh]')?.disabled===false,{},revision);
   const permissions={'seo.site':'edit','seo.content':'edit','seo.keywords':'edit','geo.assets':'edit','geo.content':'edit'};
   await p.evaluateOnNewDocument(permissions=>{sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-advisor',user:{id:7,tenant_id:null,display_name:'顾问',permissions}}));},permissions);
   p.on('request',async req=>{
    const url=new URL(req.url());if(url.protocol==='data:')return req.continue();if(url.origin!==origin)return req.abort();
    const respond=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)});
    if(url.pathname==='/api/v1/auth/me')return respond({user:{id:7,tenant_id:null,display_name:'顾问',permissions}});
    if(url.pathname==='/api/v1/auth/modules')return respond({tenant_id:null,modules:[{module_code:'seo',available:true},{module_code:'geo',available:true}]});
    if(url.pathname==='/api/v1/geo/tenants')return respond({tenants:[{id:1,name:'客户1'}]});
    if(url.pathname==='/api/v1/geo/projects')return respond({projects:[{id:10,tenant_id:1,name:'项目1',status:'active'}]});
    if(url.pathname.startsWith('/api/v1/'+module+'/workbench/onsite-tasks')){
     if(req.method()==='GET'){
      if(url.pathname.includes('/ai-requests/')){
       assert.equal(url.pathname.split('/').at(-1),row.workflow.ai_run.request_id);
       row.workflow.ai_run.state=++aiReads%2?'running':'ready';
       if(row.workflow.ai_run.state==='ready'){
        row.workflow.phase='review';row.workflow.revision++;
        row.workflow.ai_proposal={summary:'<script>throw new Error("unsafe")</script>',items:[{id:'a',reason:'已授权页面与资料',source_refs:['事实 #2']}]};
        row.allowed_actions=['save_proposal','cancel','approve'];row.capabilities.ai_planning.can_generate=true;
       }
       return respond({...row,request_run:row.workflow.ai_run});
      }
      return respond({module,tenant_id:1,scope_id:row.scope_id,can_create:true,items:[row],next_before_id:null});
     }
     const body=JSON.parse(req.postData());writes.push(body);assert.equal(body.expected_revision,row.workflow.revision);
     if(url.pathname.endsWith('/ai-proposal')){
      assert.match(body.request_id,/^[a-f0-9-]{36}$/);assert.equal(body.mode,row.workflow.phase==='draft'?'initial':'revise');
      row.workflow.ai_run={request_id:body.request_id,state:'queued'};
      row.allowed_actions=['cancel'];row.capabilities.ai_planning.can_generate=false;return respond(row,202);
     }
     if(body.action==='save_proposal'){row.workflow.items=body.items;row.workflow.phase='review';}
     const phases={approve:'implementation',implement:'recheck',recheck:'acceptance',accept:'done'};
     if(phases[body.action])row.workflow.phase=phases[body.action];
     row.workflow.revision++;
     if(body.action==='recheck')row.workflow.recheck={at:'2026-10-10T12:00:00Z',passed:true,results:[{id:'a',target_url:'https://example.com/p',passed:true}]};
     if(body.action==='accept')row.workflow.acceptance={actor:7,note:body.note};
     row.allowed_actions=row.workflow.phase==='done'?[]:['save_proposal','cancel',({review:'approve',implementation:'implement',recheck:'recheck',acceptance:'accept'})[row.workflow.phase]].filter(Boolean);
     return respond(row);
    }
    try{const r=await fetch(f.origin+url.pathname+url.search,{method:req.method(),headers:req.headers(),body:req.postData()});await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort();}
   });
   await p.goto(origin+'/customer-workbench/?'+(module==='seo'?'tenant_id=1&site_id=9':'module=geo&tenant_id=1&project_id=10')+'&onsite_task_id=77');
   await p.waitForSelector('#onsite-expected-a');
   await ready(1);
   await p.type('#onsite-expected-a','未保存改动');await p.click('[data-action=onsite-ai-proposal]');
   await p.waitForFunction(()=>document.body.textContent.includes('未保存修改'));assert.equal(writes.length,0);
   await p.$eval('#onsite-expected-a',e=>{e.value='审核文字';e.dispatchEvent(new Event('input',{bubbles:true}));});
   await p.click('[data-action=onsite-ai-proposal]');
   await p.waitForFunction(()=>document.body.textContent.includes('AI 方案已排队'));
   assert.equal(await p.$('[data-action=onsite-ai-proposal]'),null);
   assert.equal(await p.$('[data-action=onsite-approve]'),null);
   await p.reload();await p.waitForSelector('[data-action=onsite-approve]');
   assert.equal(writes.length,1);assert.equal(aiReads,2);
   await ready(2);
   assert.equal(await p.$('.onsite-detail script'),null);assert.equal(writes.length,1);
   await p.click('[data-action=onsite-save_proposal]');
   await p.waitForSelector('[data-action=onsite-approve]');
   await ready(3);
   await p.click('[data-action=onsite-ai-proposal]');
   await ready(4);
   assert.equal(writes.at(-1).mode,'revise');
   await p.type('#onsite-expected-a','未保存改动');await p.type('#onsite-note','审核依据');
   await p.click('[data-action=onsite-approve]');await p.waitForFunction(()=>document.body.textContent.includes('未保存修改'));
   assert.equal(writes.length,3);
   await p.$eval('#onsite-expected-a',e=>{e.value='审核文字';e.dispatchEvent(new Event('input',{bubbles:true}));});
   for(const action of ['approve','implement','recheck','accept']){
    await p.$eval('#onsite-note',e=>{e.value='人工核对事实及实施依据';e.dispatchEvent(new Event('input',{bubbles:true}));});
    await p.click('[data-action=onsite-'+action+']');
    const next={approve:'implement',implement:'recheck',recheck:'accept',accept:null}[action];
    if(next)await p.waitForSelector('[data-action=onsite-'+next+']');
    else await p.waitForFunction(()=>document.body.textContent.includes('人工验收：'));
    await ready({approve:5,implement:6,recheck:7,accept:8}[action]);
   }
   assert.deepEqual(writes.map(w=>w.mode?'ai-proposal':w.action),['ai-proposal','save_proposal','ai-proposal','approve','implement','recheck','accept']);
   assert.equal(await p.$('[data-action=onsite-accept]'),null);
   if(module==='seo'){
    await p.waitForFunction(()=>!document.querySelector('.navigation [data-page="首页"]').disabled);
    await p.click('.navigation [data-page="首页"]');
   }else{
    await p.waitForFunction(()=>!document.querySelector('[data-action=onsite-latest]').disabled);
    await p.click('[data-action=onsite-latest]');
   }
   try{await p.waitForSelector('.customer-onsite-summary .customer-onsite-task',{timeout:10000});}
   catch(e){throw Error('Summary failed: '+await p.$eval('body',el=>el.textContent.slice(0,4500)),{cause:e});}
   assert.match(await p.$eval('.customer-onsite-task',el=>el.textContent),/已通过人工验收/);
   assert.match(await p.$eval('.customer-onsite-task a',el=>el.getAttribute('href')),/onsite_task_id=77/);
   await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(errors,[]);
  }finally{await browser.close();await f.close();}
 });
}

