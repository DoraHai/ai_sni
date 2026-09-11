import { describe, expect, it } from 'vitest'
import { appendExplorationPath, compareMetricScope, moveExplorationPath, saveMetricScope } from './exploration-state.mjs'

const path = (metricId, moduleCode = 'sem', seoSiteId = null) => ({ metricId, moduleCode, seoSiteId, dateStart: '2026-09-01', dateEnd: '2026-09-07' })

describe('cockpit exploration state', () => {
  it('records paths, removes forward history and skips duplicates', () => {
    let state = appendExplorationPath([], -1, path('cost'))
    state = appendExplorationPath(state.history, state.index, path('click'))
    state = appendExplorationPath(state.history, 0, path('ctr'))
    expect(state.history.map(item => item.metricId)).toEqual(['cost', 'ctr'])
    expect(appendExplorationPath(state.history, state.index, path('ctr'))).toEqual(state)
    expect(moveExplorationPath(state.history, state.index, -1).path.metricId).toBe('cost')
  })

  it('keeps SEO site changes as distinct restorable paths', () => {
    let state = appendExplorationPath([], -1, path('seo-pages', 'seo', 21))
    state = appendExplorationPath(state.history, state.index, path('seo-pages', 'seo', 22))
    expect(state.history.map(item => item.seoSiteId)).toEqual([21, 22])
    expect(moveExplorationPath(state.history, state.index, -1).path.seoSiteId).toBe(21)
  })

  it('compares only the same numeric metric in the same tenant', () => {
    const saved = saveMetricScope({ id: 'sem-click', label: '点击', moduleCode: 'sem', display: '1,200', state: 'ready' }, { tenantId: 16, dateStart: '2026-09-01', dateEnd: '2026-09-07' })
    expect(compareMetricScope({ id: 'sem-click', display: '1,250', state: 'ready' }, saved, { tenantId: 16 })).toMatchObject({ status: 'ready', currentDisplay: '1,250', savedDisplay: '1,200', delta: 50, deltaDisplay: '+50' })
    expect(compareMetricScope({ id: 'sem-cost', state: 'ready' }, saved, { tenantId: 16 }).status).toBe('metric_mismatch')
    expect(compareMetricScope({ id: 'sem-click', display: '1,250', state: 'ready' }, saved, { tenantId: 17 }).status).toBe('scope_mismatch')
  })

  it('states why missing and nonnumeric evidence cannot be compared', () => {
    expect(compareMetricScope(null, null, { tenantId: 16 }).status).toBe('missing')
    const saved = saveMetricScope({ id: 'phone', label: '电话', display: '未接入', state: 'unavailable' }, { tenantId: 16 })
    expect(compareMetricScope({ id: 'phone', display: '未接入', state: 'unavailable' }, saved, { tenantId: 16 }).status).toBe('unavailable')
  })

  it('renders percent deltas as percentage points while retaining the numeric delta', () => {
    const saved = saveMetricScope({ id: 'mention-rate', label: '提及率', display: '12.5', unit: '%', state: 'available' }, { tenantId: 16 })
    expect(compareMetricScope({ id: 'mention-rate', display: '15', unit: '%', state: 'available' }, saved, { tenantId: 16 })).toMatchObject({ status: 'ready', currentDisplay: '15%', savedDisplay: '12.5%', delta: 2.5, deltaDisplay: '+2.5 个百分点' })
    const embedded = saveMetricScope({ id: 'ctr', label: '点击率', display: '5%', state: 'ready' }, { tenantId: 16 })
    expect(compareMetricScope({ id: 'ctr', display: '7.5%', state: 'ready' }, embedded, { tenantId: 16 })).toMatchObject({ delta: 2.5, deltaDisplay: '+2.5 个百分点' })
    expect(compareMetricScope({ id: 'mention-rate', display: '15', unit: '次', state: 'available' }, saved, { tenantId: 16 }).status).toBe('incomparable')
  })

  it('requires the same site for SEO but does not constrain non-SEO metrics', () => {
    const seo = saveMetricScope({ id: 'seo-pages', label: '页面', moduleCode: 'seo', display: '10', state: 'available' }, { tenantId: 16, seoSiteId: 21 })
    expect(compareMetricScope({ id: 'seo-pages', moduleCode: 'seo', display: '12', state: 'available' }, seo, { tenantId: 16, seoSiteId: 22 }).status).toBe('site_mismatch')
    const sem = saveMetricScope({ id: 'sem-click', label: '点击', moduleCode: 'sem', display: '10', state: 'ready' }, { tenantId: 16, seoSiteId: 21 })
    expect(compareMetricScope({ id: 'sem-click', moduleCode: 'sem', display: '12', state: 'ready' }, sem, { tenantId: 16, seoSiteId: 22 }).status).toBe('ready')
  })
})
