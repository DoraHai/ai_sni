export function validWebsite(value) {
  const input = String(value || '').trim()
  if (!input || input.startsWith('//') || input.length > 2048 || /[\s\\]/.test(input)) throw new Error('请输入有效的公司官网地址，例如 https://example.com')
  const url = new URL(/^[a-z][a-z\d+.-]*:/i.test(input) ? input : `https://${input}`)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !url.hostname.includes('.') || /^(localhost|127\.|0\.|169\.254\.|10\.|192\.168\.)/.test(url.hostname)) throw new Error('请使用可公开访问的 HTTP 或 HTTPS 官网地址')
  url.hash = ''
  return url.href
}
export function initialWebsite(search) {
  const params = new URLSearchParams(search)
  const raw = params.get('website') || params.get('url') || ''
  if (!raw) return { website:'', error:'' }
  try { return { website:validWebsite(raw), error:'' } }
  catch { return { website:'', error:'传入的官网地址无效，请重新输入。' } }
}
export function diagnosisDestination(website) {
  return `/diagnostic-center/?${new URLSearchParams({ website:validWebsite(website) })}`
}
