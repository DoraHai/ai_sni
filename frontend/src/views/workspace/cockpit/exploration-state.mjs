const readableStates = new Set(['available', 'ready', 'partial'])
const normalizeSiteId = value => {
  const siteId = Number(value)
  return Number.isSafeInteger(siteId) && siteId > 0 ? siteId : null
}

export function explorationPath(scope) {
  return {
    metricId: scope.metricId || null,
    moduleCode: scope.moduleCode || 'all',
    dateStart: scope.dateStart,
    dateEnd: scope.dateEnd,
    seoSiteId: normalizeSiteId(scope.seoSiteId),
    source: scope.source || 'user',
  }
}

export function appendExplorationPath(history, index, path, limit = 30) {
  const next = explorationPath(path)
  const current = history[index]
  const same = current && ['metricId', 'moduleCode', 'dateStart', 'dateEnd', 'seoSiteId'].every(key => current[key] === next[key])
  if (same) return { history, index }
  const appended = [...history.slice(0, index + 1), next].slice(-limit)
  return { history: appended, index: appended.length - 1 }
}

export function moveExplorationPath(history, index, direction) {
  const nextIndex = Math.max(0, Math.min(history.length - 1, index + direction))
  return { index: nextIndex, path: history[nextIndex] || null }
}

function comparableValue(display) {
  const match = String(display ?? '').trim().match(/^([¥￥]?)([-+]?\d+(?:,\d{3})*(?:\.\d+)?)(%?)$/)
  if (!match) return null
  return { value: Number(match[2].replace(/,/g, '')), prefix: match[1], suffix: match[3] }
}
const displayedWithUnit = (display, unit) => unit && !String(display).trim().endsWith(unit) ? `${display}${unit}` : String(display)

export function saveMetricScope(card, scope) {
  if (!card) return null
  return {
    tenantId: Number(scope.tenantId), metricId: card.id, label: card.label,
    moduleCode: card.moduleCode, dateStart: scope.dateStart, dateEnd: scope.dateEnd,
    seoSiteId: normalizeSiteId(scope.seoSiteId),
    display: card.display ?? '—', unit: card.unit || '', state: card.state, comparable: comparableValue(card.display),
  }
}

export function compareMetricScope(card, saved, scope) {
  if (!saved) return { status: 'missing', message: '尚未保存可比较的指标范围。' }
  if (!card) return { status: 'missing', message: '当前没有选中指标，无法比较。' }
  if (Number(saved.tenantId) !== Number(scope.tenantId)) return { status: 'scope_mismatch', message: '保存范围属于其他客户，无法比较。' }
  if (saved.metricId !== card.id) return { status: 'metric_mismatch', message: `保存的是“${saved.label}”，只能选择同一指标比较。` }
  if ((saved.moduleCode === 'seo' || card.moduleCode === 'seo') && saved.seoSiteId !== normalizeSiteId(scope.seoSiteId)) return { status: 'site_mismatch', message: '保存范围属于其他 SEO 网站，无法比较。' }
  const current = comparableValue(card.display)
  if (!readableStates.has(saved.state) || !readableStates.has(card.state)) return { status: 'unavailable', message: '当前值或保存值缺失，无法计算差值。' }
  const currentUnit = card.unit || ''
  if (!saved.comparable || !current || saved.unit !== currentUnit || saved.comparable.prefix !== current.prefix || saved.comparable.suffix !== current.suffix) return { status: 'incomparable', message: '该指标当前不是同一单位的可计算数值，无法比较差值。' }
  const delta = current.value - saved.comparable.value
  const shown = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(delta)
  const deltaDisplay = current.suffix === '%' || currentUnit === '%'
    ? `${delta > 0 ? '+' : ''}${shown} 个百分点`
    : `${current.prefix}${delta > 0 ? '+' : ''}${shown}${current.suffix}${currentUnit}`
  return { status: 'ready', currentDisplay: displayedWithUnit(card.display, currentUnit), savedDisplay: displayedWithUnit(saved.display, saved.unit), delta, deltaDisplay }
}
