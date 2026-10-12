import test from 'node:test';
import assert from 'node:assert/strict';
import {automationEventsCsv,downloadAutomationEvents} from './js/advisor-automation-export.mjs';
import {createAdvisorAutomationPanel} from './js/advisor-automation-panel.mjs';
import {eventPage,scope,runId,project} from './tests/advisor-automation-fixture.mjs';

test('audit CSV exports only verified scoped fields and states its pagination boundary',()=>{
  const source=eventPage();source.items[0].secret='never-export';source.items[0].prompt='never-export';
  const exported=automationEventsCsv({...source,next_after_id:1},scope,runId);
  assert(exported.contents.startsWith('\uFEFF'));assert.match(exported.contents,/仍有后续记录/);
  assert.match(exported.contents,/当前授权项目的本页记录/);assert(!exported.contents.includes('never-export'));
  assert.equal(exported.filename,'automation-seo-2-19-events-after-0.csv');
  assert.throws(()=>automationEventsCsv({...source,tenant_id:3},scope,runId),/CONTRACT/);
  assert.throws(()=>automationEventsCsv(source,scope,runId,{afterId:1}),/CONTRACT/);
});

test('spreadsheet formula prefixes including whitespace are neutralized and cells are escaped',()=>{
  const source=eventPage();source.items[0].code='  =HYPERLINK("bad")';source.items[0].evidence_refs=['@command','+call','-formula'];
  const exported=automationEventsCsv(source,scope,runId);
  assert(exported.contents.includes('"\'  =HYPERLINK(""bad"")"'));
  assert(exported.contents.includes('"\'@command | +call | -formula"'));
});

test('a local download uses a bounded filename and revokes its object URL',()=>{
  const actions=[],link={remove(){actions.push('remove');},click(){actions.push('click');}};
  const browser={Blob,URL:{createObjectURL(blob){assert.equal(blob.type,'text/csv;charset=utf-8');return 'blob:fixture';},revokeObjectURL(url){actions.push(url);}},
    document:{createElement(kind){assert.equal(kind,'a');return link;},body:{append(value){assert.equal(value,link);actions.push('append');}}},setTimeout(fn){fn();}};
  downloadAutomationEvents(automationEventsCsv(eventPage(),scope,runId),browser);
  assert.deepEqual(actions,['append','click','remove','blob:fixture']);assert.match(link.download,/^automation-seo-2-19-/);
});

test('export rereads authorized events and revocation prevents a cached download',async()=>{
  const session={token:'export-fixture',user:{id:7,tenant_id:null,permissions:{'seo.site':'edit','seo.content':'edit','seo.keywords':'view'}},authRevision:1,logout(){}},calls=[],downloads=[];
  let revoked=false,denied=false;
  const link={remove(){},click(){}},browser={Blob,URL:{createObjectURL(blob){downloads.push(blob);return 'blob:fixture';},revokeObjectURL(){}},
    document:{hidden:false,createElement(){return link;},body:{append(){}}},setTimeout(){return 1;},clearTimeout(){},crypto:{}};
  const panel=createAdvisorAutomationPanel({session,browser,onChange(){},onDenied(){denied=true;},fetchImpl:async(path,options)=>{
    calls.push({path,method:options.method});let data;
    if(path.endsWith('/auth/me'))data={user:session.user};
    else if(path.endsWith('/auth/modules'))data={tenant_id:null,modules:[{module_code:'seo',available:true}]};
    else if(path.includes('/events?')){if(revoked)return {ok:false,status:403};data={...eventPage(),run_id:null,items:eventPage().items.map(row=>({...row,run_id:null}))};}
    else data={schema:1,module:'seo',items:[project()],next_before_scope_id:null};
    return {ok:true,status:200,json:async()=>structuredClone(data)};
  }});
  const click=action=>panel.click({target:{closest:()=>({disabled:false,dataset:{automationKey:'seo:2:19',automationAction:action}})}});
  const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
  try{
    await panel.initialize(['seo']);click('project-logs');await settle();assert.match(panel.html(),/导出本页日志 CSV/);
    click('export-events');await settle();assert.equal(downloads.length,1);assert.match(await downloads[0].text(),/当前授权项目的本页记录/);
    revoked=true;click('export-events');await settle();assert(denied);assert.equal(downloads.length,1);assert.equal(panel.html(),'');
    assert.equal(calls.filter(row=>row.path.includes('/events?')).length,3);assert(calls.every(row=>row.method==='GET'));
  }finally{panel.dispose();}
});
