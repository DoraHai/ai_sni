import assert from 'node:assert/strict';
import test from 'node:test';
import { MODULES, moduleScope, scopedMetrics, taskInModuleScope, taskScopeReference, planInModuleScope, panelInModuleScope, navigationAccess, moduleEntryAccess } from './module-scope.mjs';

test('module entries map only entitled modules to reviewed cards', () => {
  const cards = { sem: 'trend', seo: 'content', geo: 'heatmap' };
  for (let mask = 1; mask < 8; mask++) {
    const enabled = MODULES.filter((_, index) => mask & (1 << index));
    for (const module of MODULES) {
      const access = moduleEntryAccess(module, enabled);
      assert.equal(access.allowed, enabled.includes(module));
      assert.equal(access.card, enabled.includes(module) ? cards[module] : null);
    }
  }
  assert.deepEqual(moduleEntryAccess('future', MODULES), {
    allowed: false,
    card: null,
    reason: '未知模块入口，未打开任何数据。',
  });
  assert.equal(moduleEntryAccess('seo', []).allowed, false);
});

test('partial navigation keeps common pages and exposes budget only with SEM', () => {
  for (let mask = 1; mask < 8; mask++) {
    const enabled = MODULES.filter((_, index) => mask & (1 << index));
    const full = enabled.length === MODULES.length;
    for (const page of ['panorama', 'tasks', 'quality']) {
      assert.equal(navigationAccess(page, enabled).allowed, true);
    }
    assert.equal(navigationAccess('acquisition', enabled).allowed, enabled.includes('sem'));
    for (const page of ['dashboard', 'overview']) {
      assert.equal(navigationAccess(page, enabled).allowed, full);
    }
    assert.equal(navigationAccess('module', enabled).allowed, false);
  }
  assert.deepEqual(navigationAccess('acquisition', ['seo']), {
    allowed: false,
    reason: '预算试算需要开通 SEM。',
  });
  assert.equal(navigationAccess('future', MODULES).allowed, false);
  assert.equal(navigationAccess('panorama', []).allowed, false);
});

test('panel reopening and nested destinations obey current module scope', () => {
  assert.equal(panelInModuleScope('spend', null, ['seo']), false);
  assert.equal(panelInModuleScope('sem:3', null, ['seo']), false);
  assert.equal(panelInModuleScope('seo:6', null, ['seo']), true);
  assert.equal(panelInModuleScope('results', null, ['sem', 'seo']), false);
  assert.equal(panelInModuleScope('pano_old', { card: 'trend' }, ['seo']), false);
  assert.equal(panelInModuleScope('pano_new', { card: 'content' }, ['seo']), true);
  assert.equal(panelInModuleScope('pano_mix', { card: 'journey' }, ['sem', 'seo']), false);
  assert.equal(panelInModuleScope('unknown', null, []), false);
  assert.equal(panelInModuleScope('spend', null, MODULES), true);
});

test('all seven customer combinations expose only their own cards and suggestions', () => {
  for (let mask = 1; mask < 8; mask++) {
    const enabled = MODULES.filter((_, index) => mask & (1 << index));
    const scope = moduleScope(enabled);
    assert.deepEqual(scope.enabled, enabled);
    assert.equal(scope.showCrossChannel, enabled.length === 3);
    assert.deepEqual(scope.comparisonModules, enabled.length > 1 ? enabled : []);
    const expected = [];
    if (enabled.includes('sem')) expected.push('trend', 'semkeywords', 'mix', 'funnel', 'device');
    if (enabled.includes('seo')) expected.push('organic', 'content', 'ranking');
    if (enabled.includes('geo')) expected.push('heatmap', 'citations', 'competition');
    if (enabled.length === 3) expected.push('journey');
    assert.deepEqual(scope.cards, expected);
    const questions = {
      sem: ['广告花费和点击有什么变化？', '哪些平台转化需要核实？'],
      seo: ['哪些内容还需要审核？', '发布之后，页面检查到哪一步？'],
      geo: ['哪些回答提到了品牌？', '这两周的数据可以比较吗？'],
    };
    assert.deepEqual(scope.questions, enabled.flatMap(module => questions[module].map(text => ({ module, text }))));
  }
});

test('invalid metrics cannot become business values', () => {
  for (const value of [false, '', '0', {}, [], NaN, Infinity, -Infinity]) {
    assert.deepEqual(scopedMetrics({ seo: value }, ['seo']).seo, { state: 'invalid', value: null });
  }
});

test('missing entitlement fails closed; explicit three-module demo is supported', () => {
  for (const value of [undefined, null, 'all', {}, ['unknown']]) {
    assert.equal(moduleScope(value).empty, true);
    assert.deepEqual(moduleScope(value).questions, []);
  }
  assert.deepEqual(moduleScope(['geo', 'sem', 'sem', 'seo']).enabled, MODULES);
});

test('not enabled, no data, and observed zero remain different', () => {
  assert.deepEqual(scopedMetrics({ sem: 0, seo: 45 }, ['sem', 'geo']), {
    sem: { state: 'available', value: 0 },
    seo: { state: 'not_enabled', value: null },
    geo: { state: 'no_data', value: null },
  });
});

test('cross-module tasks require every module and unknown provenance stays excluded', () => {
  assert.equal(taskInModuleScope({ modules: ['sem', 'seo'] }, ['sem']), false);
  assert.equal(taskInModuleScope({ modules: ['sem', 'seo'] }, ['sem', 'seo']), true);
  assert.equal(taskInModuleScope({ module: 'geo' }, ['geo']), true);
  assert.equal(taskInModuleScope({ module: 'sem', modules: ['seo'] }, ['seo']), false);
  assert.equal(taskInModuleScope({ module: 'seo', modules: ['seo', 'geo'] }, MODULES), false);
  assert.equal(taskInModuleScope({ module: 'seo', modules: ['seo', 'seo'] }, ['seo']), true);
  for (const task of [{}, { modules: [] }, { module: 'future' }, { modules: 'sem' }]) {
    assert.equal(taskInModuleScope(task, MODULES), false);
  }
});

test('legacy adaptation preserves explicit multi-module task provenance', () => {
  const task = { modules: ['sem', 'seo'], issue: 'allocation' };
  assert.equal(taskInModuleScope(taskScopeReference(task), ['sem', 'seo']), true);
  assert.equal(taskInModuleScope(taskScopeReference(task), ['sem']), false);
  assert.equal(taskInModuleScope(taskScopeReference({ issue: 'images' }), ['seo']), true);
  assert.equal(taskInModuleScope(taskScopeReference({ module: 'geo', issue: 'allocation' }), ['sem']), false);
});

test('plans require an explicit action mapping, never default unknown types to SEM', () => {
  assert.equal(planInModuleScope('content', ['seo']), true);
  assert.equal(planInModuleScope('geo', ['geo']), true);
  assert.equal(planInModuleScope('verify', ['sem']), true);
  assert.equal(planInModuleScope('verify', ['seo']), false);
  for (const type of ['execution', 'health', 'journey', 'future', '__proto__']) {
    assert.equal(planInModuleScope(type, MODULES), false);
  }
});
