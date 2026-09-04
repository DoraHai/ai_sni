const pendingWritebacks = new Map()

export function createWritebackIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()

  const entropy = Array.from(
    { length: 4 },
    () => Math.random().toString(36).slice(2).padEnd(10, '0'),
  ).join('')
  return `sem-${Date.now().toString(36)}-${entropy}`
}

export function runIdempotentWriteback(operationKey, request, idempotencyKey = null) {
  const pending = pendingWritebacks.get(operationKey)
  if (pending) return pending

  const key = idempotencyKey || createWritebackIdempotencyKey()
  const promise = Promise.resolve()
    .then(() => request(key))
    .finally(() => {
      if (pendingWritebacks.get(operationKey) === promise) {
        pendingWritebacks.delete(operationKey)
      }
    })
  pendingWritebacks.set(operationKey, promise)
  return promise
}
