import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {demoFixture} from './tests/geo-demo-fixture.mjs';

test('built target page: eight demo/six formal, filters, evidence, mobile and missing batch', {timeout: 90000}, async () => {
  const fixture = await startFixtureServer();
  const artifacts = process.env.DEMO_ARTIFACT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'geo-demo-'));
  await fs.mkdir(artifacts, {recursive: true});
  const browser = await puppeteer.launch({executablePath: process.env.EDGE_BINARY || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true, userDataDir: path.join(artifacts, 'browser-profile'), args: ['--no-sandbox']});
  const p = await browser.newPage(), errors = [], calls = [], external = [];
  const origin = 'https://geo-demo.test';
  let missing = false, deny = false;
  try {
    p.on('pageerror', (e) => errors.push(e.message));
    await p.evaluateOnNewDocument(() => sessionStorage.setItem('sem_auth_v1', JSON.stringify({version: 1, token: 'synthetic-only',
      user: {id: 7, tenant_id: 15, permissions: {'geo.assets': 'view', 'geo.content': 'view'}}})));
    await p.setRequestInterception(true);
    p.on('request', async (req) => {
      const u = new URL(req.url());
      if (u.protocol === 'data:' || u.protocol === 'blob:') return req.continue();
      if (u.origin !== origin) { external.push(u.origin); return req.abort(); }
      const send = (data, status = 200) => req.respond({status, contentType: 'application/json', body: JSON.stringify(data)});
      if (u.pathname.startsWith('/api/')) calls.push({method: req.method(), path: u.pathname});
      if (u.pathname === '/api/v1/auth/me') return send({user: {id: 7, tenant_id: 15, permissions: {'geo.assets': 'view', 'geo.content': 'view'}}});
      if (u.pathname === '/api/v1/auth/modules') return send({tenant_id: 15, modules: [{module_code: 'geo', available: true}]});
      if (u.pathname === '/api/v1/geo/tenants') return send({tenants: [{id: 15, name: '本地合成夹具'}]});
      if (u.pathname === '/api/v1/geo/projects') return send({projects: [{id: 3, tenant_id: 15, name: '合成演示项目', status: 'active'}]});
      if (u.pathname.endsWith('/onsite-tasks')) return send({module: 'geo', tenant_id: 15, scope_id: 3, can_create: false, items: [], next_before_id: null});
      if (u.pathname.endsWith('/search-visibility')) return send({state: 'ready', latest: null, weeks: []});
      if (u.pathname.includes('/client/') || u.pathname.endsWith('/executions')) {
        if (deny) return send({}, 403);
        const r = u.pathname.endsWith('/executions') ? 'executions' : u.pathname.split('/client/')[1];
        const v = structuredClone(geoFixture(r));
        if (r === 'executions') v.project_id = 3;
        else { v.tenant_id = 15; v.project_id = 3; }
        if (r === 'overview') v.data.demo_batch = missing
          ? {batch_token: demoFixture().data.demo_batch.batch_token, status: 'unavailable', reason_code: 'batch_missing'}
          : demoFixture().data.demo_batch;
        return send(v);
      }
      if (u.pathname.startsWith('/api/')) return send({}, 404);
      const response = await fetch(fixture.origin + u.pathname + u.search);
      return req.respond({status: response.status, contentType: response.headers.get('content-type'), body: Buffer.from(await response.arrayBuffer())});
    });
    await p.setViewport({width: 1440, height: 1000});
    await p.goto(origin + '/customer-workbench/?module=geo&tenant_id=15&project_id=3');
    await p.waitForSelector('[data-demo-engine]');
    await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$$eval('[data-demo-engine]', (n) => n.length), 56);
    const text = await p.$eval('.geo-demo', (e) => e.textContent);
    assert(text.includes('演示数据，不代表真实引擎检测或实际效果') && text.includes('2026-10-20 至 2026-11-18'));
    assert(!text.includes('真实 API 回答') && !text.includes('合格回答'));
    await p.screenshot({path: path.join(artifacts, 'demo-desktop.png'), fullPage: true});
    await p.$eval('[data-demo-engine] details', (e) => e.open = true);
    assert.match(await p.$eval('[data-demo-engine] details', (e) => e.innerText), /#10001/);
    await p.select('[data-geo-demo] [name=kind]', 'ordinary');
    await p.type('[data-geo-demo] [name=q]', '83');
    await p.$eval('[data-geo-demo]', (e) => e.requestSubmit());
    assert.equal(await p.$$eval('[data-demo-engine]', (n) => n.length), 8);
    await p.click('.geo-tabs [data-resource=questions]');
    await p.waitForSelector('[data-geo-questions]');
    assert.equal(await p.$$eval('.geo-workspace .geo-question-table thead th', (n) => n.length), 9);
    assert.match(await p.$eval('.geo-workspace .geo-question-table caption', (e) => e.textContent), /正式六引擎/);
    assert.equal(await p.$$eval('[data-demo-engine]', (n) => n.length), 8);
    await p.setViewport({width: 390, height: 844});
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert(await p.$eval('.geo-demo .geo-question-scroll', (e) => e.scrollWidth > e.clientWidth));
    await p.screenshot({path: path.join(artifacts, 'demo-mobile.png'), fullPage: true});
    missing = true;
    await p.click('[data-tab=home]'); await p.click('[data-geo=refresh]');
    await p.waitForFunction(() => document.querySelector('.geo-demo')?.textContent.includes('未找到已核演示批次'));
    assert.equal(await p.$('[data-demo-engine]'), null);
    deny = true; await p.click('[data-geo=refresh]'); await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$('[data-demo-engine]'), null);
    assert(calls.every((c) => c.method === 'GET'));
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
  } finally { await browser.close(); await fixture.close(); }
});
