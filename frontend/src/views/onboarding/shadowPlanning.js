export const SHADOW_NOTICE = '影子模式，不会改动百度投放'
export const LAST_GRANT_NOTICE = '禁止撤掉最后一条有效授权；必须保留至少一名可写顾问。'
export const IMAGE_LIMITS = { count: 10, single: 10 * 1024 ** 2, total: 30 * 1024 ** 2 }

export function validateScreenshots(files) {
  if (files.length > IMAGE_LIMITS.count) throw new Error('最多上传 10 张截图')
  if (files.some(f => !['image/png', 'image/jpeg', 'image/webp'].includes(f.type)
    || f.size <= 0 || f.size > IMAGE_LIMITS.single)) throw new Error('仅接受非空 PNG/JPEG/WebP，单张不超过 10MiB')
  if (files.reduce((sum, f) => sum + f.size, 0) > IMAGE_LIMITS.total) throw new Error('截图合计不得超过 30MiB')
  return files
}

export function shadowError(error) {
  if (error.code === 'LAST_GRANT_PROTECTED' || error.code === 'LAST_WRITABLE_ADVISOR_PROTECTED') return LAST_GRANT_NOTICE
  if (error.code === 'GRANT_ACCOUNT_NOT_INITIALIZED') return '账户尚未初始化授权，请按另行批准的首次授权流程处理。'
  if (error.status === 401 || error.code === 'AUTH_EXPIRED') return '登录已过期，请重新登录并选择客户。'
  if (error.status === 403) return '没有当前客户或账户的访问权限，或授权、角色、模块已失效。'
  if (error.status === 503) return error.code === 'ATTACHMENT_STORAGE_UNAVAILABLE'
    ? '截图附件存储尚未装配或暂不可用，提交未成功。可保留文字并稍后重试。'
    : '来源或授权服务暂不可用，操作未确认成功，请刷新核对。'
  if (error.status === 409) return '来源或规划版本已失效，请刷新核对最新版本。'
  if (error.status === 422) return '资料不满足契约，请检查必填项、product:/benefit:/keywords: 内容及日期、预算边界。'
  return error.status ? '请求未成功，请稍后重试。' : (error.message || '网络异常，请稍后重试。')
}

export async function changeAndReloadGrants(change, reload, current) {
  const result = await change()
  if (!current()) return null
  try { return { result, rows: await reload(), refreshFailed: false } }
  catch { return { result, rows: null, refreshFailed: true } }
}

// All requests use the existing signed-in client. No credentials/config here.
export function createShadowApi(client) {
  const root = '/api/v1/sem/phase1a/shadow'
  const grantRoot = '/api/v1/sem/phase1a/account-grants/accounts'
  return {
    list: (tenant, account, offset = 0) => client.get(`${root}/accounts/${account}/plans`, { params: { tenant_id: tenant, offset, limit: 50 } }),
    read: id => client.get(`${root}/plans/${encodeURIComponent(id)}`),
    submit: (payload, files) => {
      validateScreenshots(files)
      const data = new FormData()
      data.append('metadata', JSON.stringify(payload))
      files.forEach(f => data.append('screenshots', f))
      return client.post('/api/v1/sem/phase0/submissions', data)
    },
    create: payload => client.post(`${root}/plans`, payload),
    rule: (id, version, reason) => client.post(`${root}/plans/${encodeURIComponent(id)}/rulings`, { expected_version: version, choices: {}, reason }),
    excel: id => client.get(`${root}/plans/${encodeURIComponent(id)}/excel/advisor`, { responseType: 'blob' }),
    grants: (tenant, account) => client.get(`${grantRoot}/${account}`, { params: { tenant_id: tenant } }),
    grant: (account, body) => client.post(`${grantRoot}/${account}`, body),
    revoke: (account, body) => client.post(`${grantRoot}/${account}/revoke`, body),
  }
}

export function submissionPayload(form, tenant, account) {
  if (!Number.isSafeInteger(tenant) || tenant <= 0 || !Number.isSafeInteger(account) || account <= 0) throw new Error('请先选择客户和推广账户')
  if (!form.account_ready) throw new Error('请明确确认账户已经开好')
  const split = s => s.split('\n').map(v => v.trim()).filter(Boolean)
  const starts = new Date(form.starts_at + '+08:00')
  const ends = form.ends_at ? new Date(form.ends_at + '+08:00') : null
  if (!Number.isFinite(starts.getTime()) || (ends && !Number.isFinite(ends.getTime()))) throw new Error('请填写有效开始和截止时间')
  return {
    tenant_id: tenant, account_id: account, product_line_id: form.product_line_id,
    landing_page_id: form.landing_page_id, expected_revision: Number(form.expected_revision),
    case_type: form.case_type, account_ready: form.account_ready, landing_url: form.landing_url,
    page_content: form.page_content, goal: form.goal, budget_cents: Number(form.budget_cents),
    budget_period: form.budget_period, currency: 'CNY', bid_cap_cents: Number(form.bid_cap_cents),
    regions: split(form.regions), timezone: 'Asia/Shanghai',
    schedule: [{ days: [...form.days], start_hour: Number(form.start_hour), end_hour: Number(form.end_hour) }],
    brand_rules: form.brand_rules, negative_keywords: split(form.negative_keywords),
    starts_at: starts.toISOString(), ends_at: ends?.toISOString() || null,
    no_deadline_explicit: form.no_deadline_explicit, link_source: form.link_source, authorized_scope: form.authorized_scope,
  }
}
