import test from 'node:test';
import assert from 'node:assert/strict';
import {createGeoHostAdapter} from './js/geo-host-session-adapter.mjs';
import {createGeoProjectClient} from './js/geo-project-client.mjs';
import {createGeoProjectPanel} from './js/geo-project-panel.mjs';
import {
  geoHome,
  geoResource,
  geoExecutions,
  geoWeekly,
  geoSafeLink,
  geoObservation,
} from './js/geo-project-view.mjs';
import {geoFixture, weekly, observation} from './tests/geo-client-fixture.mjs';
const response = (data, status = 200) => new Response(JSON.stringify(data), {status});
const context = {connected: true, tenantId: 1, projectId: 10, userId: 7, revision: 1};
const base = '/api/v1/geo/projects/10/client/';
const resources = [
  'overview',
  'visibility',
  'questions',
  'questions/3',
  'answers',
  'answers/5',
  'content',
  'content/7',
  'content/7/variants',
  'content/7/variants/11',
  'content/7/articles/9',
  'deliveries',
];
async function hostFixture() {
  const calls = [];
  let session = {token: 'synthetic', userId: 7, tenantId: 1, projectId: 10, revision: 1};
  let notify;
  const user = {id: 7, tenant_id: 1, permissions: {'geo.assets': 'view', 'geo.content': 'view'}};
  const host = createGeoHostAdapter({
    origin: 'https://fixture.test',
    getSession: () => session,
    subscribeSession: (fn) => {
      notify = fn;
      return () => {};
    },
    fetchImpl: async (path, options) => {
      const u = new URL(path);
      calls.push({path, options});
      if (u.pathname === '/api/v1/auth/me') return response({user});
      if (u.pathname === '/api/v1/auth/modules')
        return response({tenant_id: 1, modules: [{module_code: 'geo', available: true}]});
      if (u.pathname === '/api/v1/geo/tenants')
        return response({tenants: [{id: 1, name: '合成客户'}]});
      if (u.pathname === '/api/v1/geo/projects')
        return response({projects: [{id: 10, tenant_id: 1, status: 'active'}]});
      return response(
        geoFixture(
          u.pathname.endsWith('executions') ? 'executions' : u.pathname.split('/client/')[1],
        ),
      );
    },
  });
  await host.initialize();
  calls.length = 0;
  return {
    host,
    calls,
    change() {
      session = {...session, projectId: 11, revision: 2};
      notify();
    },
  };
}
test('A–L and executions are exact GET routes; all invalid scope/query/body/write requests stop before transport', async () => {
  const {host, calls} = await hostFixture();
  for (const resource of resources) await host.transport(base + resource + '?tenant_id=1');
  await host.transport('/api/v1/geo/projects/10/executions?tenant_id=1');
  await host.transport(
    base +
      'answers?tenant_id=1&week_end=2026-10-19&question_id=3&engine_key=a.b-c_d&source_kind=real&eligibility=qualified&limit=100&cursor=opaque',
  );
  const accepted = calls.length;
  for (const resource of resources)
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE'])
      await assert.rejects(host.transport(base + resource + '?tenant_id=1', {method}), /DENIED/);
  for (const path of [
    base + 'overview/',
    base + 'overview/settings',
    base + 'content/7/variants/11/retry',
    base + 'questions/0',
    base + 'answers/9007199254740992',
    base.replace('/10/', '/11/') + 'overview',
    '/api/v1/geo/projects/10/service-plan',
    '/api/v1/geo/integration/read/answers',
    'https://fixture.test' + base + 'overview',
    base + '%6fverview',
  ])
    await assert.rejects(host.transport(path + '?tenant_id=1'), /DENIED/);
  for (const query of [
    'tenant_id=2',
    'tenant_id=1&tenant_id=1',
    'tenant_id=1&business_id=1',
    'tenant_id=1&project_id=10',
    'tenant_id=1&limit=101',
    'tenant_id=1&limit=0',
    'tenant_id=1&limit=1e1',
    'tenant_id=1&cursor=',
    'tenant_id=1&cursor=' + 'x'.repeat(4097),
    'tenant_id=1&status=paused',
    'tenant_id=1&q=' + 'x'.repeat(101),
    'tenant_id=1&week_end=tomorrow',
  ])
    await assert.rejects(host.transport(base + 'questions?' + query), /DENIED|MISMATCH/);
  for (const resource of resources)
    await assert.rejects(
      host.transport(base + resource + '?tenant_id=1', {body: '{}'}),
      /BODY_DENIED/,
    );
  assert.equal(calls.length, accepted);
  assert(calls.every((c) => c.options.method === 'GET'));
  host.dispose();
});
test('project client checks all response scopes, closed weeks, pagination, and executions project', async () => {
  const {host} = await hostFixture();
  const c = createGeoProjectClient({transport: host.transport, getContext: host.getContext});
  for (const resource of [...resources, 'executions']) assert(await c.read(resource));
  host.dispose();
  for (const mutate of [
    (v) => (v.tenant_id = 2),
    (v) => (v.project_id = 11),
    (v) => (v.schema_version = 'old'),
    (v) => (v.read_only = false),
    (v) => (v.basis.period.closed = false),
    (v) => (v.basis.period.timezone = 'UTC'),
    (v) => (v.basis.period.week_end = '2026-10-12'),
  ]) {
    const value = structuredClone(geoFixture('overview'));
    mutate(value);
    const client = createGeoProjectClient({
      getContext: () => context,
      transport: async () => response(value),
    });
    await assert.rejects(client.read('overview', {week_end: '2026-10-19'}), /RESPONSE_INVALID/);
  }
  const client = createGeoProjectClient({
    getContext: () => context,
    transport: async () => response({...geoFixture('executions'), project_id: 11}),
  });
  await assert.rejects(client.read('executions'), /RESPONSE_INVALID/);
});
test('identity, client invalidation and late JSON prevent old responses from becoming readable', async () => {
  for (const mode of ['scope', 'revision', 'invalidate']) {
    let ctx = {...context},
      release;
    const client = createGeoProjectClient({
      getContext: () => ctx,
      transport: async () => ({
        ok: true,
        status: 200,
        json: () => new Promise((r) => (release = r)),
      }),
    });
    const pending = client.read('overview');
    await Promise.resolve();
    if (mode === 'scope') ctx = {...ctx, projectId: 11};
    else if (mode === 'revision') ctx = {...ctx, revision: 2};
    else client.invalidate();
    release(geoFixture('overview'));
    await assert.rejects(pending, /CONTEXT_CHANGED/);
  }
});
test('404/405/409/503 and arbitrary error bodies become only safe error codes', async () => {
  for (const [status, code] of [
    [404, 'GEO_NOT_OPEN'],
    [405, 'GEO_NOT_OPEN'],
    [409, 'GEO_SCOPE_CHANGED'],
    [503, 'GEO_READ_UNAVAILABLE'],
  ]) {
    const client = createGeoProjectClient({
      getContext: () => context,
      transport: async () => response({detail: 'PRIVATE_INTERNAL_ERROR'}, status),
    });
    await assert.rejects(
      client.read('overview'),
      (e) => e.code === code && !e.message.includes('PRIVATE'),
    );
  }
});
test('null metrics, qualified true zero, observation fractions, confirmations and native delivery distinctions', () => {
  assert.match(geoWeekly(weekly()), /检测数据还不够/);
  assert(!geoWeekly(weekly()).includes('0%'));
  assert.match(geoWeekly(weekly(true)), />0%/);
  assert(!geoWeekly(weekly()).includes('undefined'));
  for (const [x, y] of [
    [1, 1],
    [0, 1],
    [0, 0],
  ]) {
    const text = geoObservation(observation(x, y));
    assert(!text.includes('%'));
    assert.match(text, y ? new RegExp(`${x}/${y}`) : /尚无/);
  }
  const content = geoResource('content/7', geoFixture('content/7'));
  assert.match(content, /历史版本已确认，当前版本尚无有效确认记录/);
  assert(!content.includes('<img'));
  const html = geoResource('deliveries', geoFixture('deliveries'));
  for (const text of [
    '原生发布登记',
    '原生投递回执',
    '尚无有效匹配证据',
    '不代表正式客户验收',
    '回执不等于',
  ])
    assert(html.includes(text));
  assert(!geoResource('answers/5', geoFixture('answers/5')).includes('<script>'));
  const executions = geoExecutions(geoFixture('executions'));
  for (const text of ['仅最近 20 项', '仅最多 200 个问题', '单项证据仅为已加载预览'])
    assert(executions.includes(text));
  assert(!executions.includes('DO_NOT_DISPLAY'));
  assert(!geoExecutions(geoFixture('executions'), true).includes('DO_NOT_DISPLAY'));
  const slots = Object.fromEntries(
    ['overview', 'visibility', 'executions'].map((r) => [r, {value: geoFixture(r)}]),
  );
  const home = geoHome(slots);
  assert.match(home, /当前待确认.*1 项稿件/);
  assert.match(home, /仅最近20项/);
  assert.match(home, /月度计划/);
  assert.match(home, /上海时区已结束完整周/);
});
test('content and citation links reject scripts, credential URLs, local hosts and embedded credentials', () => {
  for (const url of [
    'javascript:alert(1)',
    'data:text/html,test',
    'file:///a',
    'https://user:pass@example.com',
    'https://example.com/a?token=fixture',
    'http://127.1/a',
    'http://0x7f000001',
    'http://[::1]',
    'http://intranet',
    'http://host.local/a',
    'http://a.internal/a',
  ])
    assert(!geoSafeLink(url).includes('href='), url);
  assert.match(geoSafeLink('https://example.com/a#heading'), /href="https:\/\/example.com\/a"/);
});
test('panel pins server week, hides empty tabs and clears immediately on reset including late bootstrap responses', async () => {
  const calls = [],
    held = [];
  let delay = false;
  const node = {innerHTML: ''};
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        calls.push(path);
        const r = path.includes('/client/')
          ? path.split('/client/')[1].split('?')[0]
          : 'executions';
        if (delay)
          return new Promise((resolve) => held.push(() => resolve(response(geoFixture(r)))));
        return response(geoFixture(r));
      },
    },
  });
  panel.renderInto(node);
  await panel.refresh();
  assert.match(node.innerHTML, /本期要点/);
  assert.match(node.innerHTML, /交付记录/);
  for (const path of calls.filter((p) => /client\/(visibility|questions)/.test(p)))
    assert.match(path, /week_end=2026-10-19/);
  delay = true;
  const pending = panel.refresh();
  await Promise.resolve();
  panel.reset();
  held.forEach((fn) => fn());
  await pending;
  assert(!node.innerHTML.includes('合成内容任务'));
  assert(!node.innerHTML.includes('当前归属问题 3'));
  panel.dispose();
});
test('malformed lists/details fail closed, unknown metadata is omitted and incomparable trends stay hidden', async () => {
  for (const [resource, mutate] of [
    ['questions', (v) => delete v.data.pagination],
    ['content/7', (v) => (v.data.master.task_id = 8)],
    ['content/7/variants/11', (v) => (v.data.variant.id = 12)],
    ['answers/5', (v) => (v.data.item.id = 6)],
  ]) {
    const value = structuredClone(geoFixture(resource));
    mutate(value);
    const client = createGeoProjectClient({
      getContext: () => context,
      transport: async () => response(value),
    });
    await assert.rejects(client.read(resource), /RESPONSE_INVALID/);
  }
  const value = structuredClone(geoFixture('visibility', {ready: true}));
  value.data.definitions.internal = 'DO_NOT_DISPLAY_INTERNAL';
  value.data.current.metrics[1].trend_7d = {direction: 'up', change_abs: 99, change_pct: 100};
  const html = geoResource('visibility', value);
  assert(!html.includes('DO_NOT_DISPLAY'));
  assert(!html.includes('较上周增加'));
  const ex = geoFixture('executions');
  ex.items = Array.from({length: 20}, (_, i) => ({...ex.items[0], id: i + 1}));
  ex.prompts = Array.from({length: 200}, (_, i) => ({id: i + 1, question: '合成问题 ' + i}));
  const progress = geoExecutions(ex);
  assert.match(progress, /最近已加载 20 项/);
  assert.match(progress, /非完整项目总量/);
  assert.match(progress, /最多 200 个问题/);
  assert(!progress.includes('100%'));
  const unavailable = geoHome({
    overview: {error: 'GEO_NOT_OPEN'},
    visibility: {error: 'GEO_NOT_OPEN'},
    executions: {error: 'GEO_NOT_OPEN'},
  });
  assert.match(unavailable, /暂未开放/);
  assert(!unavailable.includes('0%'));
});
test('pagination scope change discards old list/cursor, retries first page, and cross-tab history restores evidence tab', async () => {
  const node = {innerHTML: ''},
    calls = [];
  let questionReads = 0;
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        const u = new URL(path, 'https://fixture.test'),
          r = u.pathname.endsWith('executions') ? 'executions' : u.pathname.split('/client/')[1];
        calls.push({resource: r, params: u.searchParams});
        if (r === 'questions' && u.searchParams.has('cursor')) return response({}, 409);
        const value = structuredClone(geoFixture(r, {more: r === 'questions'}));
        if (r === 'questions') {
          value.data.items[0].question = ++questionReads === 1 ? '旧列表已清除' : '新范围首屏';
        }
        return response(value);
      },
    },
  });
  const click = (dataset) => node.onclick({target: {closest: () => ({dataset})}});
  panel.renderInto(node);
  await panel.refresh();
  await click({geo: 'tab', tab: 'data'});
  await click({geo: 'read', resource: 'questions'});
  await click({geo: 'more'});
  assert.match(node.innerHTML, /新范围首屏/);
  assert(!node.innerHTML.includes('旧列表已清除'));
  const last = calls.at(-1);
  assert.equal(last.resource, 'questions');
  assert.equal(last.params.has('cursor'), false);
  await click({geo: 'read', resource: 'questions/3'});
  await click({geo: 'read', resource: 'content', params: '{"question_id":3}'});
  assert.equal(panel.getTab(), 'content');
  assert.equal(calls.at(-1).params.has('week_end'), false);
  assert.equal(calls.at(-1).params.get('question_id'), '3');
  await click({geo: 'back'});
  assert.equal(panel.getTab(), 'data');
  assert.match(node.innerHTML, /本周已存回答/);
  panel.dispose();
});
test('week change resets selections, history and cursors and rejects an old page delivered after new week', async () => {
  const node = {innerHTML: ''};
  let release;
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        const u = new URL(path, 'https://fixture.test'),
          r = u.pathname.endsWith('executions') ? 'executions' : u.pathname.split('/client/')[1];
        if (u.searchParams.has('cursor'))
          return new Promise(
            (resolve) =>
              (release = () => {
                const v = structuredClone(geoFixture('questions'));
                v.data.items[0].question = 'OLD_LATE_PAGE';
                resolve(response(v));
              }),
          );
        const value = structuredClone(geoFixture(r, {more: r === 'questions'})),
          week = u.searchParams.get('week_end');
        if (value.basis?.period && week) {
          value.basis.period.week_end = week;
          value.basis.period.end = week + 'T00:00:00+08:00';
        }
        if (r === 'questions')
          value.data.items[0].question = week === '2026-10-12' ? '新周首屏问题' : '原周首屏问题';
        return response(value);
      },
    },
  });
  const click = (dataset) => node.onclick({target: {closest: () => ({dataset})}});
  panel.renderInto(node);
  await panel.refresh();
  await click({geo: 'tab', tab: 'data'});
  await click({geo: 'read', resource: 'questions'});
  const pending = click({geo: 'more'});
  await Promise.resolve();
  await node.onsubmit({
    preventDefault() {},
    target: {matches: () => true, elements: {week_end: {value: '2026-10-12'}}},
  });
  release();
  await pending;
  await click({geo: 'read', resource: 'questions'});
  assert.match(node.innerHTML, /新周首屏问题/);
  assert(!node.innerHTML.includes('OLD_LATE_PAGE'));
  assert(!node.innerHTML.includes('原周首屏问题'));
  panel.dispose();
});

