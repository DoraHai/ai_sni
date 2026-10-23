import test from 'node:test';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startFixtureServer} from './tests/fixture-server.mjs';
import {geoFixture, question, page as listPage, envelope} from './tests/geo-client-fixture.mjs';
import {assertNoPatrolControls} from './tests/geo-readonly-assertions.mjs';
const edge =
  process.env.EDGE_BINARY || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const origin = 'https://geo-client.test';
test(
  'built GEO client: navigation, evidence drilldown, pagination, read-only content/delivery, fallback and mobile',
  {timeout: 120000},
  async () => {
    const fixture = await startFixtureServer(),
      browser = await puppeteer.launch({
        executablePath: edge,
        headless: true,
        args: ['--no-sandbox'],
      });
    const shots = await fs.mkdtemp(path.join(os.tmpdir(), 'geo-client-fe-'));
    try {
      for (const scenario of [
        'insufficient',
        'ready-zero',
        'not-open',
        'empty',
        'partial-failure',
        'read-unavailable',
      ]) {
        const p = await browser.newPage(),
          errors = [],
          external = [],
          calls = [];
        p.on('pageerror', (e) => errors.push(e.message));
        const user = {
          id: 7,
          tenant_id: 1,
          permissions: {'geo.assets': 'view', 'geo.content': 'view'},
        };
        await p.evaluateOnNewDocument(
          (user) =>
            sessionStorage.setItem(
              'sem_auth_v1',
              JSON.stringify({version: 1, token: 'synthetic-only', user}),
            ),
          user,
        );
        await p.setRequestInterception(true);
        p.on('request', async (req) => {
          const url = new URL(req.url());
          if (url.protocol === 'data:') return req.continue();
          if (url.origin !== origin) {
            external.push(url.origin);
            return req.abort();
          }
          const send = (data, status = 200) =>
            req.respond({status, contentType: 'application/json', body: JSON.stringify(data)});
          if (url.pathname.startsWith('/api/'))
            calls.push({
              path: url.pathname,
              query: url.searchParams.toString(),
              method: req.method(),
            });
          if (url.pathname === '/api/v1/auth/me') return send({user});
          if (url.pathname === '/api/v1/auth/modules')
            return send({tenant_id: 1, modules: [{module_code: 'geo', available: true}]});
          if (url.pathname === '/api/v1/geo/tenants')
            return send({tenants: [{id: 1, name: '合成客户'}]});
          if (url.pathname === '/api/v1/geo/projects')
            return send({projects: [{id: 10, tenant_id: 1, name: '合成项目', status: 'active'}]});
          if (url.pathname === '/api/v1/geo/workbench/onsite-tasks')
            return send({
              module: 'geo',
              tenant_id: 1,
              scope_id: 10,
              can_create: false,
              items: [],
              next_before_id: null,
            });
          if (url.pathname.endsWith('/search-visibility'))
            return send({state: 'ready', latest: null, weeks: []});
          if (url.pathname.includes('/client/') || url.pathname.endsWith('/executions')) {
            if (scenario === 'not-open') return send({detail: 'INTERNAL_MUST_NOT_RENDER'}, 404);
            const resource = url.pathname.endsWith('/executions')
              ? 'executions'
              : url.pathname.split('/client/')[1];
            if (scenario === 'read-unavailable' && resource !== 'executions')
              return send(
                {
                  detail: {
                    code: 'GEO_CLIENT_READ_UNAVAILABLE',
                    message: 'INTERNAL_MUST_NOT_RENDER',
                  },
                },
                503,
              );
            if (scenario === 'partial-failure' && ['overview', 'content'].includes(resource))
              return send({detail: 'INTERNAL_MUST_NOT_RENDER'}, 503);
            if (resource === 'questions' && url.searchParams.has('cursor'))
              return send(
                envelope(listPage([{...question, id: 4, question: '第二页合成问题'}]), 'questions'),
              );
            const data = structuredClone(
              geoFixture(resource, {
                more: resource === 'questions',
                ready: scenario === 'ready-zero',
              }),
            );
            // Exercise the browser's independent guard against a malformed available link.
            if (resource === 'answers/5') {
              data.data.citations[0].url += '&utm_source=fixture';
              data.data.citations.push({url: 'https://example.com/a?token=SYNTHETIC_URL_CREDENTIAL',
                domain: 'example.com', url_state: 'available', is_own_domain: true});
            }
            if (scenario === 'empty') {
              if (data.scope) {
                data.scope.binding_state = 'unbound';
                data.scope.business_count = 0;
                data.scope.question_count = 0;
              }
              if (data.data?.items) {
                data.data.items = [];
                data.data.pagination = {
                  limit: 20,
                  returned_count: 0,
                  total_count: 0,
                  has_more: false,
                  next_cursor: null,
                  truncated: false,
                };
              }
              if (resource === 'overview') {
                for (const group of ['content', 'monitoring'])
                  for (const key of Object.keys(data.data[group]))
                    if (typeof data.data[group][key] === 'number') data.data[group][key] = 0;
              }
            }
            return send(data);
          }
          if (url.pathname.startsWith('/api/')) return send({}, 404);
          try {
            const r = await fetch(fixture.origin + url.pathname + url.search);
            await req.respond({
              status: r.status,
              contentType: r.headers.get('content-type'),
              body: Buffer.from(await r.arrayBuffer()),
            });
          } catch {
            await req.abort();
          }
        });
        await p.setViewport({width: 1440, height: 1000});
        await p.goto(origin + '/customer-workbench/?module=geo&tenant_id=1&project_id=10');
        await p.waitForSelector('[data-geo-workspace]');
        await p.waitForFunction(
          () =>
            document.querySelector('[data-geo="tab"][data-tab="data"]') ||
            document.querySelector('.geo-workspace')?.textContent.includes('暂未开放') ||
            document.querySelector('.geo-workspace')?.textContent.includes('读取暂不可用'),
        );
        await assertNoPatrolControls(p);
        if (scenario === 'not-open') {
          assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /暂未开放/);
          assert.equal(await p.$('[data-tab=content]'), null);
          assert(await p.$('[data-tab=deliveries]'));
          assert.equal(await p.$('[data-action^="onsite-"]'), null);
          assert(await p.$('.sv-card'));
        } else {
          await p.waitForFunction(() => document.querySelector('[data-tab=plan]'));
          if (scenario === 'empty') {
            assert.equal(await p.$('[data-tab=content]'), null);
            assert(await p.$('[data-tab=deliveries]')); // Empty citation results still expose the read-only entry.
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /当前项目尚未关联业务/,
            );
          }
          if (scenario === 'partial-failure') {
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /待确认稿件读取失败/,
            );
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /最近已加载 1 项服务任务/,
            );
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /数据量较大或读取暂不可用/,
            );
          }
          const home = await p.$eval('.geo-workspace', (e) => e.textContent);
          await assertNoPatrolControls(p);
          assert(!home.includes('INTERNAL_MUST_NOT_RENDER'));
          if (scenario === 'ready-zero') assert.match(home, /0%/);
          else assert(!home.includes('0%'));
          if (scenario === 'read-unavailable') {
            assert.match(home, /数据量较大或读取暂不可用/);
            assert.equal(await p.$('[data-action^="onsite-"]'), null);
            assert(await p.$('.sv-card'));
            assert.equal(await p.$('[data-sv=run]'), null);
            await p.click('[data-tab=progress]');
            assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /项目进度/);
            await p.click('[data-tab=plan]');
            await assertNoPatrolControls(p);
            assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /服务计划/);
            await p.click('[data-tab=home]');
            await p.click('[data-resource=content]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('读取暂不可用'),
            );
            assert(await p.$('[data-geo=retry]'));
            await p.setViewport({width: 390, height: 844});
            assert.equal(
              await p.evaluate(() => document.documentElement.scrollWidth > innerWidth),
              false,
            );
            await p.screenshot({
              path: path.join(shots, 'read-unavailable-mobile.png'),
              fullPage: true,
            });
          }
          if (scenario === 'insufficient') {
            await p.screenshot({path: path.join(shots, 'home-desktop.png'), fullPage: true});
            const beforeBroken = calls.length;
            await p.$eval('[data-resource=content]', (element) => {
              element.dataset.params = '{broken';
            });
            await p.click('[data-resource=content]');
            assert.match(await p.$eval('[role=alert]', (e) => e.textContent), /操作参数无法读取/);
            assert.equal(calls.length, beforeBroken);
            await p.click('[data-tab=progress]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('仅最近 20 项'),
            );
            const progress = await p.$eval('.geo-workspace', (e) => e.textContent);
            assert.match(progress, /最多 200 个问题/);
            assert(!progress.includes('DO_NOT_DISPLAY'));
            await p.click('[data-tab=plan]');
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /不代表承诺每日自动检测/,
            );
            await p.click('[data-tab=content]');
            await p.waitForSelector('[data-resource="content/7"]');
            await p.click('[data-resource="content/7"]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-prose')?.textContent.includes('母稿全文'),
            );
            assert.match(
              await p.$eval('.geo-workspace', (e) => e.textContent),
              /历史版本已确认，当前版本尚无有效确认记录/,
            );
            assert.equal(await p.$('.geo-workspace img'), null);
            await p.click('[data-resource="content/7/variants"]');
            await p.waitForSelector('[data-resource="content/7/variants/11"]');
            await p.click('[data-resource="content/7/variants/11"]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-prose')?.textContent.includes('合成渠道稿全文'),
            );
            await p.click('[data-resource="content/7/articles/9"]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('当前母稿'),
            );
            await p.click('[data-tab=deliveries]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('原生投递回执'),
            );
            assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /尚无有效匹配证据/);
            await p.click('[data-tab=data]');
            await p.waitForSelector('[data-resource=questions]');
            await p.click('[data-resource=questions]');
            await p.waitForSelector('[data-resource="questions/3"]');
            await assertNoPatrolControls(p);
            assert(!(await p.$eval('.geo-workspace', (e) => e.textContent.includes('100%'))));
            await p.click('[data-geo=more]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('第二页合成问题'),
            );
            assert.equal(await p.$('[data-geo=more]'), null);
            await p.click('[data-resource="questions/3"]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-workspace')?.textContent.includes('本统计周期已存回答'),
            );
            await p.click('[data-resource=answers][data-params*="question_id"]');
            await p.waitForSelector('[data-resource="answers/5"]');
            await p.click('[data-resource="answers/5"]');
            await p.waitForFunction(() =>
              document.querySelector('.geo-prose')?.textContent.includes('合成回答完整原文'),
            );
            assert.equal(await p.$('.geo-workspace script'), null);
            const citationLinks = await p.$$eval('.geo-workspace a', (nodes) => nodes.map((node) => node.href));
            assert.deepEqual(citationLinks, ['https://example.com/evidence?id=123']);
            assert.match(await p.$eval('.geo-workspace', (e) => e.textContent), /docs.example.com（链接未开放）/);
            assert(!(await p.$eval('.geo-workspace', (e) => e.innerHTML)).includes('SYNTHETIC_URL_CREDENTIAL'));
            assert(!(await p.$eval('.geo-workspace', (e) => e.innerHTML)).includes('utm_source'));

            assert.equal(await p.evaluate(() => globalThis.bad), undefined);
            await p.setViewport({width: 390, height: 844});
            assert.equal(
              await p.evaluate(() => document.documentElement.scrollWidth > innerWidth),
              false,
            );
            await p.screenshot({path: path.join(shots, 'answer-mobile.png'), fullPage: true});
            await p.click('[data-tab=onsite]');
            await p.waitForFunction(() => document.querySelector('.geo-workspace')?.textContent.includes('站内 GEO 建议'));
            await assertNoPatrolControls(p);
            assert.equal(await p.$('[data-action^="onsite-"]'), null);
          }
        }
        assert.deepEqual(errors, []);
        assert.deepEqual(external, []);
        assert(calls.every((c) => c.method === 'GET'));
        assert(!calls.some((c) => c.path.includes('/visibility-patrol/')));
        assert(
          !calls.some((c) => c.path.includes('/integration/') || c.path.includes('assistant')),
        );
        await p.close();
      }
      console.log('Synthetic GEO browser screenshots: ' + shots);
    } finally {
      await browser.close();
      await fixture.close();
    }
  },
);
