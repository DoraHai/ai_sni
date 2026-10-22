// Presentation only: the server owns the formal week, qualification and counts.
const shanghaiDate = (timestamp) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(timestamp));
  const part = (type) => parts.find((p) => p.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
};
export function geoPeriod(period) {
  const start = typeof period?.start === 'string' ? Date.parse(period.start) : NaN;
  const end = typeof period?.end === 'string' ? Date.parse(period.end) : NaN;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return '统计周期：暂无';
  return `统计周期：${shanghaiDate(start)} 至 ${shanghaiDate(end - 86400000)}（北京时间）`;
}
export function geoOpenWeekProgress(progress) {
  const n = progress?.detected_answer_count;
  if (!Number.isSafeInteger(n) || n < 0) return '';
  return `<p class="geo-open-week">本周（未结束）${n > 0 ? `已检测 ${n} 条，下周一计入正式指标` : '暂未检测'}</p>`;
}
export function geoQuestionOpenWeek(count) {
  return Number.isSafeInteger(count) && count > 0
    ? `<p class="geo-question-open-week">本周（未结束）已检测 ${count} 条，下周一计入</p>` : '';
}
