import test from 'node:test';
import assert from 'node:assert/strict';
import { semMetric, semPhoneClicks } from './display.mjs';
const covered = { status: 'observed', missing_dates: [] };

test('missing reports and observed zero remain distinct', () => {
  assert.equal(semMetric(0, 'CNY', { status: 'no_data' }).value, null);
  assert.equal(semMetric(null, 'count').text, '暂无数据');
  assert.equal(semMetric(0, 'count', covered).value, 0);
  assert.equal(semMetric(0, 'count', covered).state, 'available');
  assert.equal(semMetric(0, 'ratio').text, '0%');
});
test('observed totals with missing days retain only a separately labelled subtotal', () => {
  const view = semMetric(12, 'CNY', { status: 'observed', missing_dates: ['2026-09-02'] });
  assert.equal(view.value, null);
  assert.equal(view.observedValue, 12);
  assert.equal(view.state, 'partial');
  assert.match(view.text, /已观测小计/);
  assert.match(view.note, /缺少 1 天/);
  assert.equal(semMetric(12, 'CNY').state, 'coverage_unknown');
  assert.equal(semMetric(12, 'CNY').value, null);
  assert.match(semMetric(0.02, 'ratio', { ...covered, missing_dates: ['2026-09-02'] }).text, /已有记录计算值/);
});
test('ratios use percentages and small nonzero metrics do not look like zero', () => {
  assert.equal(semMetric(0.02, 'ratio').text, '2%');
  assert.equal(semMetric(0.00001, 'ratio').text, '<0.01%');
  assert.equal(semMetric(0.001, 'CNY').text, '¥<0.01');
  for (const input of ['0', NaN, Infinity, -1]) assert.equal(semMetric(input, 'count').state, 'invalid');
  assert.equal(semMetric(2, 'ratio').state, 'invalid');
});
test('phone subtotals never become totals or consultations', () => {
  const partial = semPhoneClicks({ status: 'partial', value: null, known_subtotal: 0 });
  assert.equal(partial.text, '已知小计 0 次');
  assert.equal(partial.state, 'partial');
  assert.equal(partial.value, null);
  assert.equal(partial.knownSubtotal, 0);
  assert.match(partial.note, /不能作为完整总数/);
  assert.match(partial.note, /不等于拨通电话或有效咨询/);
  assert.equal(semPhoneClicks({ status: 'observed', value: 0, unknown_rows: 0 }).text, '0 次');
  assert.equal(semPhoneClicks({ status: 'observed', value: 2, unknown_rows: 1 }).value, null);
  assert.equal(semPhoneClicks({ status: 'unavailable' }).state, 'unavailable');
  assert.equal(semPhoneClicks({ status: 'no_data' }).state, 'no_data');
});
