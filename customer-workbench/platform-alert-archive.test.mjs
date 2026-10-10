import test from 'node:test';
import assert from 'node:assert/strict';
import {platformAlertArchive,platformNotifications,visiblePlatformAlerts} from './js/platform-alert-archive.mjs';

const snapshot=()=>({generated_at:'2026-10-10T08:00:00Z',
  alerts:platformAlertArchive.items.map(([id,signal])=>({id,signal,kind:'task_failed',handling:{status:'open'}})),
  api_costs:{period:'2026-10',unpriced:28043,known_amount:'0',estimated_amount:null},
  controls:{state:'schema_pending'},sources:{geo_async_jobs:{rows:[{status:'failed'}]}}});

test('clears the selected incidents and recurring reminders across refreshes without modifying source data',()=>{
  const data=snapshot(),before=structuredClone(data);
  assert.deepEqual(platformNotifications(data),[]);
  assert.deepEqual(visiblePlatformAlerts(data),[]);
  assert.deepEqual(platformNotifications(structuredClone(data)),[]);
  assert.deepEqual(data,before);
  assert.equal(data.sources.geo_async_jobs.rows[0].status,'failed');
  assert.equal(data.api_costs.unpriced,28043);
  assert.equal(data.api_costs.estimated_amount,null);
});
test('new failure signals and new sources continue to alert while cleared incidents remain hidden',()=>{
  const data=snapshot();
  data.alerts[0].signal='new-failure';
  data.alerts.push({id:'different-source',signal:platformAlertArchive.items[0][1],handling:{status:'open'}});
  data.alerts.push({id:'resolved-new-source',signal:'new',handling:{status:'resolved'}});
  assert.deepEqual(platformNotifications(data).map(a=>a.id),[data.alerts[0].id,'different-source']);
  data.alerts.push({id:platformAlertArchive.items[1][0],message:'signal missing'});
  assert.ok(platformNotifications(data).some(a=>a.message==='signal missing'));
});
test('new billing period or changed configuration status produces a new reminder',()=>{
  const data=snapshot();
  data.api_costs.unpriced++;
  assert.equal(platformNotifications(data).length,0);
  data.api_costs.period='2026-11';
  assert.match(platformNotifications(data)[0].message,/尚未定价/);
  data.controls.state='ready';
  assert.equal(platformNotifications(data).length,2);
  data.controls.state='enabled';
  assert.equal(platformNotifications(data).length,1);
});
test('snapshots before the archive and unknown timestamps retain reminders',()=>{
  const data=snapshot();data.generated_at='2026-10-09T08:00:00Z';
  assert.equal(platformNotifications(data).length,11);
  data.generated_at='invalid';
  assert.equal(platformNotifications(data).length,11);
});
