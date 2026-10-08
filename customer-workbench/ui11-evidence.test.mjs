import test from 'node:test';import assert from 'node:assert/strict';import puppeteer from 'puppeteer-core';import fs from 'node:fs';
import {aiRouteView,completionEvidenceView} from './js/seo-evidence-view.mjs';import {aiPlanView} from './js/seo-ai-plan-view.mjs';import {servicePlanView} from './js/seo-contract-view.mjs';import {startFixtureServer} from './tests/fixture-server.mjs';
const target=()=>({metric_key:'seo.content.target_delivery_verified_count',metric_definition:'限定本任务准确稿件与发布记录',completion_basis:'target_object_evidence',scope:{task_id:101,tenant_id:1,site_id:9,content_id:88,publication_id:91,source_version:3},before:0,after:1,change_abs:1,as_of:'2026-10-07T10:00:00Z',source:{capture_id:501},effect_context:{metric_key:'seo.content.published_count',scope:'site',before:2,after:1,change_abs:-1},seo_effect:'not_evaluated'});
test('request route, result provider and response model remain separate; missing response evidence is not invented',()=>{
  const draft={generation_route:{provider:'deepseek',model:'deepseek-reasoner',base_url:'https://api.deepseek.com/v1'},provider:'deepseek',model:'deepseek-reasoner',response_model:null};
  let view=aiRouteView(draft);assert.match(view,/请求模型 deepseek-reasoner/);assert.match(view,/响应报告模型：未返回，不能确认响应模型版本/);assert.doesNotMatch(view,/响应报告模型：deepseek-reasoner/);
  view=aiRouteView({...draft,response_model:'deepseek-reasoner-version-from-response'});assert.match(view,/响应报告模型：deepseek-reasoner-version-from-response/);assert.match(aiRouteView({status:'succeeded'}),/结果记录供应商：未提供/);assert(!aiRouteView({response_model:'<img src=x>'}).includes('<img'));
});
test('plan provenance stays read-only and missing legacy fields remain unknown',()=>{
  const plan={tenant_id:1,site_id:9,revision:4,status:'active',content_ai_provider:'deepseek',content_ai_model:'deepseek-reasoner',content_ai_policy:{provider:'deepseek',fallback_allowed:false,provider_configured:false,provider_unavailable_reason:'ai_draft_deepseek_not_configured'}};
  const view=aiPlanView(servicePlanView(plan).ai,null,null,false,false);assert.match(view,/计划请求模型：deepseek-reasoner/);assert.match(view,/其他供应商回退：禁止/);assert.match(view,/ai_draft_deepseek_not_configured/);assert.doesNotMatch(view,/<(?:input|select)[^>]*(?:provider|model)/);
  assert.match(aiPlanView(servicePlanView({...plan,content_ai_provider:undefined,content_ai_model:undefined}).ai,null,null,false,false),/计划供应商：未提供 · 计划请求模型：未提供/);
});
test('target 0/1 evidence and declining or unknown site context are separate without changing historic evidence',()=>{
  const evidence=target(),before=structuredClone(evidence),view=completionEvidenceView(evidence);assert.match(view,/目标对象的完成证据/);assert.match(view,/稿件 88 · 发布记录 91 · 稿件版本 3/);assert.match(view,/对象观察 0 → 1/);assert.match(view,/全站效果背景（独立于任务完成）/);assert.match(view,/&quot;change_abs&quot;: -1/);assert.deepEqual(evidence,before);
  assert.match(completionEvidenceView({...evidence,effect_context:null}),/未提供；不以0补齐/);
  const legacy={metric_key:'seo.site.healthy_page_count',before:2,after:3,change_abs:1};const old=completionEvidenceView(legacy);assert.match(old,/其他或历史完成证据/);assert.match(old,/healthy_page_count/);assert.doesNotMatch(old,/本任务目标对象的完成证据/);assert.deepEqual(legacy,{metric_key:'seo.site.healthy_page_count',before:2,after:3,change_abs:1});
});
test('mounted execution detail reads model provenance and new/legacy completion evidence without writes',async()=>{
  const edge=process.env.EDGE_BINARY||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync),f=await startFixtureServer(),browser=await puppeteer.launch({executablePath:edge,headless:true});
  try{
    const content=f.state.executions.get(101).task;content.status='done';content.completion_evidence=target();content.params.baseline={metric_key:'seo.content.published_count',value:2};content.params.ai_draft={status:'succeeded',provider:'deepseek',model:'deepseek-chat',response_model:null,generation_route:{provider:'deepseek',model:'deepseek-chat',base_url:'https://api.deepseek.com'}};
    const old=f.state.executions.get(104).task;old.status='done';old.completion_evidence={metric_key:'seo.reports.prepared_count',before:0,after:1,change_abs:1};
    const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(f.origin+'/fixture.html');await page.waitForFunction(()=>document.querySelector('.navigation [data-page="进度"]')&&!document.querySelector('.navigation [data-page="进度"]').disabled);
    const nav=async()=>{await page.click('.navigation [data-page="进度"]');await page.waitForSelector('#execution-count');};await nav();await page.click('[data-action="execution-detail"][data-id="101"]');await page.waitForSelector('[aria-label="模型来源"]');let text=await page.$eval('#page',e=>e.textContent);assert.match(text,/响应报告模型：未返回/);assert.match(text,/本任务目标对象的完成证据/);assert.match(text,/全站效果背景（独立于任务完成）/);assert.match(text,/已完成（附服务端证据）/);
    await nav();await page.click('[data-action="execution-detail"][data-id="104"]');await page.waitForFunction(()=>document.querySelector('#page')?.textContent.includes('其他或历史完成证据'));assert(f.state.calls.every(c=>c.method==='GET'));assert.deepEqual(errors,[]);
  }finally{await browser.close();await f.close();}
});
