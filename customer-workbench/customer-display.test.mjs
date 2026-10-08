import test from 'node:test';
import assert from 'node:assert/strict';
import {statusLabel, reasonLabel, fieldLabel, formatTime, formatMetric, escapeText} from './js/customer-display.mjs';

test('missing observations stay missing while actual zero remains visible', () => {
  for (const value of [null, undefined, '', ' ', false, [], {}, NaN, Infinity, 'not_loaded']) assert.equal(formatMetric(value), '—');
  assert.equal(formatMetric(0, {unit:'次'}), '0次');
  assert.equal(formatMetric('0.0'), '0');
  assert.equal(formatMetric('1234.56', {digits:2, unit:'元'}), '1,234.56元');
});

test('ready content is not labelled customer confirmed or completed', () => {
  assert.equal(statusLabel('ready'), '稿件已备好');
  assert.equal(statusLabel('approved', 'confirmation'), '当前版本已确认');
  assert.match(statusLabel('stale', 'confirmation'), /旧确认不适用/);
  assert.equal(statusLabel('ready', 'task'), '状态待核对');
  assert.equal(statusLabel('new_backend_state'), '状态待核对');
  assert.equal(statusLabel('constructor'), '状态待核对');
  assert.equal(reasonLabel('constructor'), '需要顾问核对具体原因');
});

test('explicit timezone offsets resolve consistently in Shanghai', () => {
  assert.equal(formatTime('2026-10-07T16:05:23.123456Z'), '2026/10/08 00:05');
  assert.equal(formatTime('2026-10-08T00:05:23+08:00'), '2026/10/08 00:05');
  assert.equal(formatTime('2026-10-07T23:05:23-04:00'), '2026/10/08 11:05');
  assert.equal(formatTime('2026-10-07T16:05:23Z', {dateOnly:true}), '2026/10/08');
});

test('dates and timestamps with unspecified timezone are not guessed', () => {
  assert.equal(formatTime('2026-10-08'), '2026/10/08');
  assert.equal(formatTime('2026-10-08 00:05:23.123456'), '2026/10/08 00:05（时区未提供）');
  for (const value of ['2026-02-30', '2026-02-30T12:00:00Z', '2026-10-08T24:00:00Z', '2026-10-08T00:60:00Z', 'yesterday', '1']) assert.equal(formatTime(value), '时间待核对');
  assert.equal(formatTime(null), '时间未提供');
});

test('labels describe responsibility without suggesting client permission escalation', () => {
  assert.equal(reasonLabel('content_and_site_edit_permissions_required'), '此项由本站顾问管理');
  assert.equal(reasonLabel('capture_disabled'), '页面检查未开启，请顾问处理');
  assert.equal(fieldLabel('clicks'), '搜索点击');
  assert.equal(fieldLabel('unexpected_backend_key'), '其他信息');
  assert.equal(escapeText('<p title="a">&\'</p>'), '&lt;p title=&quot;a&quot;&gt;&amp;&#39;&lt;/p&gt;');
});
