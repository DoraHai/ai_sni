/** Join live answer snapshots onto prompts using existing snapshot fields. */

/** 可见度加权：首位 1 · 备选 0.6 · 顺带提及 0.3 · 未出现 0 */
export const POSITION_WEIGHT = {
  first: 1,
  alternative: 0.6,
  mentioned: 0.3,
  absent: 0,
  unknown: 0,
}

export function positionWeight(snap) {
  const pos = snap?.brand_position
  if (pos && Object.prototype.hasOwnProperty.call(POSITION_WEIGHT, pos)) {
    return POSITION_WEIGHT[pos]
  }
  return snap?.mentions_brand ? 0.3 : 0
}

/** 0–1 加权可见度得分（与原型「提及 + 顺位」口径一致） */
export function visibilityScore(snaps = []) {
  const rows = Array.isArray(snaps) ? snaps : []
  if (!rows.length) return null
  const sum = rows.reduce((a, s) => a + positionWeight(s), 0)
  return sum / rows.length
}

export function positionRank(pos) {
  if (pos === 'first') return 1
  if (pos === 'alternative') return 2
  if (pos === 'mentioned') return 3
  return null
}

export function avgRecommendRank(snaps = []) {
  const ranks = (snaps || [])
    .map((s) => positionRank(s.brand_position))
    .filter((n) => n != null)
  if (!ranks.length) return null
  return ranks.reduce((a, b) => a + b, 0) / ranks.length
}

export function pctDelta(cur, prev) {
  if (cur == null || prev == null) return null
  const c = Number(cur)
  const p = Number(prev)
  if (!Number.isFinite(c) || !Number.isFinite(p)) return null
  if (!p) return c ? 100 : 0
  return ((c - p) / Math.abs(p)) * 100
}

export function splitByMidpoint(snaps = [], startIso, endIso) {
  const rows = (snaps || []).filter((s) => s?.captured_at)
  if (rows.length < 2) return { prev: [], cur: [] }
  let mid
  if (startIso && endIso) {
    const a = Date.parse(`${startIso}T00:00:00`)
    const b = Date.parse(`${endIso}T23:59:59`)
    mid = Number.isFinite(a) && Number.isFinite(b) ? a + (b - a) / 2 : null
  }
  if (mid == null) {
    const times = rows
      .map((s) => Date.parse(s.captured_at))
      .filter((n) => Number.isFinite(n))
      .sort((x, y) => x - y)
    mid = times[Math.floor(times.length / 2)]
  }
  const prev = []
  const cur = []
  for (const s of rows) {
    const t = Date.parse(s.captured_at)
    if (!Number.isFinite(t) || t < mid) prev.push(s)
    else cur.push(s)
  }
  return { prev, cur }
}

export function shareOfVoiceRows(snaps = [], brandLabel = '本品牌') {
  let own = 0
  const comps = {}
  for (const s of snaps || []) {
    if (s.mentions_brand) own += 1
    for (const c of s.competitors || []) {
      const name = String(c || '').trim()
      if (!name) continue
      comps[name] = (comps[name] || 0) + 1
    }
  }
  const top = Object.entries(comps).sort((a, b) => b[1] - a[1])
  const total = own + top.reduce((a, [, n]) => a + n, 0)
  if (!total) return []
  const rows = [{ name: brandLabel, count: own, value: (own / total) * 100, bar: 'own' }]
  let used = own
  for (const [name, count] of top.slice(0, 2)) {
    rows.push({ name, count, value: (count / total) * 100, bar: 'amber' })
    used += count
  }
  const other = total - used
  if (other > 0 || top.length > 2) {
    rows.push({ name: '其他', count: other, value: (other / total) * 100, bar: 'red' })
  }
  return rows.map((r) => ({ ...r, width: r.value }))
}