test('actual BE 66be297c synthetic A–L HTTP snapshots pass validation and render safely', async () => {
  const {readFileSync} = await import('node:fs');
  const snapshot = JSON.parse(
    readFileSync(new URL('./tests/geo-be-response-snapshot.json', import.meta.url), 'utf8'),
  );
  assert.equal(snapshot.backend_head, '66be297c2134e8eda39bebd0ec2455d718f8e7dc');
  assert.equal(snapshot.cases.length, 49);
  const seen = new Set();
  for (const item of snapshot.cases) {
    const client = createGeoProjectClient({
      getContext: () => ({...context, tenantId: 101, projectId: 1}),
      transport: async () => response(item.body, item.status),
    });
    if (item.status !== 200) {
      const code =
        {404: 'GEO_NOT_OPEN', 503: 'GEO_READ_UNAVAILABLE'}[item.status] ||
        (item.params.cursor ? 'GEO_CURSOR_INVALID' : 'GEO_INVALID_WEEK');
      await assert.rejects(client.read(item.resource, item.params), (error) => error.code === code);
      continue;
    }
    const value = await client.read(item.resource, item.params);
    seen.add(item.resource);
    const html =
      item.resource === 'overview'
        ? geoHome({overview: {value}})
        : geoResource(item.resource, value);
    assert.equal(typeof html, 'string');
    assert(!html.includes('undefined'), item.resource);
    if (item.scenario) {
      assert(!html.includes('SYNTHETIC_URL_CREDENTIAL'));
      assert(!html.includes('utm_source'));
      if (item.scenario === 'public_and_suppressed_query_citations') {
        assert.equal(value.data.citations[0].url, 'https://p1.example.com/a?id=123');
        assert.equal(value.data.citations[2].url, null);
        assert.equal(value.data.citations[2].domain, 'p1.example.com');
        assert.match(html, /p1.example.com（链接未开放）/);
        assert.match(html, /href="https:\/\/p1.example.com\/a\?id=123"/);
      } else if (item.scenario === 'credential_query_publication') {
        assert.equal(value.data.counts.published_records, 0);
        assert.equal(value.data.items[0].published_url, null);
        assert.match(html, /p1.example.com（链接未开放）/);
        assert(!html.includes('href='));
      } else {
        assert.equal(value.data.counts.published_records, 1);
        assert.match(html, /href="https:\/\/p1.example.com\/post\?id=123"/);
      }
    }
    if (value.data.pagination)
      assert.equal(value.data.pagination.returned_count, value.data.items.length);
    if (value.basis.period === null) assert.equal(value.basis.unknown_time_count, null);
    if (item.resource === 'visibility') {
      assert.match(
        html,
        value.data.current.sample_status === 'insufficient' ? /检测数据还不够/ : />0%/,
      );
    }
    if (item.resource === 'answers/1' && value.data.item.captured_at === null) {
      assert.match(html, /采样时间未知/);
      assert.equal(value.basis.unknown_time_scope, 'single_answer');
    }
  }
  assert.equal(seen.size, 12);
});

