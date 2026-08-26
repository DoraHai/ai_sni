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
