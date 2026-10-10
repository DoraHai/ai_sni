import test from 'node:test';
import assert from 'node:assert/strict';
import {renderCallMonitor} from './js/platform-ops-panel.mjs';
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
