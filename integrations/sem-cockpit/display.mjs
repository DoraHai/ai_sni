// Pure display helpers for validated sem-cockpit-v1 responses. No network or storage.
const count = value => Number.isSafeInteger(value) && value >= 0;
const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;

export function semMetric(value, unit, coverage) {
  const status = coverage?.status ?? 'observed';
  if (status === 'no_data' || value == null) return { text: '暂无数据', value: null, state: 'no_data' };
  if (status !== 'observed' || !number(value)
      || (unit === 'count' && !count(value))
      || (unit === 'ratio' && value > 1)
      || !['count', 'CNY', 'CNY/click', 'ratio'].includes(unit)) {
    return { text: '数据待核对', value: null, state: 'invalid' };
  }
  const format = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
  const displayNumber = unit === 'ratio' ? value * 100 : value;
  const formatted = displayNumber > 0 && displayNumber < 0.01 ? '<0.01' : format.format(displayNumber);
  const text = unit === 'ratio' ? `${formatted}%`
    : unit === 'CNY' ? `¥${formatted}`
      : unit === 'CNY/click' ? `¥${formatted}/次` : formatted;
  if (!Array.isArray(coverage?.missing_dates)) {
    return { text, value: null, observedValue: value, state: 'coverage_unknown', note: '覆盖范围尚未确认，不能作为完整期间结果。' };
  }
  if (coverage.missing_dates.length) {
    const label = ['count', 'CNY'].includes(unit) ? '已观测小计' : '已有记录计算值';
    return { text: `${label} ${text}`, value: null, observedValue: value, state: 'partial',
      missingDates: [...coverage.missing_dates], note: `缺少 ${coverage.missing_dates.length} 天报告，不能作为完整期间结果。` };
  }
  return { text, value, state: 'available', note: '所选日期未发现缺报；上游完整性仍未知。' };
}

export function semPhoneClicks(phone) {
  const note = '电话按钮点击不等于拨通电话或有效咨询。';
  if (!phone || phone.status === 'no_data') return { text: '暂无数据', value: null, state: 'no_data', note };
  if (phone.status === 'unavailable') return { text: '缺少点击依据', value: null, state: 'unavailable', note };
  if (phone.status === 'partial' && phone.value === null && count(phone.known_subtotal)) {
    return { text: `已知小计 ${phone.known_subtotal} 次`, value: null, knownSubtotal: phone.known_subtotal, state: 'partial', note: `部分记录缺少依据，不能作为完整总数。${note}` };
  }
  // Do not infer a complete total from a subtotal or an unrecognized status.
  if (phone.status === 'observed' && count(phone.value) && phone.unknown_rows === 0) {
    return { text: `${phone.value} 次`, value: phone.value, state: 'available', note: `仅覆盖已有报告记录。${note}` };
  }
  return { text: '数据待核对', value: null, state: 'invalid', note };
}
