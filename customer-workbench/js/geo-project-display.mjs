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
  return `<p class="geo-open-week">进行中本周（未结束）：已保存 ${n} 条真实 API 回答（当前非品牌点名范围）。${n === 0 ? '暂无已保存回答；尝试或失败情况请查看逐模型状态。' : ''}下周一结束本周后，符合正式资格的回答才可计入正式周；保存不等于计入。</p>`;
}
export function geoQuestionOpenWeek(count) {
  return Number.isSafeInteger(count) && count > 0
    ? `<p class="geo-question-open-week">进行中本周已保存 ${count} 条回答，周结束后仍须通过正式资格检查</p>` : '';
}
