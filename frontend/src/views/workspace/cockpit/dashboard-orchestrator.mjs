import { validVisualization } from './visualization-model.mjs'

export const DASHBOARD_MODES = ['overview', 'priority', 'sem-focus', 'seo-focus', 'geo-focus', 'compare', 'evidence']
export const AI_STATES = ['idle', 'thinking', 'scanning', 'assembling', 'ready']
export const MOTION = { thinking: 160, scanning: 440, assemble: 960, return: 560, stagger: 90 }
export function createCommandEpoch() {
  let epoch = 0
  return { next: () => ++epoch, current: ticket => ticket === epoch, cancel: () => ++epoch }
}
export function inferDashboardIntent(text, command = {}) {
  if (/\bGEO\b|品牌提及|AI\s*可见度/i.test(text)) return 'geo-focus'
  if (/\bSEM\b|投放|点击|消耗|CPC/i.test(text)) return 'sem-focus'
  if (/今天|关注|风险|异常|优先|重要|attention|priority|risk/i.test(text)) return 'priority'
  // Only these three scenes are supported in this iteration.
  return ['sem', 'geo'].includes(command.focus_module) ? `${command.focus_module}-focus` : 'priority'
}
const readable = card => ['available', 'partial'].includes(card.state)
export function metricDisplay(card) { return readable(card) ? String(card.display ?? '—') : '—' }
export function metricStatus(card) {
  return ({ available: '已读取', partial: '部分数据', no_data: '暂无数据', unavailable: '暂不可用', denied: '无权限', loading: '读取中' })[card.state] || '待核验'
}
function delta(card) {
  if (card?.state !== 'available') return null
  const raw = String(card.changeLabel || '')
  const match = raw.match(/([+-]?\d+(?:\.\d+)?)%/)
  if (!match) return null
  const value = Number(match[1])
  return /↓|下降|减少/.test(raw) ? -Math.abs(value) : value
}
export function createDashboardPlan({ text, command = {}, cards, modules, revision }) {
  const allowed = new Set(modules.map(item => item.module_code))
  const current = cards.filter(card => allowed.has(card.moduleCode) && card.contextRevision === revision)
  const mode = inferDashboardIntent(text, command)
  const moduleCode = mode === 'priority' ? null : mode.split('-')[0]
  const candidates = moduleCode ? current.filter(card => card.moduleCode === moduleCode) : current
  let metrics
  if (mode === 'sem-focus') {
    const matches = [/展现|曝光/, /点击量|广告点击|^点击$/, /消耗|花费/, /CPC|点击价格/]
    metrics = [...new Map(matches.map(pattern => candidates.find(card => pattern.test(card.label))).filter(Boolean).map(card => [card.id, card])).values()]
  } else if (mode === 'geo-focus') {
    const core = candidates.find(card => /提及率/.test(card.label)) || candidates.find(card => /可见度/.test(card.label)) || candidates[0]
    metrics = core ? [core, ...candidates.filter(card => card.id !== core.id)].slice(0, 5) : []
  } else {
    metrics = candidates.filter(card => Number(card.urgentCount) > 0 || ['partial', 'no_data', 'unavailable', 'denied'].includes(card.state))
      .sort((a, b) => Number(b.urgentCount || 0) - Number(a.urgentCount || 0)).slice(0, 3)
  }
  const click = candidates.find(card => /点击量|广告点击|^点击$/.test(card.label))
  const cost = candidates.find(card => /消耗|花费/.test(card.label))
  const clickDelta = delta(click), costDelta = delta(cost)
  const matchedPeriod = Boolean(click?.periodLabel && click.periodLabel === cost?.periodLabel)
  const efficiency = matchedPeriod && clickDelta !== null && costDelta !== null && costDelta > clickDelta
  if (mode === 'priority' && efficiency && !metrics.some(card => card.id === cost.id)) metrics = [...metrics.slice(0, 2), cost]
  const evidence = metrics.map(card => ({ ...card, display: metricDisplay(card), changeLabel: readable(card) ? card.changeLabel : '', visualization: undefined }))
  const businessCount = evidence.filter(card => Number(card.urgentCount) > 0).length
  const boundaryCount = evidence.filter(card => !['available'].includes(card.state) && !(Number(card.urgentCount) > 0)).length
  let insight = mode === 'priority'
    ? evidence.length ? `当前提取 ${evidence.length} 项关注依据，其中 ${businessCount} 项包含待处理事项，${boundaryCount} 项需要核对数据边界。缺失或部分数据不等于业务异常。` : '当前授权范围未识别到待处理或边界异常，不代表业务没有风险。可继续查看各渠道明细。'
    : mode === 'sem-focus' ? '当前展示投放侧已读取指标；缺少转化依据时，不能判断线索质量或转化是否改善。'
      : '品牌提及、可见度和引用分别按原始口径展示；未提供模型拆分的数据，不生成模型占比。正式结论以已核验样本为准。'
  if (efficiency && mode !== 'geo-focus') insight = `${mode === 'priority' ? insight + ' ' : ''}同一统计周期内，消耗变化 ${cost.changeLabel}，点击变化 ${click.changeLabel}，消耗增速高于点击。建议进一步核对转化是否同步增长；现有数据不能证明转化下降。`
  if (!candidates.length && moduleCode) insight = `${moduleCode.toUpperCase()} 在当前授权范围暂无可用指标。请先核对模块开通、查看权限和数据读取状态。`
  const trendRequested = /趋势|变化|最近|近\s*\d+\s*天|走势/.test(text)
  const trendCandidates = trendRequested ? candidates.filter(card => readable(card) && validVisualization(card.visualization) && card.visualization.type === 'trend' && card.visualization.state === 'available') : []
  const topic = [/CPC|点击价格/i, /消耗|花费|成本/, /展现|曝光/, /点击/, /提及/, /可见度/, /收录/, /内容/].find(pattern => pattern.test(text))
  const trend = (topic && trendCandidates.find(card => topic.test(card.label))) || trendCandidates[0] || null
  return {
    mode, moduleCode, question: text, metrics: evidence, insight,
    title: ({ priority: '今日关注', 'sem-focus': 'SEM 投放关系视图', 'geo-focus': 'GEO 品牌可见性' })[mode],
    trend: trend || null, trendRequested,
    coverage: modules.filter(item => !moduleCode || item.module_code === moduleCode).map(item => {
      const list = current.filter(card => card.moduleCode === item.module_code)
      return { code: item.module_code, status: !list.length ? '尚未读取' : list.some(card => card.state !== 'available') ? '部分数据' : '已读取', count: list.length }
    }),
  }
}