test('503 stays visible on home and detail while progress and other tabs remain usable', async () => {
  const node = {innerHTML: ''};
  const calls = [];
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        const resource = path.includes('/client/')
          ? path.split('/client/')[1].split('?')[0]
          : 'executions';
        calls.push(path);
        if (['overview', 'visibility', 'content/7'].includes(resource))
          return response(
            {detail: {code: 'GEO_CLIENT_READ_UNAVAILABLE', message: 'PRIVATE_ERROR'}},
            503,
          );
        return response(geoFixture(resource));
      },
    },
  });
  const click = (dataset) => node.onclick({target: {closest: () => ({dataset})}});
  panel.renderInto(node);
  await panel.refresh();
  assert.match(node.innerHTML, /数据量较大或读取暂不可用，请稍后再试/);
  assert.match(node.innerHTML, /最近已加载 1 项服务任务/);
  assert(!node.innerHTML.includes('PRIVATE_ERROR'));
  await click({geo: 'read', resource: 'content/7'});
  assert.match(node.innerHTML, /数据量较大或读取暂不可用/);
  await click({geo: 'tab', tab: 'deliveries'});
  assert.match(node.innerHTML, /原生投递回执/);
  await click({geo: 'tab', tab: 'progress'});
  assert.match(node.innerHTML, /项目进度/);
  await click({geo: 'tab', tab: 'plan'});
  assert.match(node.innerHTML, /服务计划/);
  assert.equal(calls.filter((path) => path.includes('/executions?tenant_id=1')).length, 1);
  panel.dispose();
});

