const TIMEZONE_SUFFIX = /(?:z|[+-]\d{2}:?\d{2})$/i

/** Parse backend timestamps that are stored as naive UTC without guessing local time. */
export function parseUtcTimestamp(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  const text = value.trim()
  const normalized = TIMEZONE_SUFFIX.test(text) ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Format a backend UTC timestamp in the user's local timezone. */
export function formatUtcTimestamp(value, { fallback = '—', short = false, timeZone } = {}) {
  const date = parseUtcTimestamp(value)
  if (!date) return fallback
  const options = {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }
  if (!short) options.year = 'numeric'
  if (timeZone) options.timeZone = timeZone
  return date.toLocaleString('zh-CN', options)
}

/** Build a calendar date without converting it through UTC. */
export function formatLocalDate(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