/** 在已提及样本内：首选 / 备选 / 顺带，合计 100% */
export function mentionManner(snaps = []) {
  const rows = (snaps || []).filter(
    (s) =>
      s.mentions_brand ||
      s.brand_position === 'first' ||
      s.brand_position === 'alternative' ||
      s.brand_position === 'mentioned',
  )
  const n = rows.length
  if (!n) return { n: 0, first: 0, alternative: 0, mentioned: 0 }
  const first = rows.filter((s) => s.brand_position === 'first').length
  const alternative = rows.filter((s) => s.brand_position === 'alternative').length
  return {
    n,
    first: first / n,
    alternative: alternative / n,
    mentioned: (n - first - alternative) / n,
  }
}

export function sentimentShare(snaps = []) {
  const rows = (snaps || []).filter((s) =>
    ['positive', 'neutral', 'negative'].includes(s.sentiment),
  )
  const n = rows.length
  if (!n) return { n: 0, positive: null, neutral: null, negative: null }
  const count = (k) => rows.filter((s) => s.sentiment === k).length
  return {
    n,
    positive: count('positive') / n,
    neutral: count('neutral') / n,
    negative: count('negative') / n,
  }
}

export function highlightParts(text, names = []) {
  const src = String(text || '')
  const list = [...new Set((names || []).map((n) => String(n || '').trim()).filter((n) => n.length >= 2))]
    .sort((a, b) => b.length - a.length)
  if (!src || !list.length) return [{ text: src, hit: false }]
  const escaped = list.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = []
  let last = 0
  for (const m of src.matchAll(re)) {
    const idx = m.index || 0
    if (idx > last) parts.push({ text: src.slice(last, idx), hit: false })
    parts.push({ text: m[0], hit: true })
    last = idx + m[0].length
  }
  if (last < src.length) parts.push({ text: src.slice(last), hit: false })
  return parts.length ? parts : [{ text: src, hit: false }]
}

export function summarizeSnapshots(snaps = []) {
  const rows = Array.isArray(snaps) ? snaps : []
  const n = rows.length
  const mentioned = rows.filter((s) => s.mentions_brand).length
  const first = rows.filter((s) => s.brand_position === 'first').length
  const comps = {}
  for (const s of rows) {
    for (const c of s.competitors || []) {
      const name = String(c || '').trim()
      if (!name) continue
      comps[name] = (comps[name] || 0) + 1
    }
  }
  const topComp = Object.entries(comps).sort((a, b) => b[1] - a[1])[0]
  const latest = [...rows].sort((a, b) => String(b.captured_at || '').localeCompare(String(a.captured_at || '')))[0]
  let position = 'unknown'
  if (!n) position = 'unknown'
  else if (first) position = 'first'
  else if (mentioned) position = 'mentioned'
  else position = 'absent'
  return {
    n,
    mentionRate: n ? mentioned / n : null,
    firstRate: n ? first / n : null,
    visScore: visibilityScore(rows),
    position,
    topCompetitor: topComp?.[0] || null,
    topCompetitorCount: topComp?.[1] || 0,
    latestText: latest?.raw_text || '',
    latestEngine: latest?.engine || '',
    latestAt: latest?.captured_at || '',
  }
}

export function groupSnapshotsByPrompt(snaps = []) {
  const map = new Map()
  for (const s of snaps) {
    const id = s.prompt_id
    if (!id) continue
    if (!map.has(id)) map.set(id, [])
    map.get(id).push(s)
  }
  const out = new Map()
  for (const [id, rows] of map) out.set(id, summarizeSnapshots(rows))
  return out
}

export function groupSnapshotsByEngine(snaps = []) {
  const map = new Map()
  for (const s of snaps) {
    const key = s.engine || 'other'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(s)
  }
  return [...map.entries()].map(([engine, rows]) => {
    const sum = summarizeSnapshots(rows)
    return { engine, ...sum }
  }).sort((a, b) => (b.visScore || b.mentionRate || 0) - (a.visScore || a.mentionRate || 0))
}

