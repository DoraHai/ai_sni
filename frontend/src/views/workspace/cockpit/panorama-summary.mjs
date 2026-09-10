const ATTENTION_STATES = new Set(['partial', 'no_data', 'unavailable', 'denied', 'loading'])
const DELIVERY_STATES = new Set(['no_data', 'unavailable', 'denied', 'loading'])

function needsAttention(card) {
  return Number(card?.urgentCount) > 0 || ATTENTION_STATES.has(card?.state)
}

function belongsToDelivery(card) {
  return Number(card?.urgentCount) > 0 || DELIVERY_STATES.has(card?.state)
}

export function buildPanoramaSummary(cards = []) {
  const scoped = Array.isArray(cards) ? cards.filter(card => card && typeof card.id === 'string') : []
  const attention = scoped.filter(needsAttention)
  const outcomes = scoped.filter(card => card.state === 'available' && !needsAttention(card))

  return {
    outcomes: outcomes.slice(0, 3),
    attention: attention
      .sort((left, right) => Number(right.urgentCount || 0) - Number(left.urgentCount || 0))
      .slice(0, 3),
    groups: [
      { id: 'performance', title: '趋势与投入', note: '看变化，核对投放与搜索表现', cards: scoped.filter(card => card.moduleCode === 'sem' && !belongsToDelivery(card)) },
      { id: 'presence', title: '内容与品牌', note: '看产出，追查内容、页面与品牌依据', cards: scoped.filter(card => card.moduleCode !== 'sem' && !belongsToDelivery(card)) },
      { id: 'delivery', title: '待办与结果', note: '看待处理、缺失与暂不可用证据', cards: scoped.filter(belongsToDelivery) },
    ],
  }
}
