export function questionScopeQuery(query, next, extra = {}) {
  const q = { ...query, layer: next }
  delete q.tag
  if (next === 'business') {
    delete q.business_id
    delete q.unit_id
  } else if (next === 'keyword' || Object.hasOwn(extra, 'business_id')) {
    delete q.unit_id
  }
  return { ...q, ...extra }
}

export function validQuestionScope(businessId, unitId, businesses, units) {
  const business = businesses.some(b => b.id === businessId) ? businessId : null
  if (businessId && !business) return { business_id: null, unit_id: null }
  const unit = units.find(u => u.id === unitId && (!business || u.business_id === business))
  return { business_id: business, unit_id: unit?.id || null }
}

export const isBrandEvaluation = s => s.mentions_brand === true && ['positive', 'neutral', 'negative'].includes(s.sentiment)
export function evaluationLabel(saved, evaluated) {
  return `已保存 ${saved} 条回答；有效品牌评价 ${evaluated} 条${evaluated === 0 ? '，暂不能判断评价' : evaluated < 3 ? '（小样本，至少 3 条后判断倾向）' : ''}`
}