export const ENGINE_DOT = {
  deepseek: '#4d6bfe',
  doubao: '#ff6a00',
  kimi: '#111827',
  qwen: '#615ced',
  tongyi: '#615ced',
  yuanbao: '#0ea5e9',
  hunyuan: '#0ea5e9',
  chatgpt: '#10a37f',
  claude: '#d97706',
  gemini: '#4285f4',
  wenxin: '#2932E1',
}

export function engineColor(key) {
  const k = String(key || '').toLowerCase()
  for (const [id, c] of Object.entries(ENGINE_DOT)) {
    if (k.includes(id)) return c
  }
  return '#7c3aed'
}

export function heatTone(rate) {
  const n = Number(rate) || 0
  if (n >= 0.55) return { bg: '#7c3aed', fg: '#fff' }
  if (n >= 0.4) return { bg: '#9a6ef0', fg: '#fff' }
  if (n >= 0.28) return { bg: '#a78bfa', fg: '#fff' }
  if (n >= 0.18) return { bg: '#c4b5fd', fg: '#1e2330' }
  if (n >= 0.08) return { bg: '#ddd6fe', fg: '#1e2330' }
  return { bg: '#f5f3ff', fg: '#6b7280' }
}

export function mentionHeatFromSnapshots(snaps = [], brandLabel = '本品牌') {
  const engines = []
  const seenE = new Set()
  const totals = {}
  const hits = { [brandLabel]: {} }
  for (const s of snaps || []) {
    const e = s.engine || 'other'
    if (!seenE.has(e)) {
      seenE.add(e)
      engines.push(e)
    }
    totals[e] = (totals[e] || 0) + 1
    if (s.mentions_brand) hits[brandLabel][e] = (hits[brandLabel][e] || 0) + 1
    for (const c of s.competitors || []) {
      const name = String(c || '').trim()
      if (!name) continue
      if (!hits[name]) hits[name] = {}
      hits[name][e] = (hits[name][e] || 0) + 1
    }
  }
  const others = Object.keys(hits)
    .filter((n) => n !== brandLabel)
    .sort((a, b) => {
      const sa = Object.values(hits[a]).reduce((x, y) => x + y, 0)
      const sb = Object.values(hits[b]).reduce((x, y) => x + y, 0)
      return sb - sa
    })
    .slice(0, 5)
  return {
    engines,
    rows: [brandLabel, ...others].map((name) => ({
      name,
      own: name === brandLabel,
      cells: engines.map((e) => {
        const n = totals[e] || 0
        return n ? (hits[name]?.[e] || 0) / n : 0
      }),
    })),
  }
}

export function citationHeatFromItems(items = []) {
  const engines = []
  const seenE = new Set()
  const buckets = new Map()
  for (const it of items || []) {
    const name = it.blueprint_channel_name || it.domain || '其他'
    if (!buckets.has(name)) buckets.set(name, { name, total: 0, byEng: {} })
    const b = buckets.get(name)
    const n = Number(it.cite_count || 0)
    b.total += n
    const list = it.engines || []
    const share = list.length ? n / list.length : n
    for (const e of list) {
      if (!seenE.has(e)) {
        seenE.add(e)
        engines.push(e)
      }
      b.byEng[e] = (b.byEng[e] || 0) + share
    }
  }
  const rows = [...buckets.values()].sort((a, b) => b.total - a.total).slice(0, 6)
  const grand = rows.reduce((a, r) => a + r.total, 0) || 1
  return {
    engines,
    rows: rows.map((r) => ({
      name: r.name,
      cells: engines.map((e) => (r.byEng[e] || 0) / grand),
    })),
  }
}

export function starsFromPriority(priority) {
  const p = Number(priority) || 0
  if (p >= 80) return '★★★★★'
  if (p >= 50) return '★★★★'
  if (p >= 20) return '★★★'
  if (p >= 10) return '★★'
  return '★'
}