test('broken button params show an alert without transport and clear on next valid navigation', async () => {
  const node = {innerHTML: ''};
  let calls = 0;
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        calls++;
        const resource = path.includes('/client/')
          ? path.split('/client/')[1].split('?')[0]
          : 'executions';
        return response(geoFixture(resource));
      },
    },
  });
  const click = (dataset) => node.onclick({target: {closest: () => ({dataset})}});
  panel.renderInto(node);
  await panel.refresh();
  const before = calls;
  for (const params of ['{broken', 'null', '[]', '42', '"text"']) {
    await click({geo: 'read', resource: 'content', params});
    assert.match(node.innerHTML, /role="alert"/);
    assert.match(node.innerHTML, /操作参数无法读取/);
    assert.equal(calls, before);
  }
  await click({geo: 'tab', tab: 'progress'});
  assert(!node.innerHTML.includes('操作参数无法读取'));
  panel.reset();
  assert(!node.innerHTML.includes('role="alert"'));
  panel.dispose();
});

test('content status and pending page verification use distinct customer labels', () => {
  for (const [state, label] of [
    ['facts_bound', '已关联事实'],
    ['needs_fix', '待修改'],
    ['adapting', '渠道适配中'],
  ]) {
    const value = structuredClone(geoFixture('content'));
    value.data.items[0].stored_status = state;
    assert(geoResource('content', value).includes(label));
  }
  const html = geoResource('deliveries', geoFixture('deliveries'));
  assert.match(html, /待页面核验/);
  assert(!html.includes('待客户确认'));
});

