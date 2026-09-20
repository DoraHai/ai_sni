import { validVisualization } from './visualization-model.mjs'

export function dashboardChannels(cards, modules, revision) {
  return modules.map(module => {
    const code = module.module_code
    const metrics = cards.filter(card => card.moduleCode === code && card.contextRevision === revision)
      .map(card => ({ ...card, visualization: ['available', 'partial'].includes(card.state) && validVisualization(card.visualization) ? card.visualization : null }))
    return { code, metrics, charts: metrics.filter(card => card.visualization), readable: metrics.filter(card => ['available', 'partial'].includes(card.state)).length }
  })
}
export function dashboardHighlights(channels) {
  const priority = { sem: [/消耗|花费/, /点击量|广告点击|点击$/], seo: [/收录/, /内容|发布/], geo: [/提及率/, /可见度/] }
  return channels.flatMap(channel => {
    const chosen = (priority[channel.code] || []).map(pattern => channel.metrics.find(card => pattern.test(card.label))).filter(Boolean)
    return [...new Map(chosen.map(card => [card.id, card])).values()]
  }).slice(0, 6)
}
