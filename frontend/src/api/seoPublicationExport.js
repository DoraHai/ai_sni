export function previousBeijingMonth(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).formatToParts(now)
  const year = Number(parts.find(part => part.type === 'year').value)
  const month = Number(parts.find(part => part.type === 'month').value)
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, '0')}`
}

export function publicationListFilename(disposition, fallback) {
  const encoded = disposition?.match(/(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded.trim()) } catch { /* use fallback */ }
  }
  const plain = disposition?.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;]+))/i)
  return plain ? (plain[1] || plain[2]).trim() : fallback
}
