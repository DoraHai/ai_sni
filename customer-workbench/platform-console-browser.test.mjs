import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import {existsSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {platformAlertArchive} from './js/platform-alert-archive.mjs';
const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const admin={id:7,username:'platform-admin',display_name:'平台管理员',tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const source=rows=>({state:'available',total:rows.length,rows,truncated:false});
const snapshot={schema:1,mode:'read_only_inventory',generated_at:'2026-10-09T16:00:00Z',
  sources:{tenants:source([{id:1,name:'测试客户 A',industry:'制造业'},{id:2,name:'客户 <img src=x onerror=alert(1)>',industry:'服务业'}]),
    users:source([{id:7,username:'platform-admin',display_name:'平台管理员',tenant_id:null,role_id:1,is_active:true,last_login_at:'2026-10-09T14:00:00Z'},
      {id:8,username:'customer-a',tenant_id:1,role_id:2,is_active:true,last_login_at:null}]),
    roles:source([{id:1,name:'管理员',permissions:admin.permissions},{id:2,name:'客户',permissions:{'seo.content':'view'}}]),
    tenant_modules:source([{id:1,tenant_id:1,module_code:'seo',status:'active',expires_at:'2027-01-01'},{id:2,tenant_id:1,module_code:'geo',status:'active',expires_at:null}]),
    seo_sites:source([{id:9,tenant_id:1,name:'官网',domain:'example.test',status:'active'}]),geo_projects:source([{id:1,tenant_id:1,name:'品牌项目',primary_domain:'example.test',status:'active'}]),
    api_audit_logs:source([{id:1,tenant_id:1,endpoint:'/v1/search',status_code:200,latency_ms:90,request_id:'request-1',created_at:'2026-10-09T15:00:00Z'}]),
    geo_tracking_engines:source([{id:1,tenant_id:1,display_name:'采样引擎',sample_mode:'mock_persona',model:null,enabled:true}]),
    sem_tasks:source([]),seo_tasks:source([{id:1,tenant_id:1,title:'网站检查',status:'open',updated_at:'2026-10-09T15:00:00Z'}]),
    geo_async_jobs:source([{id:1,tenant_id:1,kind:'generate_article',status:'failed',created_at:'2026-10-09T15:00:00Z'}]),geo_action_tickets:source([]),baidu_oauth_grants:source([])},
  calls:{total:3,failed:1,average_latency_ms:90},alerts:[{tenant_id:1,message:'GEO 异步任务失败',severity:'error'}],
  costs:{actual_amount:null,estimated_amount:null,date:'2026-10-10',note:'已有部分调用次数与抓取配额；尚未统一记录金额。',usage:[{tenant_id:1,ai_requests:4,chat_requests:2,crawl_urls:8}]},
  coverage:{api:'已有审计记录，尚未覆盖所有服务商调用。',credentials:'运行密钥由服务器管理。',backup:'备份记录尚未接入。',audit:'统一审计尚未接入。'}};

test('built superadmin console uses real-shaped data, all tabs and strict identity boundaries',async()=>{
  const f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  const origin='https://workbench.test',requests=[],errors=[],external=[];
  let serverUser=admin,status=200,held=null;const connectionWrites=[],usageQueries=[],operationWrites=[];let exports=0;
  try{
    const p=await browser.newPage();await p.setViewport({width:1440,height:1000});
    p.on('pageerror',e=>errors.push(e.message));await p.setRequestInterception(true);
    p.on('request',async r=>{
      const u=new URL(r.url());if(u.protocol==='data:')return r.continue();
      if(u.origin!==origin){external.push(u.href);return r.abort();}
      if(u.pathname.startsWith('/api/')){
        requests.push({path:u.pathname,method:r.method()});
        if(u.pathname.endsWith('/usage/export')){
          exports++;assert.equal(r.headers().authorization,'Bearer fixture-admin');
          return r.respond({status:200,contentType:'text/csv',body:'\ufeffid,estimated_amount\ncomplete-history,\n'});
        }
        if(u.pathname.endsWith('/usage')){
          usageQueries.push(Object.fromEntries(u.searchParams));
          const next=u.searchParams.has('cursor');
          return r.respond({status:200,contentType:'application/json',body:JSON.stringify({state:'available',total:2,unpriced:1,known_amount:'0.01',estimated_amount:null,
            as_of:'2026-10-10T01:00:00Z',next_cursor:next?null:'fixture-next-page',rows:[{id:next?'history-second':'history-first',tenant_id:1,user_id:8,module:'seo',provider:'chinaz',
              model:null,endpoint:'openapi.chinaz.net/v1/index',state:'succeeded',started_at:'2026-10-10T01:00:00Z',estimated_amount:next?'0.01':null,currency:'CNY'}]})});
        }
        if(u.pathname.endsWith('/operations')){
          const data=JSON.parse(r.postData());operationWrites.push(data);
          if(data.kind==='alert'){
            const alert=snapshot.alerts.find(a=>a.id===data.key);
            assert.equal(data.expected_revision,alert.handling.revision);alert.handling.revision++;
            alert.handling.status=data.value.action==='resolve'?'resolved':'in_progress';alert.handling.owner_id=7;alert.handling.note=data.value.note;
          }else snapshot.operations.suppliers=[{host:data.key,...data.value,revision:1,source:'manual',updated_at:'2026-10-10T01:00:00Z'}];
          return r.respond({status:200,contentType:'application/json',body:JSON.stringify({revision:1})});
        }
        if(u.pathname.endsWith('/controls')){
          const payload=JSON.parse(r.postData());
          assert.equal(r.headers().authorization,'Bearer fixture-admin');
          if(payload.kind!=='connection')assert.equal(payload.expected_revision,0);
          const c=snapshot.controls;
          if(payload.kind==='connection'){
            connectionWrites.push(structuredClone(payload));
            const row=c.connections.find(row=>'connection:'+row.id===payload.key);
            assert.equal(payload.expected_revision,row.revision);
            row.revision++;
            const visible=Object.fromEntries(Object.entries(payload.value.secrets).map(([k,v])=>[k,Boolean(v)]));
            if(payload.value.restore){row.parameters.model='deepseek-chat';row.secret_status.api_key=false;row.source='server';}
            else {Object.assign(row.parameters,payload.value.parameters);Object.assign(row.secret_status,visible);row.source='managed';}
            c.audit.push({id:payload.request_id,actor_id:7,resource:payload.key,action:'connection.update',after_value:{parameters:row.parameters,secrets:row.secret_status},created_at:'2026-10-10T01:00:00Z'});
            return r.respond({status:200,contentType:'application/json',body:JSON.stringify({revision:row.revision})});
          }else if(payload.kind==='credential'){
            assert.equal(payload.value.key,'fixture-private-replacement');
            c.credentials.push({id:payload.key,revision:1,overridden:true});
          }else c.settings.push({key:payload.key,kind:payload.kind,revision:1,value:payload.value});
          c.audit.push({id:payload.request_id,actor_id:7,resource:payload.key,action:payload.kind+'.update',before_value:null,after_value:payload.kind==='credential'?{overridden:true,revision:1}:payload.value,created_at:'2026-10-10T01:00:00Z'});
          return r.respond({status:200,contentType:'application/json',body:JSON.stringify({revision:1})});
        }
        const body=u.pathname.endsWith('/login')?{token:'fixture-admin',user:serverUser}:u.pathname.endsWith('/me')?{user:serverUser}:snapshot;
        if(u.pathname.endsWith('/snapshot')&&held)await held;
        return r.respond({status:u.pathname.endsWith('/snapshot')?status:200,contentType:'application/json',body:JSON.stringify(body)}).catch(()=>{});
      }
      try{const response=await fetch(f.origin+u.pathname+u.search);await r.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});}catch{await r.abort().catch(()=>{});}
    });
    const signIn=async()=>{await p.waitForSelector('#pc-login');await p.type('[name=username]','platform-admin');await p.type('[name=password]','fixture-password');await p.click('#pc-login button');};
    const body=()=>p.evaluate(()=>document.body.textContent);
    await p.goto(origin+'/customer-workbench/?console=platform');await signIn();await p.waitForSelector('.pc-kpis');
    assert.equal(await p.title(),'超级管理员工作台 · G-SNIPERS');assert(!await p.$('.chat'));assert(!await p.$('.composer'));assert.match(await body(),/本月 API 估算待接入/);
    await p.screenshot({path:path.join(os.tmpdir(),'platform-admin-overview-20261010.png'),fullPage:true});
    const pages={customers:'客户与服务',accounts:'账号管理',apis:'API 调用情况',costs:'平台成本',tasks:'SEO 执行任务',security:'数据与权限',inventory:'系统盘点'};
    for(const [tab,label] of Object.entries(pages)){
      await p.click(`.pc-sidebar [data-pc-page=${tab}]`);assert.match(await body(),new RegExp(label));
    }
    await p.click('.pc-sidebar [data-pc-page=customers]');assert(!await p.$('.pc-table-wrap img'));
    await p.type('#pc-search','制造');assert.match(await body(),/测试客户 A/);assert.doesNotMatch(await p.$eval('.pc-content',e=>e.textContent),/客户 <img/);
    await p.click('.pc-sidebar [data-pc-page=costs]');assert.match(await body(),/不能相加/);assert.doesNotMatch(await body(),/¥0|￥0/);
    // Forward metering includes inactive and zero-activity accounts, and keeps
    // an unknown total separate from its known subtotal.
    snapshot.sources.users.rows.push(...Array.from({length:6},(_,i)=>({id:20+i,username:'no-calls-'+i,tenant_id:1,role_id:2,is_active:i!==0})));
    snapshot.sources.users.total=8;
    snapshot.api_costs={state:'recording',period:'2026-10',note:'本月真实外部请求的 API 原价估算',calls:3,pending:0,unpriced:1,known_amount:'0.006',estimated_amount:null,
      user_totals:[{user_id:8,calls:2,input_tokens:1000,output_tokens:500,known_amount:'0.006',estimated_amount:'0.006',unpriced:0},{user_id:null,calls:1,input_tokens:0,output_tokens:0,known_amount:'0',estimated_amount:null,unpriced:1}],
      tenant_totals:[{tenant_id:1,calls:3,input_tokens:1000,output_tokens:500,known_amount:'0.006',estimated_amount:null,unpriced:1}],
      provider_totals:[{module:'seo',provider:'chinaz',endpoint:'openapi.chinaz.net/v1/keyword_360mobile',calls:308,known_amount:'0',unpriced:308}],unattributed:{calls:0,input_tokens:0,output_tokens:0,known_amount:'0',estimated_amount:'0',unpriced:0},recent:[]};
    await p.click('[data-pc=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('本月 API 费用'));
    assert.match(await body(),/全部 8 个登录账号/);assert.match(await body(),/no-calls-0/);assert.match(await body(),/已停用/);
    assert.match(await body(),/¥0.006/);assert.match(await body(),/待定价/);assert.match(await body(),/系统任务/);
    // A cleared reminder stays gone on refresh while the source accounting and
    // failed job records remain available. A new incident must reappear.
    const previousAlerts=snapshot.alerts,previousTime=snapshot.generated_at;
    snapshot.generated_at='2026-10-10T08:00:00Z';
    snapshot.controls={state:'schema_pending'};
    snapshot.alerts=platformAlertArchive.items.map(([id,signal],i)=>({id,signal,tenant_id:1,
      message:'历史测试告警 '+i,severity:'error',handling:{status:'open'}}));
    await p.click('[data-pc=refresh]');
    await p.waitForFunction(()=>document.querySelector('.pc-right .pc-tag')?.textContent==='0');
    assert.doesNotMatch(await p.$eval('.pc-right',e=>e.textContent),/历史测试告警|尚未定价|尚未启用/);
    assert.match(await p.$eval('.pc-content',e=>e.textContent),/¥0.006|待定价/);
    assert.equal(snapshot.sources.geo_async_jobs.rows[0].status,'failed');
    await p.click('.pc-sidebar [data-pc-page=alerts]');
    assert.equal(await p.$('#pc-alert-operation'),null);
    snapshot.alerts[0]={...snapshot.alerts[0],signal:'new-failure-after-clear',message:'清空后新发生的异常'};
    await p.click('[data-pc=refresh]');
    await p.waitForFunction(()=>document.querySelector('.pc-right .pc-tag')?.textContent==='1');
    assert.match(await p.$eval('.pc-right',e=>e.textContent),/清空后新发生的异常/);
    assert.match(await p.$eval('.pc-content',e=>e.textContent),/清空后新发生的异常/);
    snapshot.alerts=previousAlerts;snapshot.generated_at=previousTime;
    snapshot.controls={state:'enabled',settings:[],budgets:[],audit:[],credentials:[],default_rates:[{host:'dashscope.aliyuncs.com',model:'deepseek-v4-flash',input:'1',output:'2',max_input:1000000,source:'approved price'}],
      connections:[{id:'seo.deepseek',module:'seo',label:'DeepSeek 官方',registered:true,supported:true,source:'server',revision:0,
        parameters:{enabled:true,model:'deepseek-chat',base_url:'https://api.deepseek.com/v1'},secret_status:{api_key:false},
        fields:[{name:'enabled',type:'boolean',label:'平台默认配置启用'},{name:'model',type:'model',label:'默认模型'},{name:'base_url',type:'url',label:'接口地址'}],
        secret_fields:[{name:'api_key',label:'API Key'}]}],
      bindings:[{id:'a'.repeat(64),module:'seo',label:'dashscope',host:'dashscope.aliyuncs.com',model:'deepseek-v4-flash',configured:true,can_rotate:true}]};
    snapshot.api_costs.recent=[{id:'meter-request',tenant_id:1,model:'deepseek-v4-flash',endpoint:'dashscope.aliyuncs.com/v1',state:'succeeded',latency_ms:33,started_at:'2026-10-10T00:00:00Z'}];
    await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');
    await p.click('.pc-sidebar [data-pc-page=apis]');assert.match(await body(),/meter-request/);assert.doesNotMatch(await body(),/request-1/);assert.match(await body(),/站长之家/);assert.match(await body(),/keyword_360mobile/);assert.match(await body(),/308/);
    await p.select('#pc-usage-query [name=tenant_id]','1');await p.click('#pc-usage-query button');
    await p.waitForFunction(()=>document.body.textContent.includes('history-first'));
    assert.equal(usageQueries[0].tenant_id,'1');assert.match(await body(),/未定价 1 条/);
    await p.click('[data-pc=usage-next]');await p.waitForFunction(()=>document.body.textContent.includes('history-second'));
    assert.equal(usageQueries[1].cursor,'fixture-next-page');assert.match(await body(),/第 2 页/);
    await p.click('[data-pc=usage-prev]');await p.waitForFunction(()=>document.body.textContent.includes('history-first'));
    assert(!('cursor' in usageQueries[2]));assert.match(await body(),/第 1 页/);
    await p.screenshot({path:path.join(os.tmpdir(),'platform-usage-history-20261010.png'),fullPage:true});
    await p.click('[data-pc=usage-export]');await p.waitForFunction(()=>document.querySelector('.pc-save-notice')?.textContent.includes('已导出'));
    assert.equal(exports,1);
    snapshot.operations={state:'enabled',provider_health:[{module:'seo',provider:'chinaz',calls:10,failed:3,last_failure:'2026-10-10T01:00:00Z'}],suppliers:[],
      backup:{state:'available',note:'数据库备份与恢复验证分别记录。',records:[{completed_at:'2026-10-10T01:00:00Z',state:'succeeded',archive_verified:true,restore_verified:false}]}};
    snapshot.alerts=[{id:'a'.repeat(64),signal:'b'.repeat(64),tenant_id:1,message:'测试接口异常',severity:'error',handling:{status:'open',revision:0}}];
    await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');
    await p.click('.pc-sidebar [data-pc-page=alerts]');await p.click('#pc-alert-operation button');
    await p.waitForFunction(()=>document.querySelector('.pc-content')?.textContent.includes('处理中'));
    assert.equal(operationWrites[0].value.action,'claim');
    await p.select('#pc-alert-operation [name=action]','resolve');await p.type('#pc-alert-operation [name=note]','已检查上游服务，等待下一次调用确认');
    await p.click('#pc-alert-operation button');await p.waitForFunction(()=>document.querySelector('.pc-content')?.textContent.includes('已标记处理'));
    assert.equal(operationWrites[1].expected_revision,1);
    await p.type('#pc-supplier-operation [name=remaining_calls]','0');await p.type('#pc-supplier-operation [name=warning_calls]','10');
    await p.click('#pc-supplier-operation button');await p.waitForFunction(()=>document.querySelector('.pc-save-notice')?.textContent.includes('已保存')&&document.querySelector('#pc-supplier-operation [name=remaining_calls]')?.value==='0');
    await p.waitForFunction(()=>document.querySelector('#pc-supplier-operation')?.closest('.pc-card').querySelector('tbody tr')?.textContent.includes('dashscope.aliyuncs.com'));
    assert.equal(operationWrites[2].value.balance,null);assert.equal(operationWrites[2].value.remaining_calls,0);
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.setViewport({width:1440,height:1000});
    await p.screenshot({path:path.join(os.tmpdir(),'platform-alert-operations-20261010.png'),fullPage:true});
    await p.click('.pc-sidebar [data-pc-page=config]');await p.waitForSelector('[data-control-kind=connection]');
    const connection='[data-control-kind=connection]';
    assert.equal(await p.$eval(connection+' button',e=>e.disabled),false);
    await p.type('[data-connection-secret=api_key]','first-platform-private-key');
    await p.click(connection+' button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=connection] [name=revision]')?.value==='1');
    assert.equal(connectionWrites[0].value.secrets.api_key,'first-platform-private-key');
    assert.equal(await p.$eval('[data-connection-secret=api_key]',e=>e.value),'');
    assert.doesNotMatch(await body(),/first-platform-private-key/);
    await p.click(connection+' button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=connection] [name=revision]')?.value==='2');
    assert.deepEqual(connectionWrites[1].value.secrets,{});
    await p.type('[data-connection-secret=api_key]','should-clear-on-restore');
    await p.select('[name=connection_mode]','restore');
    assert.equal(await p.$eval('[data-connection-secret=api_key]',e=>e.value),'');
    await p.click(connection+' button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=connection] [name=revision]')?.value==='3');
    assert.deepEqual(connectionWrites[2].value,{parameters:{},secrets:{},restore:true});
    await p.screenshot({path:path.join(os.tmpdir(),'platform-system-config-20261010.png'),fullPage:true});
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.setViewport({width:1440,height:1000});
    snapshot.controls.state='ready';await p.click('[data-pc=refresh]');await p.waitForSelector(connection);
    assert.equal(await p.$eval(connection+' button',e=>e.disabled),true);
    snapshot.controls.state='enabled';await p.click('[data-pc=refresh]');await p.waitForSelector(connection);
    await p.type('[data-connection-secret=api_key]','revoked-private-input');serverUser={...admin,tenant_id:1};await p.click(connection+' button');
    await p.waitForFunction(()=>document.body.textContent.includes('无法保存管理配置'));assert.equal(connectionWrites.length,3);assert.doesNotMatch(await body(),/revoked-private-input/);
    serverUser=admin;await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');
    await p.click('.pc-sidebar [data-pc-page=controls]');await p.waitForSelector('.pc-control-form');
    await p.select('[data-control-kind=budget] [name=target]','user:8');
    await p.type('[data-control-kind=budget] [name=daily_calls]','10');
    await p.click('[data-control-kind=budget] button');await p.waitForFunction(()=>document.querySelector('.pc-save-notice')?.textContent.includes('已保存'));
    assert.equal(snapshot.controls.settings.find(r=>r.key==='budget:user:8').value.daily_calls,10);
    await p.select('[data-control-kind=provider] [name=enabled]','false');
    await p.click('[data-control-kind=provider] button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=provider] [name=revision]')?.value==='1');
    await p.type('[data-control-kind=rate] [name=model]','deepseek-v4-flash');
    await p.$eval('[data-control-kind=rate] [name=model]',e=>e.dispatchEvent(new Event('change',{bubbles:true})));
    assert.equal(await p.$eval('[data-control-kind=rate] [name=input]',e=>e.value),'1');
    await p.click('[data-control-kind=rate] button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=rate] [name=model]')?.value===''&&document.querySelector('.pc-save-notice')?.textContent.includes('已保存'));
    await p.type('[data-control-kind=credential] [name=secret]','fixture-private-replacement');
    await p.click('[data-control-kind=credential] button');await p.waitForFunction(()=>document.querySelector('[data-control-kind=credential] [name=revision]')?.value==='1');
    assert.equal(await p.$eval('[name=secret]',e=>e.value),'');
    assert.doesNotMatch(await body(),/fixture-private-replacement/);
    await p.screenshot({path:path.join(os.tmpdir(),'api-controls-console-20261010.png'),fullPage:true});
    await p.click('.pc-sidebar [data-pc-page=security]');assert.match(await body(),/预算设置/);assert.match(await body(),/密钥设置/);assert.doesNotMatch(await body(),/fixture-private-replacement/);
    assert.match(await body(),/待恢复演练/);assert.match(await body(),/已通过/);
    await p.screenshot({path:path.join(os.tmpdir(),'api-metering-console-20261010.png'),fullPage:true});
    await p.click('.pc-sidebar [data-pc-page=overview]');await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await p.screenshot({path:path.join(os.tmpdir(),'platform-admin-mobile-20261010.png'),fullPage:true});await p.setViewport({width:1440,height:1000});
    // Live permission changes clear the old snapshot before a new preflight.
    serverUser={...admin,tenant_id:1};await p.evaluate(()=>window.dispatchEvent(new Event('sem:auth-context-changed')));
    await p.waitForFunction(()=>document.body.textContent.includes('此账号无法进入'));assert(!await p.$('.pc-kpis'));assert.doesNotMatch(await body(),/测试客户 A/);
    serverUser=admin;await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');
    status=500;await p.click('[data-pc=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('暂时无法读取'));assert(!await p.$('.pc-kpis'));
    status=403;await p.click('[data-pc=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('此账号无法进入'));assert(!await p.$('.pc-kpis'));
    status=200;await p.click('[data-pc=refresh]');await p.waitForSelector('.pc-kpis');
    let release;held=new Promise(r=>release=r);await p.click('[data-pc=refresh]');await p.waitForFunction(()=>document.body.textContent.includes('正在核对'));
    await p.click('[data-pc=logout]');await p.waitForSelector('#pc-login');release();held=null;
    await new Promise(r=>setTimeout(r,50));assert(!await p.$('.pc-kpis'));assert.equal(await p.evaluate(()=>sessionStorage.getItem('sem_auth_v1')),null);
    await signIn();await p.waitForSelector('.pc-kpis');status=401;await p.click('[data-pc=refresh]');await p.waitForSelector('#pc-login');assert(!await p.$('.pc-kpis'));
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    assert(requests.every(r=>['/api/v1/auth/login','/api/v1/auth/me','/api/v1/admin/console/snapshot','/api/v1/admin/console/controls','/api/v1/admin/console/usage','/api/v1/admin/console/usage/export','/api/v1/admin/console/operations'].includes(r.path)));
    assert(requests.filter(r=>r.method!=='GET').every(r=>['/api/v1/auth/login','/api/v1/admin/console/controls','/api/v1/admin/console/operations'].includes(r.path)));
  }finally{await browser.close();await f.close();}
});
