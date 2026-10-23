import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {geoFixture, question, openWeekProgress, envelope, page as listPage} from './tests/geo-client-fixture.mjs';
import {geoEngines} from './js/geo-project-insights.mjs';
import {assertNoPatrolControls} from './tests/geo-readonly-assertions.mjs';
import {publicationPage} from './tests/publication-groups-fixture.mjs';

test('built insights: full server filters, six engines, citations, suggestions, binary downloads and permission cleanup', {timeout: 90000}, async () => {
  const fixture = await startFixtureServer();
  const browser = await puppeteer.launch({executablePath: process.env.EDGE_BINARY || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true, args: ['--no-sandbox']});
  const shots = await fs.mkdtemp(path.join(os.tmpdir(), 'geo-insights-'));
  const p = await browser.newPage(), calls = [], errors = [], external = [];
  const origin = 'https://geo-client.test';
  let unavailable = false, denied = false, legacy = false, openCount = 26;
  try {
    p.on('pageerror', (e) => errors.push(e.message));
    await p.evaluateOnNewDocument(() => sessionStorage.setItem('sem_auth_v1', JSON.stringify({version: 1, token: 'synthetic-only', user: {id: 7, tenant_id: 1, permissions: {'geo.assets': 'edit', 'geo.content': 'edit'}}})));
    await p.setRequestInterception(true);
    p.on('request', async (req) => {
      const u = new URL(req.url());
      if (u.protocol === 'blob:' || u.protocol === 'data:') return req.continue();
      if (u.origin !== origin) { external.push(u.origin); return req.abort(); }
      const send = (data, status = 200) => req.respond({status, contentType: 'application/json', body: JSON.stringify(data)});
      if (u.pathname.startsWith('/api/')) calls.push({method: req.method(), path: u.pathname, params: Object.fromEntries(u.searchParams)});
      if (u.pathname === '/api/v1/auth/me') return send({user: {id: 7, tenant_id: 1, permissions: {'geo.assets': 'edit', 'geo.content': 'edit'}}});
      if (u.pathname === '/api/v1/auth/modules') return send({tenant_id: 1, modules: [{module_code: 'geo', available: true}]});
      if (u.pathname === '/api/v1/geo/tenants') return send({tenants: [{id: 1, name: '合成客户'}]});
      if (u.pathname === '/api/v1/geo/projects') return send({projects: [{id: 10, tenant_id: 1, name: '合成项目', status: 'active'}]});
      if (u.pathname.endsWith('/onsite-tasks')) return send({module: 'geo', tenant_id: 1, scope_id: 10, can_create: false, items: [], next_before_id: null});
      if (u.pathname.endsWith('/search-visibility')) return send({state: 'ready', latest: null, weeks: []});
      if (u.pathname.includes('/client/') || u.pathname.endsWith('/executions')) {
        const r = u.pathname.endsWith('/executions') ? 'executions' : u.pathname.split('/client/')[1];
        if(r==='publication-groups'){
          const params=Object.fromEntries(u.searchParams);if(params.article_id)params.article_id=Number(params.article_id);
          return send(publicationPage('geo',params));
        }
        if (denied) return send({}, 403);
        if (unavailable && ['summary', 'questions', 'article-citations'].includes(r)) return send({}, 404);
        if (r.startsWith('reports/')) return req.respond({status: 200,
          contentType: r.endsWith('.pdf') ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          headers: {'cache-control': 'private, no-store', 'content-disposition': 'attachment'},
          body: Buffer.from(r.endsWith('.pdf') ? '%PDF-synthetic-report' : 'PK-synthetic-workbook')});
        if (r === 'questions') {
          const q = {...question, id: u.searchParams.has('cursor') ? 4 : 3, question: u.searchParams.has('cursor') ? '末页问题' : '合成问题：设备如何选型？',
            unit: {id: 4, name: '内部单元名', keyword: '设备选型', display_name: '设备选型'},
            by_engine: geoEngines.map(([engine_key, label], i) => ({engine_key, label, mentioned: i < 2 ? 0 : i === 2 ? 1 : null, total: i < 2 ? 0 : i === 2 ? 2 : null,
              percentage: i === 2 ? 50 : null, status: ['tested_excluded', 'tested_excluded', 'small_sample', 'not_tested', 'not_configured', 'failed'][i],
              excluded_reason_codes: i === 0 ? ['engine_source_untrusted', 'analysis_incomplete'] : i === 1 ? ['snapshot_unavailable'] : [],
              small_sample: i === 2, last_sample_at: i < 3 ? '2026-10-15T02:00:00Z' : null}))};
          const v = envelope({...listPage([q], !u.searchParams.has('cursor')), options: {businesses: [{id: 2, name: '设备业务'}], units: [{id: 4, business_id: 2, name: '内部单元名', display_name: '设备选型'}]}}, 'questions');
          v.data.pagination.total_count = 2;
          if (!legacy) v.data.open_week_progress = {...openWeekProgress, detected_answer_count: openCount};
          else delete q.open_week_detected_count;
          return send(v);
        }
        const v = structuredClone(geoFixture(r, {ready: true}));
        if (v.data?.open_week_progress) {
          if (legacy) delete v.data.open_week_progress;
          else v.data.open_week_progress.detected_answer_count = openCount;
        }
        return send(v);
      }
      if (u.pathname.startsWith('/api/')) return send({}, 404);
      const r = await fetch(fixture.origin + u.pathname + u.search);
      return req.respond({status: r.status, contentType: r.headers.get('content-type'), body: Buffer.from(await r.arrayBuffer())});
    });
    await p.setViewport({width: 1500, height: 1050});
    await p.goto(origin + '/customer-workbench/?module=geo&tenant_id=1&project_id=10&onsite_task_id=21');
    await p.waitForSelector('[data-tab=plan]');
    await p.waitForNetworkIdle({idleTime: 200});
    await p.waitForFunction(() => document.querySelector('[data-tab=onsite]')?.getAttribute('aria-current') === 'page');
    assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /完善 FAQ/);
    assert.equal(await p.$('[data-action^="onsite-"], [data-sv=run], [data-sv=config]'), null);
    await assertNoPatrolControls(p);
    await p.click('[data-tab=home]');
    await p.waitForFunction(() => document.querySelector('.geo-open-week')?.textContent.includes('26'));
    let text = await p.$eval('.geo-workspace', (e) => e.textContent);
    assert.match(text, /统计周期：2026-10-12 至 2026-10-18（北京时间）/);
    assert(!text.includes('右端不含') && !text.includes('2026-10-12T'));
    await assertNoPatrolControls(p);
    await p.screenshot({path: path.join(shots, 'home-open-week-desktop.png'), fullPage: true});
    await p.click('[data-tab=data]');
    await p.waitForFunction(() => document.querySelector('.geo-summary')?.textContent.includes('1.5'));
    await assertNoPatrolControls(p);
    assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /本周（未结束）已检测 26 条，下周一计入正式指标/);
    await p.click('[data-resource=questions]');
    await p.waitForSelector('[data-geo-questions]');
    await p.select('[name=business_id]', '2');
    await p.select('[name=unit_id]', '4');
    await p.type('[name=q]', '设备');
    await p.$eval('[data-geo-questions]', (f) => f.requestSubmit());
    await p.waitForFunction(() => document.querySelector('[data-geo-questions] [name=q]')?.value === '设备' && document.querySelector('[data-geo=more]'));
    await p.click('[data-geo=more]');
    await p.waitForFunction(() => document.querySelector('.geo-workspace')?.textContent.includes('末页问题'));
    const paged = calls.filter((c) => c.path.endsWith('/client/questions') && c.params.cursor).at(-1);
    assert.equal(paged.params.business_id, '2'); assert.equal(paged.params.unit_id, '4'); assert.equal(paged.params.q, '设备');
    assert.equal(paged.params.week_end, '2026-10-19');
    assert.equal(await p.$('[data-geo=more]'), null);
    assert.deepEqual(await p.$eval('.geo-matrix', (matrix) => [...matrix.querySelectorAll('section b')].map((n) => n.textContent)), ['豆包', 'DeepSeek', '千问', '元宝', '文心', 'Kimi']);
    text = await p.$eval('.geo-workspace', (e) => e.textContent);
    for (const line of ['本周（未结束）已检测 26 条，下周一计入正式指标', '本周（未结束）已检测 4 条，下周一计入',
      '已检测，未计入', '平台来源未核实；回答判读未完成', '回答记录不可读', '样本时间：2026年10月15日 10:00']) assert(text.includes(line), line);
    const excludedText = await p.$eval('.geo-matrix', (e) => [...e.querySelectorAll('section')].filter((s) => s.textContent.includes('已检测，未计入')).map((s) => s.textContent).join(''));
    assert(!excludedText.includes('0/0') && !excludedText.includes('%'));
    await assertNoPatrolControls(p);
    await p.screenshot({path: path.join(shots, 'data-matrix-desktop.png'), fullPage: true});
    const cdp = await p.createCDPSession();
    await cdp.send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: shots});
    for (const [format, prefix] of [['pdf', '%PDF'], ['xlsx', 'PK']]) {
      await p.click(`[data-format=${format}]`);
      const file = path.join(shots, `GEO-10-2026-10-19.${format}`);
      await p.waitForFunction(() => !document.querySelector('[data-format=pdf]')?.disabled);
      // Chromium completes these tiny synthetic files asynchronously.
      await assert.doesNotReject(async () => {
        for (let i = 0; i < 50; i++) {
          try { assert((await fs.readFile(file, 'utf8')).startsWith(prefix)); return; }
          catch (e) { if (i === 49) throw e; await new Promise((r) => setTimeout(r, 100)); }
        }
      });
    }
    await p.setViewport({width: 390, height: 844});
    assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await p.screenshot({path: path.join(shots, 'data-matrix-mobile.png'), fullPage: true});
    await p.setViewport({width: 1440, height: 1000});
    await p.click('[data-tab=deliveries]');
    await p.click('[data-resource=article-citations]');
    await p.waitForSelector('[data-resource="answers/5"]');
    assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /H\/U：1\/2 · 50%/);
    await assertNoPatrolControls(p);
    await p.screenshot({path: path.join(shots, 'published-article-citations.png'), fullPage: true});
    await p.click('[data-resource="answers/5"]');
    await p.waitForSelector('.geo-prose');
    await p.click('[data-tab=onsite]');
    await p.waitForFunction(() => document.querySelector('.geo-workspace')?.textContent.includes('完善 FAQ'));
    await assertNoPatrolControls(p);
    await p.screenshot({path: path.join(shots, 'onsite-suggestions.png'), fullPage: true});
    openCount = 0;
    await p.click('[data-tab=home]'); await p.click('[data-geo=refresh]');
    await p.waitForNetworkIdle({idleTime: 200});
    assert.match(await p.$eval('.geo-open-week', (e) => e.textContent), /本周（未结束）暂未检测/);
    legacy = true;
    await p.click('[data-geo=refresh]');
    await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$('.geo-open-week'), null);
    await assertNoPatrolControls(p);
    await p.click('[data-tab=data]');
    assert.match(await p.$eval('.geo-summary', (e) => e.textContent), /1.5/);
    await p.click('[data-resource=questions]');
    await p.waitForNetworkIdle({idleTime: 200});
    assert.equal(await p.$('.geo-question-open-week'), null);
    assert.equal(await p.$('.geo-open-week'), null);
    unavailable = true;
    await p.click('[data-tab=home]'); await p.click('[data-geo=refresh]');
    await p.waitForFunction(() => document.querySelector('[data-geo=refresh]') && document.querySelector('[data-tab=plan]'));
    await p.waitForNetworkIdle({idleTime: 200});
    await p.click('[data-tab=data]');
    await p.waitForFunction(() => document.querySelector('.geo-workspace')?.textContent.includes('暂无数据'));
    await p.click('[data-resource=questions]');
    await p.waitForFunction(() => document.querySelector('.geo-workspace')?.textContent.includes('暂无数据（接口暂未开放）'));
    await assertNoPatrolControls(p);
    await p.screenshot({path: path.join(shots, 'api-unavailable-fallback.png'), fullPage: true});
    denied = true;
    await p.click('[data-resource=answers]');
    await p.waitForFunction(() => !document.querySelector('[data-geo-workspace]'));
    assert(!(await p.$eval('#app', (e) => e.textContent)).includes('末页问题'));
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    assert(calls.every((c) => c.method === 'GET'));
    assert(!calls.some((c) => c.path.includes('/visibility-patrol/')));
    assert(calls.filter((c) => c.path.includes('/client/')).every((c) => c.params.tenant_id === '1' && c.path.includes('/projects/10/')));
    console.log('Synthetic insights screenshots: ' + shots);
  } finally { await browser.close(); await fixture.close(); }
});
