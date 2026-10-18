export function safeGeoWebsiteUrl(value) {
  const text = String(value || '').trim()
  if (!text || /[\s\\\u0000-\u001f\u007f]/.test(text)) return ''
  try {
    const url = new URL(text)
    return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password
      ? url.href : ''
  } catch {
    return ''
  }
}
