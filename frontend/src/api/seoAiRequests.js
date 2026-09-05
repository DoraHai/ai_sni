// Keep the same operation ID after an uncertain response. A successful action
// or an explicit terminal rejection permits the next intentional generation.
export function createSeoAiRequester(send, getScope, createId = () => crypto.randomUUID(), options = {}) {
  const pending = new Map()
  let scope
  const storageKey = 'seo_ai_pending_v1'
  function readStored() {
    if (!options.storage) return {}
    try {
      const value = JSON.parse(options.storage().getItem(storageKey) || '{}')
      if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error()
      if (Object.entries(value).some(([key, id]) => !/^[a-f0-9]{64}$/.test(key) || typeof id !== 'string' || !/^[A-Za-z0-9_-]{16,64}$/.test(id))) throw new Error()
      return value
    } catch { throw new Error('无法读取待确认操作，请到自动任务中心取回结果后再试') }
  }
  function store(signature, id) {
    if (!options.storage) return
    const value = readStored()
    if (id) value[signature] = id
    else delete value[signature]
    if (Object.keys(value).length > 64) throw new Error('待确认的 AI 操作过多，请先到自动任务中心取回结果')
    try { options.storage().setItem(storageKey, JSON.stringify(value)) }
    catch { throw new Error('浏览器无法保存请求标识，请检查存储设置后再试') }
  }
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical)
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
    }
    return value
  }
  return async function request(path, payload) {
    const currentScope = getScope()
    if (scope !== currentScope) { pending.clear(); scope = currentScope }
    const rawSignature = JSON.stringify([currentScope, path, canonical(payload)])
    // Persist only a digest and random ID, never the source draft or credentials.
    const signature = options.storage
      ? Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(rawSignature))), byte => byte.toString(16).padStart(2, '0')).join('')
      : rawSignature
    if (getScope() !== currentScope) throw new Error('登录账户已变化，请重新发起操作')
    let entry = pending.get(signature)
    if (!entry) {
      if (pending.size >= 64) throw new Error('待确认的 AI 操作过多，请先重试取回已有结果')
      entry = { id: payload.request_id || readStored()[signature] || createId(), promise: null }
      store(signature, entry.id)
      pending.set(signature, entry)
    }
    if (entry.promise) return entry.promise
    const forget = () => {
      if (readStored()[signature] === entry.id) store(signature, null)
      if (scope === currentScope && pending.get(signature) === entry) pending.delete(signature)
    }
    entry.promise = (async () => {
      const result = await send(path, { ...payload, request_id: entry.id }, {
        timeout: 200000,
        // Preserve structured terminal/in-progress 4xx responses without changing
        // the shared client's error handling for SEM or GEO.
        validateStatus: status => status >= 200 && status < 500,
      })
      if (result?.detail) {
        if (result.detail?.code !== 'operation_running') forget()
        throw new Error(typeof result.detail === 'string' ? result.detail : result.detail.message || 'AI 请求未通过校验')
      }
      if (!result || typeof result !== 'object' || (!result.action && !result.ai_generated)) {
        throw new Error('AI 响应不完整，请重试取回结果')
      }
      forget()
      return result
    })()
    try { return await entry.promise } finally { entry.promise = null }
  }
}
