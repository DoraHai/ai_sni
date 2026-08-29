const TIMEZONE_SUFFIX = /(?:z|[+-]\d{2}:?\d{2})$/i

/** Parse backend timestamps that are stored as naive UTC without guessing local time. */
export function parseUtcTimestamp(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  const text = value.trim()
  const normalized = TIMEZONE_SUFFIX.test(text) ? text : `${text}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}