test('overview executions link is ignored even when it points outside the allowlist', async () => {
  const node = {innerHTML: ''},
    calls = [];
  const panel = createGeoProjectPanel({
    host: {
      getContext: () => context,
      transport: async (path) => {
        calls.push(path);
        const resource = path.includes('/client/')
          ? path.split('/client/')[1].split('?')[0]
          : 'executions';
        const value = structuredClone(geoFixture(resource));
        if (resource === 'overview')
          value.data.links.executions_path = 'https://outside.invalid/forbidden';
        return response(value);
      },
    },
  });
  panel.renderInto(node);
  await panel.refresh();
  assert(calls.includes('/api/v1/geo/projects/10/executions?tenant_id=1'));
  assert(calls.every((path) => path.startsWith('/api/v1/geo/projects/10/')));
  assert(!node.innerHTML.includes('outside.invalid'));
  panel.dispose();
});

test('search length counts Unicode characters like the BE query validator', async () => {
  const {host, calls} = await hostFixture();
  for (const resource of ['questions', 'content']) {
    await host.transport(
      base + resource + '?tenant_id=1&q=' + encodeURIComponent('😀'.repeat(100)),
    );
    const before = calls.length;
    await assert.rejects(
      host.transport(base + resource + '?tenant_id=1&q=' + encodeURIComponent('😀'.repeat(101))),
      /DENIED/,
    );
    assert.equal(calls.length, before);
  }
  host.dispose();
});


