export function createWritebackIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()

  const entropy = Array.from(
    { length: 4 },
    () => Math.random().toString(36).slice(2).padEnd(10, '0'),
  ).join('')
  return `sem-${Date.now().toString(36)}-${entropy}`
}
