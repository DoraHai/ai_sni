import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';

const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
// Real browser and bundled UI, isolated HTTP fixtures: backend JWT/DB checks are
// separate integration tests. No provider calls or customer data are used here.
for(const module of ['seo','geo']){
 test(module+' customer sees advisor progress without gaining workflow controls, and clears denied results',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const origin='https://onsite-delivery.test',errors=[],calls=[];
  const scopeId=module==='seo'?9:10,field=module==='seo'?'site_id':'project_id';
  const permissions={'seo.site':'view','seo.content':'view','seo.keywords':'view','geo.assets':'view','geo.content':'view'};
  const query=new URLSearchParams({module,tenant_id:1,[field]:scopeId});
  const base=origin+'/customer-workbench/?'+query;
  const month=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7);
  const taskTitle='客户自己的站内任务';
  const row={id:77,module,tenant_id:1,scope_id:scopeId,title:taskTitle,
   workflow:{module,revision:1,phase:'review',month,work_type:'monthly',domain:'example.com',owner_name:'网站维护人员',advisor_user_id:7,source:{},history:[],
    items:[{id:'a',kind:module==='seo'?'title':'structured_content',target_url:'https://example.com/p',expected:'核实过的方案内容',instruction:'待顾问与实施人员处理'}]},
   capabilities:{ai_planning:{enabled:true,can_generate:false}},allowed_actions:[],completion_evidence:null};
  let denied=false,foreignResponse=false;
  try{
   const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));await p.setRequestInterception(true);
   await p.evaluateOnNewDocument(permissions=>sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'fixture-customer',user:{id:12,tenant_id:1,display_name:'客户',permissions}})),permissions);
   p.on('request',async req=>{
    const url=new URL(req.url());if(url.protocol==='data:')return req.continue();if(url.origin!==origin)return req.abort();
    const respond=(data,status=200)=>req.respond({status,contentType:'application/json',headers:{'Cache-Control':'no-store'},body:JSON.stringify(data)});
    if(url.pathname==='/api/v1/auth/me')return respond({user:{id:12,tenant_id:1,display_name:'客户',permissions}});
    if(url.pathname==='/api/v1/auth/modules')return respond({tenant_id:1,modules:[{module_code:'seo',available:true},{module_code:'geo',available:true}]});
    if(url.pathname==='/api/v1/geo/tenants')return respond({tenants:[{id:1,name:'客户1'}]});
    if(url.pathname==='/api/v1/geo/projects')return respond({projects:[{id:10,tenant_id:1,name:'项目1',status:'active'}]});
    if(url.pathname.startsWith('/api/v1/'+module+'/workbench/onsite-tasks')){
     calls.push({method:req.method(),path:url.pathname,tenant:url.searchParams.get('tenant_id'),scope:url.searchParams.get(field)});
     if(req.method()!=='GET')return respond({detail:'Customer writes denied'},403);
     if(denied)return respond({detail:'Assignment revoked'},403);
     const item=foreignResponse?{...row,scope_id:scopeId+1,title:'其他范围的机密任务'}:row;
     return respond({module,tenant_id:1,scope_id:scopeId,can_create:false,items:[item],next_before_id:null});
    }
    try{const r=await fetch(f.origin+url.pathname+url.search,{method:req.method(),headers:req.headers(),body:req.postData()});await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort();}
   });
   const noControls=async()=>{
    for(const action of ['create','ai-proposal','save_proposal','approve','implement','recheck','accept','cancel'])
     assert.equal(await p.$('[data-action="onsite-'+action+'"]'),null,action+' must remain advisor-only');
    assert.equal(await p.$('[data-action^="automation-"]'),null);
    assert.equal(await p.$('#onsite-note'),null);
    assert.equal(await p.$eval('#onsite-expected-a',e=>e.disabled),true);
    assert.equal(await p.$eval('#onsite-task-owner',e=>e.disabled),true);
   };
   const phases={review:'待人工审核',implementation:'待网站实施',recheck:'待系统复检',acceptance:'待人工验收',done:'交付已验收'};
   for(const [phase,label] of Object.entries(phases)){
    row.workflow.phase=phase;row.workflow.revision++;
    if(phase==='done')row.workflow.acceptance={actor:7,note:'顾问已核实实施与复检证据'};
    await p.goto(base);
    await p.waitForSelector('.customer-onsite-summary .customer-onsite-task');
    const summary=await p.$eval('.customer-onsite-task',e=>e.textContent);
    assert.ok(summary.includes(label),summary);
    assert.ok(summary.includes(phase==='done'?'已通过人工验收':'尚未确认交付完成'));
    assert.ok(summary.includes('本列表未提供效果结论'));
    const link=await p.$eval('.customer-onsite-task a',e=>e.getAttribute('href'));
    const target=new URL(link,origin);
    assert.equal(target.searchParams.get('onsite_task_id'),'77');
    assert.equal(target.searchParams.get(field),String(scopeId));
    await p.goto(target.href);await p.waitForSelector('#onsite-expected-a');
    assert.ok((await p.$eval('.onsite-detail',e=>e.textContent)).includes(taskTitle));
    await noControls();
   }
   await p.setViewport({width:390,height:844});
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);

   // A scoped endpoint accidentally returning a foreign task must not expose it.
   foreignResponse=true;await p.goto(base+'&onsite_task_id=77');
   await p.waitForFunction(()=>document.body.textContent.includes('CONTRACT_MISMATCH'));
   assert.equal(await p.$('.onsite-detail'),null);
   assert.equal((await p.$eval('body',e=>e.textContent)).includes('其他范围的机密任务'),false);

   foreignResponse=false;await p.goto(base+'&onsite_task_id=77');await p.waitForSelector('#onsite-expected-a');
   denied=true;await p.click('[data-action=onsite-refresh]');
   await p.waitForFunction(()=>!document.querySelector('.onsite-detail'));
   assert.equal((await p.$eval('body',e=>e.textContent)).includes(taskTitle),false);
   assert.equal(await p.$('.customer-onsite-task'),null);
   assert.equal(await p.$('#input-recovery'),null);

   assert.ok(calls.length>=12);assert.ok(calls.every(c=>c.method==='GET'&&c.tenant==='1'&&c.scope===String(scopeId)));
   assert.deepEqual(errors,[]);
  }finally{await browser.close();await f.close();}
 });
}
