export const credentialFields = {
  webhook: [['webhook_url', 'Webhook 地址', true], ['secret', '签名密钥', false, true], ['headers', '请求头 JSON（可选）']],
  gateway: [['api_url', '发布接口地址', true], ['access_token', 'Access Token', true, true]],
  wechat_mp: [['app_id', 'App ID', true], ['app_secret', 'App Secret', true, true]],
  oauth2: [['client_id', 'Client ID', true], ['client_secret', 'Client Secret', true, true], ['authorize_url', '授权地址', true], ['token_url', '令牌地址', true], ['redirect_uri', '回调地址', true], ['api_url', '发布接口地址', true], ['scope', 'Scope（可选）']],
}

export function credentialKind(form) {
  if (form.auth_type === 'manual') return 'manual'
  if (form.auth_type === 'webhook') return 'webhook'
  if (form.auth_type === 'oauth2') return 'oauth2'
  return form.provider || 'gateway'
}

export function buildAccountCredentials(form, platform) {
  if (form.id && !form.replace_credentials) {
    if (form.auth_type !== form.original_auth_type) throw new Error('更改授权方式时请重新填写完整凭据')
    return undefined
  }
  const kind = credentialKind(form)
  if (kind === 'manual') return undefined
  if (!credentialFields[kind]) throw new Error('不支持的接入方式')
  const social = ['wechat', 'zhihu', 'baijiahao', 'toutiao']
  if (kind !== 'webhook' && !social.includes(platform)) throw new Error('此平台请使用 Webhook 或人工回填')
  if (kind === 'wechat_mp' && platform !== 'wechat') throw new Error('微信公众号原生接口只适用于微信平台')
  const values = form.credential_values || {}
  const result = kind === 'webhook' ? { method: 'POST' } : { provider: kind, platform, mode_default: 'draft' }
  for (const [key, label, required] of credentialFields[kind]) {
    const value = String(values[key] || '').trim()
    if (!value) {
      if (required) throw new Error(`请填写${label}`)
      continue
    }
    if (key.endsWith('_url') || key === 'redirect_uri') {
      let url
      try { url = new URL(value) } catch { throw new Error(`${label}须为有效的 HTTPS 地址`) }
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error(`${label}须为不含账号密码的 HTTPS 地址`)
    }
    if (key === 'headers') {
      let headers
      try { headers = JSON.parse(value) } catch { throw new Error('请求头须为 JSON 对象') }
      if (!headers || Array.isArray(headers) || typeof headers !== 'object' || Object.values(headers).some(v => typeof v !== 'string')) throw new Error('请求头须为字符串键值对象')
      result.headers = headers
    } else result[key] = value
  }
  return result
}

export function credentialCheckMessage(result) {
  if (result?.ok !== true) throw new Error('凭据检查未通过')
  return result.check_scope === 'authorization' ? '授权验证通过，尚未执行发布' : '凭据配置检查通过；尚未验证远端发布连接'
}
