export const splitLines = value => Array.isArray(value) ? value : String(value || '').split(/\n|，|,/).map(s => s.trim()).filter(Boolean)
export const joinLines = value => Array.isArray(value) ? value.join('\n') : String(value || '')
export const brandFields = [
  { key:'website', label:'官方网站', required:true },
  { key:'name', label:'品牌名称', required:true },
  { key:'industry', label:'所属行业', required:true },
  { key:'brand_terms', label:'品牌词根', list:true },
  { key:'business_desc', label:'业务定位与品牌介绍', multiline:true },
  { key:'core_products', label:'核心产品与服务', required:true, list:true },
  { key:'proof_points', label:'可信信息与证明', list:true },
]
export function brandDraft(profile = {}) {
  return Object.fromEntries(brandFields.map(f => [f.key, f.list ? joinLines(profile[f.key]) : String(profile[f.key] || '')]))
}
export function missingBrandFields(draft) {
  return brandFields.filter(f => f.required && (f.list ? !splitLines(draft[f.key]).length : !String(draft[f.key] || '').trim()))
}
// Unedited secondary fields belong to the saved profile, not a fresh extraction.
export function mergeBrandProfile(existing, draft, edited = new Set()) {
  const result = { ...existing }
  for (const f of brandFields) {
    const value = f.list ? splitLines(draft[f.key]) : String(draft[f.key] || '').trim()
    if (f.required || edited.has(f.key) || !(Array.isArray(existing[f.key]) ? existing[f.key].length : existing[f.key])) result[f.key] = value
  }
  result.competitors = existing.competitors || []
  return result
}
