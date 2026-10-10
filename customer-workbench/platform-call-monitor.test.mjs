import test from 'node:test';
import assert from 'node:assert/strict';
import {renderCallMonitor,renderWorkerMonitor} from './js/platform-ops-panel.mjs';
import {renderControlPanel} from './js/platform-control-panel.mjs';
import {escapeText as esc} from './js/customer-display.mjs';
const helpers={esc,card:(title,body,note='')=>`<h2>${title}</h2>${body}<p>${note}</p>`,table:(headers,rows)=>headers.join('|')+rows.flat().join('|'),time:s=>s||'暂无记录',tenant:id=>'客户 '+id};

test('monitor unavailable is unknown and does not fabricate workers or zero calls',()=>{
  const rendered=renderCallMonitor({...helpers,snapshot:{}});
  assert.match(rendered,/调用监控待接入/);assert.match(rendered,/后台任务心跳/);
  assert.doesNotMatch(rendered,/成功率.*0%|心跳正常|调度器故障/);
});

test('monitor distinguishes unknown rate from zero and escapes provider text',()=>{
  const monitor={state:'ready',summary:{calls:1,pending:0,success_percent:null},providers:[{provider:'<img onerror=bad()>',module:'geo',calls:1,success_percent:null}],workers:{state:'not_connected'}};
  const rendered=renderCallMonitor({...helpers,snapshot:{operations:{call_monitor:monitor}}});
  assert.match(rendered,/暂无确定结果/);assert.match(rendered,/计量尚未启用/);assert.match(rendered,/未知/);
  assert.match(rendered,/&lt;img/);assert.doesNotMatch(rendered,/<img/);
  assert.match(rendered,/标记告警已处理不会/);
});

test('legacy controls do not offer unsupported concurrency and provider budgets',()=>{
  const snapshot={sources:{users:{rows:[]},tenants:{rows:[]}},controls:{state:'enabled',settings:[],bindings:[{host:'provider.test',module:'sem',label:'test'}],credentials:[],budgets:[]}};
  const legacy=renderControlPanel({...helpers,snapshot});
  assert.doesNotMatch(legacy,/name="max_concurrent"|value="provider:provider.test"/);
  snapshot.controls.capabilities=['budget_concurrency_v1','provider_budget_v1'];
  const modern=renderControlPanel({...helpers,snapshot});
  assert.match(modern,/name="max_concurrent"/);assert.match(modern,/value="provider:provider.test"/);
  snapshot.controls.state='ready';
  assert.doesNotMatch(renderControlPanel({...helpers,snapshot}),/<form/);
});

test('one known success and nine unknown outcomes never appear as overall 100 percent',()=>{
  const summary={calls:10,succeeded:1,known_outcomes:1,success_percent:100,unknown:9,pending:0};
  const rendered=renderCallMonitor({...helpers,snapshot:{operations:{call_monitor:{state:'recording',summary,providers:[]}}}});
  assert.match(rendered,/已知结果成功率/);assert.match(rendered,/100%/);assert.match(rendered,/结果未知（24h）/);
  assert.match(rendered,/\|9\|/);assert.match(rendered,/不代表整体成功率或业务结果已验收/);
});

const workerRow=()=>({module:'seo',transport_state:'available',module_observed_at:'2026-10-11T00:00:10Z',
 worker:{state:'active',verified:true,last_tick_at:'2026-10-11T00:00:00Z',evidence:{kind:'local_tick',scope:'this_process'}},
 queue:{state:'available',queued:0,running:2,unknown:1,oldest_running_at:'2026-10-10T23:59:00Z'}});

test('worker monitoring reports a recent local tick separately from real queue counts',()=>{
 const rendered=renderWorkerMonitor({...helpers,workers:{state:'connected',rows:[workerRow()]}});
 assert.match(rendered,/采样时当前进程有心跳/);assert.match(rendered,/0 \/ 2 \/ 1/);
 assert.match(rendered,/当前进程心跳不能证明所有进程正常/);assert.doesNotMatch(rendered,/全部服务正常/);
});

test('empty queues, an old tick or an unverified owner never become healthy evidence',()=>{
 for(const change of [r=>r.worker.verified=false,r=>r.worker.evidence=null,r=>r.worker.evidence.scope='all_processes',
  r=>r.worker.last_tick_at='2026-10-10T23:50:00Z',r=>r.transport_state='timeout',r=>r.module_observed_at=null]){
  const row=workerRow();change(row);row.queue={state:'available',queued:0,running:0,unknown:0};
  const rendered=renderWorkerMonitor({...helpers,workers:{rows:[row]}});
  assert.doesNotMatch(rendered,/采样时当前进程有心跳/);assert.match(rendered,/存活尚未验证/);
 }
});

test('partial worker coverage retains unknown counts and safely renders diagnostic codes',()=>{
 const row=workerRow();row.transport_state='timeout';row.worker={state:'degraded',last_error_code:'<img src=x onerror=bad()>'};
 row.queue={state:'schema_pending',queued:0,running:0,unknown:0};
 const rendered=renderWorkerMonitor({...helpers,workers:{rows:[row]}});
 assert.match(rendered,/读取超时/);assert.match(rendered,/执行器报告异常/);assert.match(rendered,/未知 \/ 未知 \/ 未知/);
 assert.match(rendered,/&lt;img/);assert.doesNotMatch(rendered,/<img/);
 assert.doesNotMatch(renderWorkerMonitor({...helpers,workers:{note:'<script>bad()</script>'}}),/<script>/);
});

test('worker evidence stays visible while the separate provider ledger is unavailable',()=>{
 const row=workerRow();row.worker.state='stopped';
 const rendered=renderCallMonitor({...helpers,snapshot:{operations:{call_monitor:{state:'schema_pending',workers:{rows:[row]}}}}});
 assert.match(rendered,/调用监控待接入/);assert.match(rendered,/执行器已停止/);assert.match(rendered,/0 \/ 2 \/ 1/);
});