test('public citation links preserve ordinary query and strip tracking parameters', () => {
  for (const [url, expected] of [
    ['https://example.com/a?utm_source=fixture&utm_medium=test#part', 'https://example.com/a'],
    ['https://example.com/a?id=123&utm_source=fixture&gclid=tracking', 'https://example.com/a?id=123'],
    ['https://example.com/a?id=123', 'https://example.com/a?id=123'],
    ['http://example.com/a?id=1&id=2&empty=', 'http://example.com/a?id=1&amp;id=2&amp;empty='],
    ['https://example.com/a?UTM_Source=x&FBCLID=y&MSCLKID=z&spm=a&dclid=b&yclid=c&_ga=d&_gl=e', 'https://example.com/a'],
    ['https://example.com/a?%75tm_source=x&id=123', 'https://example.com/a?id=123'],
    ['https://example.com/a?monkey=1&keyboard=2&zipcode=3', 'https://example.com/a?monkey=1&amp;keyboard=2&amp;zipcode=3'],
  ]) {
    assert(geoSafeLink(url).includes(`href="${expected}"`), url);
    assert.match(geoSafeLink(url), /rel="noopener noreferrer"/);
  }
  assert(!geoSafeLink('https://example.com/a?id=123&label=%22%3E%3Cimg%20src=x%20onerror=fixture%3E', '<img src=x onerror=fixture>').includes('<img'));
});

