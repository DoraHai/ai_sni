import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {publicationPage} from './tests/publication-groups-fixture.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const origin='https://publication-workbench.test';
const jwt=claims=>`e30.${Buffer.from(JSON.stringify({sub:'7',...claims})).toString('base64url')}.synthetic`;
for(const module of ['seo','geo'])for(const advisor of [false,true])test(`built ${module} ${advisor?'advisor':'customer'} read-only publication groups, pagination, failure, scope and mobile`,{timeout:90000},async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const calls=[],errors=[],external=[],shots=process.env.PUBLICATION_SHOTS_DIR;
  let failed=false,revoked=false,selectionMode=false;
  try{
    const p=await browser.newPage();p.on('pageerror',e=>errors.push(e.message));await p.setViewport({width:1440,height:900});
    const user={id:advisor?7:12,tenant_id:advisor?null:1,is_advisor:advisor,display_name:advisor?'示例顾问':'示例客户甲',permissions:{'seo.site':advisor?'edit':'view','seo.content':advisor?'edit':'view','seo.keywords':advisor?'edit':'view','geo.assets':advisor?'edit':'view','geo.content':advisor?'edit':'view'}};
    await p.evaluateOnNewDocument(({user,advisor,token})=>{sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token,user}));sessionStorage.setItem('sem_tenant_id','1');if(advisor)sessionStorage.setItem('sem_advisor_identity_v1',JSON.stringify({token:'synthetic-identity',user}));},{user,advisor,token:advisor?jwt({scope_kind:'advisor_tenant',aud:'advisor-business',tid:1,gid:101}):'fixture-customer'});
    await p.setRequestInterception(true);
    p.on('request',async req=>{
      const u=new URL(req.url());if(u.protocol==='data:')return req.continue();if(u.origin!==origin){external.push(u.origin);return req.abort();}
      const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)});
      if(u.pathname.startsWith('/api/'))calls.push({path:u.pathname,query:Object.fromEntries(u.searchParams),method:req.method()});
      if(u.pathname==='/api/v1/auth/me')return send({user});
      if(u.pathname==='/api/v1/auth/modules')return send({tenant_id:1,modules:[{module_code:module,available:true}]});
      if(u.pathname==='/api/v1/auth/tenants')return send(advisor?[{id:1,name:'示例客户甲'}]:{module:'seo',tenants:[{id:1,name:'示例客户甲'}]});
      if(u.pathname==='/api/v1/seo/workbench/sites')return send({tenant_id:1,sites:[{id:9,status:'active',name:'示例网站'},...(selectionMode?[{id:19,status:'active',name:'示例网站乙'}]:[])],selection_policy:{selectable_statuses:['active']}});
      if(u.pathname==='/api/v1/seo/workbench/publication-page-evidence')return send({tenant_id:1,site_id:9,read_only:true,page:Number(u.searchParams.get('page')),page_size:20,total:1,items:[{content:{id:88,tenant_id:1,site_id:9,title:'示例客户甲原生文章'},publication:{id:91,status:'published',platform_name:'官网',public_url:'https://example.com/article',published_at:'2026-10-23T01:00:00Z'},page_check:{coverage:'no_data'},page_association:{association_status:'no_match'}}]});
      if(u.pathname==='/api/v1/geo/tenants')return send({tenants:[{id:1,name:'示例客户甲'}]});
      if(u.pathname==='/api/v1/geo/projects')return send({projects:[{id:10,tenant_id:1,name:'示例项目',status:'active'},...(selectionMode?[{id:20,tenant_id:1,name:'示例项目乙',status:'active'}]:[])]});
      if(u.pathname.endsWith('/publication-groups')){
        if(revoked)return send({detail:{code:'forbidden'}},403);
        if(failed)return send({detail:{code:'synthetic_unavailable'}},503);
        const params=Object.fromEntries(u.searchParams);if(params.article_id)params.article_id=Number(params.article_id);
        const value=publicationPage(module,params);
        if(!params.article_id&&params.bucket!=='unlinked'){
          if(!params.cursor){value.items=value.items.slice(0,1);value.has_more=true;value.next_cursor='groups-next';}
          else value.items=value.items.slice(1);
        }
        if(params.article_id){
          if(!params.cursor){value.items=value.items.slice(0,3);value.has_more=true;value.next_cursor='details-next';}
          else value.items=value.items.slice(3);
        }
        return send(value);
      }
      if(module==='geo'&&(u.pathname.includes('/client/')||u.pathname.endsWith('/executions'))){
        const resource=u.pathname.endsWith('/executions')?'executions':u.pathname.split('/client/')[1];return send(geoFixture(resource));
      }
      if(module==='geo'&&u.pathname.endsWith('/search-visibility'))return send({state:'ready',latest:null,weeks:[]});
      if(module==='geo'&&u.pathname==='/api/v1/geo/workbench/onsite-tasks')return send({module:'geo',tenant_id:1,scope_id:10,can_create:false,items:[],next_before_id:null});
      try{
        // Only the in-process loopback fixture may receive fallback requests.
        const response=await fetch(fixture.origin+u.pathname+u.search,{method:req.method(),headers:{...req.headers(),authorization:advisor?'Bearer fixture-advisor':'Bearer fixture-customer'},body:req.postData()});
        await req.respond({status:response.status,contentType:response.headers.get('content-type'),body:Buffer.from(await response.arrayBuffer())});
      }catch{await req.abort().catch(()=>{});}
    });
    const entry=origin+'/customer-workbench/?'+(module==='seo'?'tenant_id=1&site_id=9':'module=geo&tenant_id=1&project_id=10');
    await p.goto(entry);
    if(module==='seo'){
      await p.waitForSelector('[data-action=page][data-page="交付记录"]:not([disabled])');
      await p.locator('[data-page="交付记录"]').click();
    }else{
      await p.waitForSelector('[data-geo=tab][data-tab=deliveries]');await p.locator('[data-tab=deliveries]').click();
    }
    const ready=()=>p.waitForFunction(()=>document.querySelector('.publication-counts')?.textContent.includes('原生记录 2 条'));
    await ready();await p.waitForFunction(()=>document.querySelector('.publication-unlinked')?.textContent.includes('示例客户甲待关联回传'));
    await p.locator('[data-publication=expand]').click();await p.waitForSelector('[data-publication=detail-more]');
    assert.equal(await p.$$eval('.publication-source',es=>es.length),4); // Three detail rows + one unlinked.
    await p.locator('[data-publication=detail-more]').click();await p.waitForFunction(()=>document.querySelectorAll('.publication-source').length===5);
    await p.locator('[data-publication=groups-more]').click();await p.waitForFunction(()=>document.querySelectorAll('.publication-group').length===2);
    assert.match(await p.$eval('.publication-groups',e=>e.textContent),/操作人报告失败/);
    assert.match(await p.$eval('.publication-groups',e=>e.textContent),/关联 v2；当前 v3/);
    const counts=await p.$eval('.publication-counts',e=>e.textContent);
    await p.select('[data-publication-source]','external');assert.equal(await p.$eval('.publication-counts',e=>e.textContent),counts);
    assert.equal(await p.$$eval('.publication-group .publication-source',es=>es.length),2);
    await p.select('[data-publication-source]','all');
    assert.equal(await p.$$eval('.publication-groups [data-action],.publication-groups [data-geo]',es=>es.length),0);
    const shot=async name=>{if(shots){await fs.mkdir(shots,{recursive:true});await p.screenshot({path:path.join(shots,`${module}-${advisor?'advisor':'customer'}-${name}.png`),fullPage:true});}};
    await shot('delivery-desktop');
    const before=calls.filter(c=>c.path.endsWith('/publication-groups')).length;
    if(module==='seo'){
      await p.locator('[data-page="内容"]').click();await p.waitForSelector('[data-action=delivery]:not([disabled])');await p.locator('[data-action=delivery]').click();
    }else{
      await p.locator('[data-geo=read][data-resource="content/7"]').click();
    }
    await p.waitForFunction(()=>document.querySelector('.publication-groups h2')?.textContent==='本稿件发布记录');await ready();
    const detailCalls=calls.filter(c=>c.path.endsWith('/publication-groups')).slice(before);
    assert(detailCalls.every(c=>c.query.article_id===(module==='seo'?'88':'7')&&c.query.bucket==='linked'));
    if(module==='geo')assert(detailCalls.every(c=>c.path.includes('/projects/10/')));
    await shot('article-desktop');
    await p.setViewport({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await shot('article-mobile');
    failed=true;await p.locator('[data-publication=refresh]').click();await p.waitForFunction(()=>document.querySelector('.publication-groups')?.textContent.includes('读取不完整'));assert.equal(await p.$$eval('.publication-source',es=>es.length),0);await shot('failure-mobile');
    failed=false;await p.locator('[data-publication=refresh]').click();await ready();
    revoked=true;await p.locator('[data-publication=refresh]').click();await p.waitForFunction(()=>!document.querySelector('.publication-source'));
    if(!advisor){
      selectionMode=true;revoked=false;
      const groupCalls=calls.filter(c=>c.path.endsWith('/publication-groups')).length;
      await p.goto(origin+'/customer-workbench/?module='+module);await p.waitForSelector('#entry-site');
      assert.equal(calls.filter(c=>c.path.endsWith('/publication-groups')).length,groupCalls);
      await shot('scope-required-mobile');
    }
    assert(calls.every(c=>c.method==='GET'));assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
    assert(!calls.some(c=>c.path.includes('/distribution/v2/')||c.path.includes('/label')));
    if(shots)await fs.writeFile(path.join(shots,`${module}-${advisor?'advisor':'customer'}-fixture.json`),JSON.stringify({module,actor:advisor?'advisor':'customer',tenant_id:1,scope_id:module==='seo'?9:10,group_ids:[88,89],native_records:2,external_records:4,article_groups:2,unlinked_records:1,api_methods:[...new Set(calls.map(c=>c.method))],external_requests:external,errors},null,2));
  }catch(e){e.message+=' ? '+JSON.stringify({calls,errors,external,pages:await Promise.all((await browser.pages()).map(async page=>({url:page.url(),body:(await page.$eval('body',el=>el.textContent).catch(()=>''))?.slice(0,2500)})))});throw e;}finally{await browser.close();await fixture.close();}
});
