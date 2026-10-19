// Keep this explicit list aligned with security/advisor_write_routes.py.
const stringFields = ['product_name', 'website', 'summary', 'industry', 'audience', 'cta']
const listFields = ['honors', 'qualifications', 'capabilities', 'scenarios',
  'competitors', 'recommend_reasons', 'banned_claims']

export const brandProfileLabels = {
  product_name: '品牌名称', website: '官网地址', summary: '品牌简介', industry: '所属行业',
  honors: '品牌口号', qualifications: '资质证书', capabilities: '产品能力', audience: '目标受众',
  scenarios: '使用场景', geo_scope: '服务区域', competitors: '竞争对手',
  recommend_reasons: '推荐理由', banned_claims: '禁用说法', cta: '行动引导',
}
export const brandTextMax = 500
const count = (value) => Array.from(value).length
const splitItems = (value) => value.split(/[,，；\n]/).map((item) => item.trim()).filter(Boolean)

// This page edits six brand fields and the separate competitor section.
// Hidden legacy fields must neither block saving nor overwrite stored values.
export function brandProfilePatch(profile = {}) {
  return Object.fromEntries(['product_name', 'website', 'industry', 'summary',
    'honors', 'qualifications', 'competitors']
    .filter((key) => Object.hasOwn(profile, key)).map((key) => [key, profile[key]]))
}

// Validate the unmodified form, before splitting lists or sending a request.
export function brandProfileError(profile = {}) {
  for (const [key, value] of Object.entries(profile)) {
    const label = brandProfileLabels[key]
    if (!label) continue
    if (listFields.includes(key)) {
      if (typeof value === 'string' && count(value) > 10019) return `${label} 最多 10019 字，现在 ${count(value)} 字`
      const items = typeof value === 'string' ? splitItems(value) : value
      if (!Array.isArray(items) || items.some((item) => typeof item !== 'string')) return `${label} 请填写文字或文字列表`
      if (items.length > 20) return `${label} 最多 20 条，现在 ${items.length} 条`
      const long = items.find((item) => count(item) > brandTextMax)
      if (long) return `${label}每条最多 ${brandTextMax} 字，现在 ${count(long)} 字`
    } else {
      if (typeof value !== 'string') return `${label} 必须是文字`
      if (count(value) > brandTextMax) return `${label} 最多 ${brandTextMax} 字，现在 ${count(value)} 字`
      if (key === 'website' && value.trim()) {
        const site = value.trim()
        try {
          const url = new URL(site)
          if (!/^https?:\/\//i.test(site) || !url.hostname || url.username || url.password || /[\s\x00-\x1f\x7f\\]/u.test(site)) throw new Error()
        } catch {
          return '官网地址要以 http:// 或 https:// 开头，请填写完整网址，不能含账号信息'
        }
      }
    }
  }
  return ''
}

export function advisorBrandProfile(profile = {}) {
  const out = {}
  for (const key of [...stringFields, ...listFields]) {
    if (!Object.hasOwn(profile, key)) continue
    const value = profile[key]
    // The form joins existing lists with Chinese commas. Send actual lists so
    // repeated saves preserve item boundaries and backend length checks apply.
    out[key] = listFields.includes(key) && typeof value === 'string'
      ? splitItems(value)
      : value
  }
  return out
}
