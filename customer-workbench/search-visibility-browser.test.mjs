import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs/promises';
import puppeteer from 'puppeteer-core';
import {startFixtureServer} from './tests/fixture-server.mjs';
const edge=process.env.EDGE_BINARY||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const ready=()=>({state:'ready',latest:{id:30,status:'succeeded',created_at:'2026-10-18 06:00',finished_at:'2026-10-18 06:05',result:{summary:{indexed:true,indexed_count:18,index_query_ok:true,brand_hit:2,brand_total:2,core_hit:2,core_total:4,articles_alive:8,articles_total:10},items:[
  {kind:'brand',query:'示例制造',best_rank:1,results:[{rank:1,title:'示例制造官网',url:'https://example.com'}]},
  {kind:'core',query:'工业减速机',best_rank:3,results:[{rank:1,title:'行业资讯',site_name:'工业资讯网',url:'https://news.example.org'},{rank:2,title:'选型指南',site_name:'设备指南',url:'https://guide.example.org'},{rank:3,title:'示例制造产品',url:'https://example.com/products'}]},
  {kind:'core',query:'精密传动',best_rank:null,results:[]},
  {kind:'article',url:'https://media.example.org/article',title:'示例制造技术文章',alive:true},
]}},weeks:Array.from({length:8},(_,i)=>({week:new Date(Date.UTC(2026,7,24+i*7)).toISOString().slice(0,10),status:'succeeded',summary:{brand_hit:1,core_hit:i%4}}))});
const base='/api/v1/geo/projects/10/search-visibility';
test('built GEO feature: role hints, hidden customers, save/run/CSV and desktop/mobile layout',{timeout:120000},async()=>{
  const fixture=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true,args:['--no-sandbox']});
  const shots=process.env.GEO_VISIBILITY_SHOTS;
  if(shots)await fs.mkdir(shots,{recursive:true});
  try{
    for(const scenario of ['advisor','customer-open','customer-closed','advisor-off','advisor-service','admin-off','admin-service','customer-off','customer-service','empty','failure']){
      const customer=scenario.startsWith('customer'),admin=scenario.startsWith('admin'),notEnabled=/-off$|-service$/.test(scenario),level=customer||admin?'view':'edit';
      const user={id:customer?12:7,tenant_id:admin?null:1,display_name:customer?'客户':admin?'超管':'顾问',permissions:{'geo.assets':level,'geo.content':level,...(admin?{'settings.accounts':'edit','settings.customers':'edit'}:{})}};
      const page=await browser.newPage(),errors=[],calls=[];let runs=0,csv=0,config={enabled:!scenario.endsWith('-off'),domains:['example.com'],zh_url:'https://example.com/cn',brand_terms:['示例制造'],core_terms:['工业减速机'],extra_article_urls:[],customer_visible:customer&&scenario!=='customer-closed'};
      page.on('pageerror',e=>errors.push(e.message));
      await page.evaluateOnNewDocument(user=>{sessionStorage.setItem('sem_auth_v1',JSON.stringify({version:1,token:'synthetic-only',user}));},user);
      await page.setRequestInterception(true);
      page.on('request',async req=>{
        const url=new URL(req.url());if(['data:','blob:'].includes(url.protocol))return req.continue();if(url.origin!=='https://visibility.test')return req.abort();
        const send=(data,status=200)=>req.respond({status,contentType:'application/json',body:JSON.stringify(data)});
        if(url.pathname.startsWith('/api/'))calls.push({path:url.pathname,method:req.method(),body:req.postData()});
        if(url.pathname==='/api/v1/auth/me')return send({user});
        if(url.pathname==='/api/v1/auth/modules')return send({tenant_id:user.tenant_id,modules:[{module_code:'geo',available:true}]});
        if(url.pathname==='/api/v1/geo/tenants')return send({tenants:[{id:1,name:'示例制造'}]});
        if(url.pathname==='/api/v1/geo/projects')return send({projects:[{id:10,tenant_id:1,name:'中文官网项目',status:'active'}]});
        if(url.pathname==='/api/v1/geo/workbench/onsite-tasks')return send({module:'geo',tenant_id:1,scope_id:10,can_create:!customer,items:[],next_before_id:null});
        if(url.pathname===base){
          if(scenario==='customer-closed')return send({state:'not_open',message:'暂未开放'});
          if(notEnabled)return send({state:'not_enabled',message:'待启用'});
          if(scenario==='empty')return send({state:'ready',latest:null,weeks:[]});
          const data=ready();if(scenario==='failure'){data.latest.status='failed';data.latest.error='余额不足';data.latest.result.summary.stopped_reason='余额不足';}
          return send(data);
        }
        if(url.pathname===base+'/config'){
          if(req.method()==='PUT'){config=JSON.parse(req.postData());assert.equal(config.customer_visible,false);}
          return send({state:'ready',config,suggested_core_terms:['精密传动'],suggested_core_terms_scope:'tenant'});
        }
        if(url.pathname===base+'/run'){runs++;return send({state:'queued',job:{...ready().latest,id:31,status:'pending'}},202);}
        if(url.pathname===base+'/runs/30/csv'){csv++;return req.respond({status:200,contentType:'text/csv;charset=utf-8',body:'\ufeff类型,搜索词\r\n品牌词,示例制造'});}
        if(url.pathname.startsWith('/api/'))return send({detail:'Unexpected fixture request'},404);
        try{const r=await fetch(fixture.origin+url.pathname+url.search);await req.respond({status:r.status,contentType:r.headers.get('content-type'),body:Buffer.from(await r.arrayBuffer())});}catch{await req.abort();}
      });
      await page.setViewport({width:1440,height:900});
      await page.goto('https://visibility.test/customer-workbench/?module=geo&tenant_id=1&project_id=10');
      await page.waitForFunction(()=>document.body.textContent.includes('示例制造 / 中文官网项目'));
      if(scenario==='customer-closed'){
        await page.waitForFunction(()=>document.querySelector('.onsite-list')||document.body.textContent.includes('GEO 官网'));
        assert.equal(await page.$('.sv-card'),null);
        const hidden=await page.$eval('[data-search-visibility]',e=>e.innerHTML);assert.equal(hidden,'');
        assert.doesNotMatch(await page.$eval('body',e=>e.textContent),/DeepSeek 搜索可见度|想开通请联系你的顾问|每周核对这个项目/);
        assert(!calls.some(c=>c.path.endsWith('/config')));
      }else{
        await page.waitForSelector('.sv-card');
        if(notEnabled){
          const expected=customer?'想开通请联系你的顾问':scenario.endsWith('-off')?'还没开启':'项目已开启';
          await page.waitForFunction(expected=>document.querySelector('.sv-card')?.textContent.includes(expected),{},expected);
          const text=await page.$eval('.sv-card',e=>e.textContent);
          assert.doesNotMatch(text,/not_enabled|customer_visible|api_key|[A-Z][A-Z0-9]*_[A-Z_]+|HTTP|待启用/);
          if(!customer&&scenario.endsWith('-off'))assert.match(text,/项目设置.*每周核对这个项目.*保存项目设置.*每周一北京时间早上 6 点/);
          if(!customer&&scenario.endsWith('-service'))assert.match(text,admin?/超管联系技术人员在服务器上配置搜索服务/:/需要超管处理，请联系超管/);
          if(admin)assert.equal(await page.$eval('.sv-card a',e=>e.getAttribute('href')),'/customer-workbench/?console=platform&page=costs');
          else assert.equal(await page.$('.sv-card a'),null);
          if(!customer){
            await page.click('[data-sv=config]');
            assert.equal(await page.$eval('[data-sv-field=customer_visible]',e=>e.checked),false);
            assert.match(await page.$eval('.sv-form',e=>e.textContent),/前 4 周先由顾问核对/);
            await page.click('[data-sv-field=enabled]');
            await page.click('[data-sv=config]');
            assert((await page.$eval('.sv-empty',e=>e.textContent)).includes(expected),'unsaved checkbox must not change the diagnosis');
            assert(!calls.some(c=>c.method!=='GET'),'hint and settings inspection must remain read only');
          }
        }
        else if(scenario==='empty')await page.waitForFunction(()=>document.querySelector('.sv-card')?.textContent.includes('还没有检查记录'));
        else await page.waitForSelector('.sv-metrics');
        if(customer){assert(!calls.some(c=>c.path.endsWith('/config')));assert.equal(await page.$('[data-sv=config]'),null);assert.equal(await page.$('[data-sv=run]'),null);}
      }
      for(const [name,width,height] of [['desktop',1440,900],['mobile',390,844]]){
        await page.setViewport({width,height});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),scenario+' page must not overflow horizontally');
        if(shots)await page.screenshot({path:path.join(shots,`${scenario}-${name}.png`),fullPage:false});
      }
      if(scenario==='advisor'){
        await page.click('[data-sv=config]');await page.waitForSelector('[data-sv-field=enabled]');
        assert.equal(await page.$eval('[data-sv-field=customer_visible]',e=>e.checked),false);
        if(shots)for(const [name,width,height] of [['desktop',1440,900],['mobile',390,844]]){await page.setViewport({width,height});await page.$eval('.sv-form',e=>e.scrollIntoView());await page.screenshot({path:path.join(shots,`config-${name}.png`)});}
        await page.click('.sv-form button[type=submit]');await page.waitForFunction(()=>document.querySelector('.sv-feedback')?.textContent.includes('已保存'));
        await page.click('[data-sv=config]');await page.click('[data-sv=run]');await page.waitForFunction(()=>document.body.textContent.includes('已排队'));
        assert.equal(runs,1);await page.waitForFunction(()=>document.querySelector('.sv-muted')?.textContent.includes('最近检查')&&!document.querySelector('[data-sv=csv]')?.disabled,{timeout:10000});
        await page.click('[data-sv=csv]');await page.waitForFunction(()=>!document.querySelector('[data-sv=csv]')?.disabled);assert.equal(csv,1);
      }
      assert.deepEqual(errors,[]);await page.close();
    }
  }finally{await browser.close();await fixture.close();}
});
