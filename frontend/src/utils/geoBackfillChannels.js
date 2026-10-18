// Generated from app/geo/content/backfill_channels.json; see scripts/generate_geo_backfill_config.py.
import config from './geoBackfillConfig.json' with { type: 'json' }

export const BACKFILL_CHANNELS = config.channels
const nameRules = config.custom_name
const categoryPattern = categories => new RegExp(`[${categories.map(c => `\\p{${c}}`).join('')}]`, 'u')
const requiredNameCharacter = categoryPattern(nameRules.required_categories)
const forbiddenNameCharacter = categoryPattern(nameRules.forbidden_categories)

export function backfillChannelLabel(channel) {
  return BACKFILL_CHANNELS.find(item => item.value === channel)?.label
    || { docs: '文档', industry_media: '行业媒体' }[channel] || channel || '—'
}

export function customChannelError(value) {
  if (forbiddenNameCharacter.test(value)) return nameRules.invisible_message
  const name = value.trim()
  if (!name || [...name].length > nameRules.max_length || !requiredNameCharacter.test(name)) {
    return nameRules.invalid_message
  }
  return ''
}

export function isHttpsPublicationUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !!url.hostname && url.port !== '0'
      && !url.username && !url.password && !/[\s\p{C}]/u.test(value)
  } catch { return false }
}
