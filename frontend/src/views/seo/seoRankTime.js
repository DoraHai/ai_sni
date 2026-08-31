const SEO_TIME_ZONE = 'Asia/Shanghai'
const EXPLICIT_TIME_ZONE = /(Z|[+-]\d{2}:\d{2})$/i

export function parseSeoRankTime(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = String(value || '').trim()
  if (!text) return null
  const parsed = new Date(EXPLICIT_TIME_ZONE.test(text) ? text : `${text}Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatSeoRankTime(value) {
  const parsed = parseSeoRankTime(value)
  if (!parsed) return '—'
  return parsed.toLocaleString('zh-CN', {
    timeZone: SEO_TIME_ZONE,
    hour12: false,
  })
}

export function formatSeoCsvTime(value) {
  const parsed = parseSeoRankTime(value)
  if (!parsed) return ''
  const values = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: SEO_TIME_ZONE,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    }).formatToParts(parsed).map(({ type, value: part }) => [type, part]),
  )
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}:${values.second}+08:00`
}
