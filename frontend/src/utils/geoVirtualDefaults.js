export function isPersistedGeoRow(row) {
  return !!row && row.virtual_default !== true && Number.isInteger(row.id) && row.id > 0
}

export function persistedGeoRows(rows) {
  return (Array.isArray(rows) ? rows : []).filter(isPersistedGeoRow)
}

