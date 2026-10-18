// Keep this explicit list aligned with security/advisor_write_routes.py.
const stringFields = ['product_name', 'website', 'summary', 'industry', 'audience', 'cta']
const listFields = ['honors', 'qualifications', 'capabilities', 'scenarios',
  'competitors', 'recommend_reasons', 'banned_claims']

export function advisorBrandProfile(profile = {}) {
  const out = {}
  for (const key of [...stringFields, ...listFields]) {
    if (!Object.hasOwn(profile, key)) continue
    const value = profile[key]
    // The form joins existing lists with Chinese commas. Send actual lists so
    // repeated saves preserve item boundaries and backend length checks apply.
    out[key] = listFields.includes(key) && typeof value === 'string'
      ? value.split(/[,，；\n]/).map((item) => item.trim()).filter(Boolean)
      : value
  }
  return out
}
