export function previousBeijingMonth(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).formatToParts(now)
  const year = Number(parts.find(p => p.type === 'year').value)
  const month = Number(parts.find(p => p.type === 'month').value)
  const date = new Date(Date.UTC(year, month - 2, 1))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}
export function monthRange(selectedMonth) {
  const [year, month] = selectedMonth.split('-').map(Number)
  const start = new Date(Date.UTC(year, month - 12, 1))
  return { from_month: `${start.getUTCFullYear()}-${String(start.getUTCMonth() + 1).padStart(2, '0')}`, to_month: selectedMonth }
}
export const metricText = value => value == null ? '无数据' : Number(value).toLocaleString('zh-CN')
export const beijingTime = value => value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '无数据'
export function baiduAuthorizeUrl(apiKey) {
  const query = new URLSearchParams({ response_type: 'code', client_id: apiKey, redirect_uri: 'oob', scope: 'basic', display: 'popup' })
  return `https://openapi.baidu.com/oauth/2.0/authorize?${query}`
}
export function sanitizedSecrets(form) {
  return Object.fromEntries(Object.entries(form).filter(([, value]) => value != null && String(value).trim() !== ''))
}
