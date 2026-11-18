import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {geoFixture} from './tests/geo-client-fixture.mjs';
import {demoFixture} from './tests/geo-demo-fixture.mjs';
import {demoOverview} from './js/geo-project-demo.mjs';

test('built demo: first screen, chart states, collapsed details, formal regression and URL isolation', {timeout: 120000}, async () => {
  const fixture = await startFixtureServer();
  const artifacts = process.env.DEMO_ARTIFACT_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'geo-demo-'));
  await fs.mkdir(artifacts, {recursive: true});
  const browser = await puppeteer.launch({executablePath: process.env.EDGE_BINARY || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true, userDataDir: path.join(artifacts, 'browser-profile'), args: ['--no-sandbox']});
  const p = await browser.newPage(), errors = [], calls = [], external = [];
  const origin = 'https://geo-demo.test';
  let missing = false, deny = false, chartState = 'varied';
  const batch = () => demoFixture(chartState === 'zero' ? {mention: () => false} : chartState === 'unknown' ? {mention: () => null} : {});
  const screenshot = async (name, fullPage = false) => {
    await p.evaluate(() => {
      if (document.querySelector('#local-fixture-label')) return;
      const el = document.createElement('aside'); el.id = 'local-fixture-label';
      el.textContent = '数据来源：本地测试夹具（合成数据，非生产） · Offline fixture preview';
      el.style.cssText = 'position:sticky;top:0;z-index:9999;background:#24364b;color:white;text-align:center;padding:7px;font:13px sans-serif';
      document.body.prepend(el);
    });
    await p.screenshot({path: path.join(artifacts, name), fullPage});
  };
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
      if (u.pathname === '/api/v1/geo/projects') return send({projects: [3, 4].map((id) => ({id, tenant_id: 15, name: '本地合成项目', status: 'active'}))});
      if (u.pathname.endsWith('/onsite-tasks')) return send({module: 'geo', tenant_id: 15, scope_id: 3, can_create: false, items: [], next_before_id: null});
      if (u.pathname.endsWith('/search-visibility')) return send({state: 'ready', latest: null, weeks: []});
      if (u.pathname.includes('/client/') || u.pathname.endsWith('/executions')) {
        if (deny) return send({}, 403);
        const r = u.pathname.endsWith('/executions') ? 'executions' : u.pathname.split('/client/')[1];
        const v = structuredClone(geoFixture(r));
        const pid = Number(u.pathname.match(/projects\/(\d+)/)?.[1]);
        if (r === 'executions') v.project_id = pid;
        else { v.tenant_id = 15; v.project_id = pid; }
        if (r === 'overview') v.data.project.canonical_domain = '';
        if (r === 'questions') v.data.options = {businesses: [{id: 2, name: '合成业务甲'}, {id: 3, name: '合成业务乙'}], units: [{id: 20, business_id: 2, display_name: '合成关键词甲'}, {id: 19, business_id: 3, display_name: '合成关键词乙'}]};
        if (r === 'overview') v.data.demo_batch = missing
          ? {batch_token: demoFixture().data.demo_batch.batch_token, status: 'unavailable', reason_code: 'batch_missing'}
          : batch().data.demo_batch;
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
    assert.equal(await p.$eval('[data-geo-demo-details]', (e) => e.open), false);
    assert.equal(await p.$$eval('[data-demo-comparison]', (n) => n.length), 8);
    const visible = await p.$eval('[data-geo-workspace]', (e) => e.innerText);
    for (const text of ['暂不可计算', '服务计划', '交付记录', '全部问题', '数据范围与依据', '合格回答']) assert(!visible.includes(text), text);
    assert(visible.includes('项目尚未配置自有域名'));
    assert.equal(await p.$eval('[data-geo-demo]', (e) => e.checkVisibility()), false);
    await screenshot('demo-first-screen.png');
    assert(await p.$eval('.geo-demo-charts', (e) => e.getBoundingClientRect().bottom <= innerHeight), 'charts must fit desktop first screen');
    await p.select('[data-geo-demo-day]', '2026-10-20');
    const first = demoOverview(batch()).ordinary.daily[0];
    assert((await p.$eval('.geo-demo-day-value', (e) => e.textContent)).includes(`${first.mentioned_count}/${first.sample_count}`));
    await screenshot('demo-selected-day.png');
    await p.click('[data-geo=demo-details]');
    assert.equal(await p.$eval('[data-geo-demo-details]', (e) => e.open), true);
    assert.equal(await p.$$eval('[data-demo-engine]', (n) => n.length), 56);
    const text = await p.$eval('.geo-demo', (e) => e.textContent);
    assert(text.includes('演示数据，不代表真实引擎检测或实际效果') && text.includes('2026-10-20 至 2026-11-18'));
    assert(!text.includes('真实 API 回答') && !text.includes('合格回答'));
    await screenshot('demo-expanded-grid.png', true);
    await p.$eval('[data-demo-engine] details', (e) => e.open = true);
    assert.match(await p.$eval('[data-demo-engine] details', (e) => e.innerText), /#10001/);
    await p.select('[data-geo-demo] [name=kind]', 'ordinary');
    await p.type('[data-geo-demo] [name=q]', '83');
    await p.$eval('[data-geo-demo]', (e) => e.requestSubmit());
    assert.equal(await p.$$eval('[data-demo-engine]', (n) => n.length), 8);
    assert.equal(await p.$eval('[data-geo-demo-details]', (e) => e.open), true);
    await p.$eval('[data-demo-engine] details', (e) => e.open = true);
    assert.match(await p.$eval('[data-demo-engine] details', (e) => e.innerText), /#10001/);
    await p.evaluate(() => {
      [...document.querySelectorAll('.geo-demo details')].find((e) => e.querySelector('summary')?.textContent === '演示批次依据').open = true;
    });
    await screenshot('demo-expanded-evidence.png', true);
    await p.setViewport({width: 390, height: 844});
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert(await p.$eval('.geo-demo .geo-question-scroll', (e) => e.scrollWidth > e.clientWidth));
    await screenshot('demo-mobile-expanded.png', true);
    await p.evaluate(() => scrollTo(0, 0)); await p.click('[data-geo=demo-details]');
    await p.evaluate(() => scrollTo(0, 0)); await screenshot('demo-mobile-first-screen.png');
    await p.setViewport({width: 1440, height: 1000});
    const slide = await p.evaluate(async () => {
      const before = document.querySelector('.geo-view-modes').getBoundingClientRect().left;
      document.querySelector('[data-view=formal]').click();
      const control = document.querySelector('.geo-view-modes');
      const animation = control.getAnimations()[0];
      const from = control.getBoundingClientRect().left;
      await animation?.finished;
      return {before, from, to: control.getBoundingClientRect().left, animated: !!animation};
    });
    assert(slide.animated && Math.abs(slide.before - slide.from) < 2 && slide.to > slide.from + 100);
    assert.equal(await p.$('.geo-workspace .geo-demo, .geo-demo-charts'), null);
    assert.match(await p.$eval('.geo-workspace', (e) => e.innerText), /本期要点[\s\S]*GEO 优化概览[\s\S]*AI 提及率/);
    assert(!/暂不可计算|合格回答|真实 API 回答|数据范围与依据/.test(await p.$eval('.geo-workspace', (e) => e.innerText)));
    assert.equal(await p.$('.geo-tabs [data-tab=plan]'), null);
    assert.equal(await p.$('.geo-tabs [data-tab=deliveries]'), null);
    assert.equal(await p.$('.geo-tabs [data-all-questions]'), null);
    assert.equal(await p.$eval('[data-search-visibility]', (e) => e.hidden), true);
    await screenshot('formal-first-screen.png');
    await p.click('.geo-tabs [data-tab=work]');
    await p.waitForSelector('[data-geo-questions]');
    assert.equal(await p.$$eval('.geo-demo-work .geo-question-table thead th', (n) => n.length), 22);
    assert.equal(await p.$$eval('.geo-demo-work [data-demo-engine]', (n) => n.length), 56);
    assert.doesNotMatch(await p.$eval('.geo-demo-work', (e) => e.textContent), /演示|模拟/);
    await screenshot('formal-question-filters.png', true);
    await p.select('[data-geo-questions] [name=business_id]', '2');
    await p.$eval('[data-geo-questions]', (e) => e.requestSubmit());
    await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$$eval('.geo-demo-work [data-demo-engine]', (n) => n.length), 16);
    assert.equal(await p.$eval('[data-tab=work]', (e) => e.getAttribute('aria-current')), 'page');
    await p.click('[data-geo=clear-filters]');
    await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$$eval('.geo-demo-work [data-demo-engine]', (n) => n.length), 56);
    await p.$eval('.geo-demo-work [data-demo-engine] details', (e) => e.open = true);
    assert.match(await p.$eval('.geo-demo-work [data-demo-engine] details', (e) => e.innerText), /#10001/);
    await screenshot('formal-sample-evidence.png', true);
    for (const tab of ['home', 'progress', 'onsite', 'data', 'content']) {
      if (!await p.$(`.geo-tabs [data-tab=${tab}]`)) continue;
      await p.click(`.geo-tabs [data-tab=${tab}]`);
      await p.waitForNetworkIdle({idleTime: 200});
      assert(!await p.$eval('.geo-workspace', (e) => e.innerText.includes('数据范围与依据')));
      assert.doesNotMatch(await p.$eval('.geo-workspace', (e) => e.innerText), /演示|模拟/);
      await screenshot(`formal-${tab}.png`);
    }
    await p.click('[data-view=demo]');
    await p.emulateMediaFeatures([{name: 'prefers-reduced-motion', value: 'reduce'}]);
    await p.$eval('[data-view=formal]', (button) => button.click());
    assert.equal(await p.$eval('.geo-view-modes', (control) => control.getAnimations().length), 0);
    await p.click('[data-view=demo]');
    await p.emulateMediaFeatures([]);
    for (const state of ['zero', 'unknown']) {
      chartState = state; await p.click('[data-geo=refresh]'); await p.waitForNetworkIdle({idleTime: 200});
      assert.equal(await p.$$eval('[data-demo-comparison] strong', (n) => n.every((e) => e.textContent === '0.0%')), true);
      if (state === 'unknown') assert(demoOverview(batch()).ordinary.unknown_mention_count > 0);
      await p.evaluate(() => scrollTo(0, 0)); await screenshot(`demo-${state}.png`);
    }
    missing = true;
    await p.click('[data-geo=refresh]');
    await p.waitForFunction(() => document.querySelector('.geo-demo')?.textContent.includes('未找到已核演示批次'));
    assert.equal(await p.$('[data-demo-engine]'), null);
    assert.equal(await p.$('[data-demo-comparison]'), null);
    await screenshot('demo-missing.png');
    deny = true; await p.click('[data-geo=refresh]'); await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$('[data-demo-engine]'), null);
    missing = false; deny = false;
    await p.goto(origin + '/customer-workbench/?module=geo&tenant_id=15&project_id=4');
    await p.waitForNetworkIdle({idleTime: 200}); assert.equal(await p.$('.geo-demo'), null);
    assert.equal(await p.$('[data-view=demo]'), null);
    assert(await p.$('.geo-tabs [data-tab=plan]'));
    assert(await p.$('.geo-tabs [data-tab=deliveries]'));
    assert(await p.$('.geo-basis'));
    assert.match(await p.$eval('.geo-workspace', (e) => e.innerText), /暂不可计算/);
    assert(!await p.evaluate(() => document.body.innerText.includes('geo-demo-t15-p3')));
    await p.goto(origin + '/customer-workbench/?module=geo&tenant_id=16&project_id=3');
    await p.waitForNetworkIdle({idleTime: 200}); assert.equal(await p.$('.geo-demo'), null);
    assert(!await p.evaluate(() => document.body.innerText.includes('geo-demo-t15-p3')));
    assert(calls.every((c) => c.method === 'GET'));
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
  } finally { await browser.close(); await fixture.close(); }
});