test('credential query links show only domain, including encoded, mixed case and empty keys', () => {
  for (const key of ['token', 'access_token', 'key', 'apikey', 'secret', 'password', 'sig', 'signature',
    'auth', 'session', 'code', 'ToKeN', '%74oken', 'api_key', 'X-Amz-Signature', 'client_secret',
    'refresh_token', 'session[id]', 'utm_token', 'authorization', 'accessToken']) {
    assert.equal(geoSafeLink(`https://example.com/a?id=123&utm_source=fixture&${key}=SYNTHETIC_URL_CREDENTIAL`), 'example.com（链接未开放）');
    assert.equal(geoSafeLink(`https://example.com/a?${key}`), 'example.com（链接未开放）');
  }
  assert.equal(geoSafeLink('https://synthetic:fixture@example.com/a'), 'example.com（链接未开放）');
  for (const url of ['https://@example.com/a', 'http://[::1]/', 'http://0x7f000001/', 'http://0177.0.0.1/',
    'http://0x7f.0.0.1/', 'http://host.localdomain/', 'http://host.corp/', 'http://host.lan/', 'http://host.home/',
    'http://host.test/', 'http://host.invalid/', 'https://example.com:8443/a', 'https:example.com/a', 'https:///example.com/a', 'https://%65xample.com/a',
    'https://example.com\\@localhost/', 'https://example.com/\nfixture']) assert(!geoSafeLink(url).includes('href='), url);
});

test('suppressed citation and publication render validated domain without URL or HTML fallback', () => {
  const answer = structuredClone(geoFixture('answers/5'));
  answer.data.citations = [{url: null, domain: 'example.com', url_state: 'suppressed', is_own_domain: false}];
  let html = geoResource('answers/5', answer);
  assert.match(html, /example.com（链接未开放）/);
  assert(!html.includes('href='));
  answer.data.citations[0].domain = '<img src=x onerror=fixture>';
  html = geoResource('answers/5', answer);
  assert(!html.includes('<img'));
  assert(!html.includes('onerror'));
  const deliveries = structuredClone(geoFixture('deliveries'));
  const publication = deliveries.data.items.find((item) => item.record_type === 'publication');
  publication.url_state = 'suppressed';
  publication.published_url = null;
  publication.domain = 'example.com';
  assert.match(geoResource('deliveries', deliveries), /example.com（链接未开放）/);
});
