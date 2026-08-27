/** GEO route helpers — dashboard vs collect/judge (former snapshots + patrol + evaluation) */

export const GEO_VISIBILITY_DASH = '/geo/visibility'
export const GEO_VISIBILITY_SNAPSHOTS = '/geo/visibility/snapshots'
/** Merged collect/judge surface (alias of snapshots). */
export const GEO_VISIBILITY_COLLECT = GEO_VISIBILITY_SNAPSHOTS
/** @deprecated redirects to snapshots */
export const GEO_VISIBILITY_EVALUATION = '/geo/visibility/evaluation'
/** @deprecated redirects to snapshots */
export const GEO_VISIBILITY_PATROL = '/geo/visibility/patrol'

/** Build collect/judge route with optional query (prompt_id, patrol_run_id, etc.) */
export function geoSnapshotLink(query = {}) {
  const q = {}
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== '') q[k] = String(v)
  }
  return { path: GEO_VISIBILITY_SNAPSHOTS, query: q }
}

/** Dashboard drill-down (KPI overview) — not for registration */
export function geoVisibilityDashLink(query = {}) {
  const q = {}
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== '') q[k] = String(v)
  }
  return { path: GEO_VISIBILITY_DASH, query: q }
}
