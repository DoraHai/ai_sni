/** Normalize competitor display names for fuzzy alias clustering. */
export function normalizeCompetitorKey(name) {
  return String(name || '')
    .trim()
    .toLowerCase()
    .replace(/[\s\-_./·•]+/g, '')
    .replace(/[（）()【】\[\]「」]/g, '')
    .replace(/(公司|集团|有限|股份|inc|ltd|co)$/g, '')
}

/**
 * Find clusters of items that share a normalized key (size >= 2).
 * @returns {{ key: string, names: string[], items: object[] }[]}
 */
export function findAliasClusters(items) {
  const map = new Map()
  for (const row of items || []) {
    const name = row?.name
    if (!name) continue
    const key = normalizeCompetitorKey(name)
    if (!key) continue
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(row)
  }
  const clusters = []
  for (const [key, rows] of map.entries()) {
    const names = [...new Set(rows.map((r) => r.name))]
    if (names.length < 2) continue
    clusters.push({ key, names, items: rows })
  }
  clusters.sort((a, b) => b.items.length - a.items.length)
  return clusters
}

/**
 * Apply alias map { aliasName: canonicalName } and merge stats into canonical rows.
 */
export function applyAliasMap(items, aliasMap) {
  const map = aliasMap || {}
  const buckets = new Map()

  for (const row of items || []) {
    const raw = row.name
    const canonical = map[raw] || raw
    const prev = buckets.get(canonical)
    if (!prev) {
      buckets.set(canonical, {
        ...row,
        name: canonical,
        aliases: raw !== canonical ? [raw] : [],
        _merged: raw !== canonical,
        platform_keys: [...(row.platform_keys || [])],
        engines: [...(row.engines || [])],
      })
      continue
    }
    prev.mention_count = (prev.mention_count || 0) + (row.mention_count || 0)
    prev.prompt_count = (prev.prompt_count || 0) + (row.prompt_count || 0)
    prev.source_count = (prev.source_count || 0) + (row.source_count || 0)
    const eng = new Set([...(prev.engines || []), ...(row.engines || [])])
    prev.engines = [...eng]
    const pks = new Set([...(prev.platform_keys || []), ...(row.platform_keys || [])])
    prev.platform_keys = [...pks]
    prev.platform_count = prev.platform_keys.length
    if (raw !== canonical && !prev.aliases.includes(raw)) prev.aliases.push(raw)
    if (
      row.latest_captured_at &&
      (!prev.latest_captured_at || row.latest_captured_at > prev.latest_captured_at)
    ) {
      prev.latest_captured_at = row.latest_captured_at
      prev.sample_prompt_question = row.sample_prompt_question
    }
    prev._merged = true
  }

  return [...buckets.values()].sort(
    (a, b) => (b.mention_count || 0) - (a.mention_count || 0) || a.name.localeCompare(b.name),
  )
}

export function aliasStorageKey(tenantId) {
  return `geo_competitor_alias_map_v1_${tenantId || 0}`
}

export function loadAliasMap(tenantId) {
  try {
    return JSON.parse(localStorage.getItem(aliasStorageKey(tenantId)) || '{}')
  } catch {
    return {}
  }
}

export function saveAliasMap(tenantId, map) {
  localStorage.setItem(aliasStorageKey(tenantId), JSON.stringify(map || {}))
}
