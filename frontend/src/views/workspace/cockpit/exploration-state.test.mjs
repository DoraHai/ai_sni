import { describe, expect, it } from 'vitest'
import { appendExplorationPath, compareMetricScope, moveExplorationPath, saveMetricScope } from './exploration-state.mjs'

const path = (metricId, moduleCode = 'sem') => ({ metricId, moduleCode, dateStart: '2026-09-01', dateEnd: '2026-09-07' })

describe('cockpit exploration state', () => {
  it('records paths, removes forward history and skips duplicates', () => {
    let state = appendExplorationPath([], -1, path('cost'))
    state = appendExplorationPath(state.history, state.index, path('click'))
    state = appendExplorationPath(state.history, 0, path('ctr'))
    expect(state.history.map(item => item.metricId)).toEqual(['cost', 'ctr'])
    expect(appendExplorationPath(state.history, state.index, path('ctr'))).toEqual(state)
    expect(moveExplorationPath(state.history, state.index, -1).path.metricId).toBe('cost')
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

  it('preserves a separately rendered unit in the compared values and delta', () => {
    const saved = saveMetricScope({ id: 'mention-rate', label: '提及率', display: '12.5', unit: '%', state: 'available' }, { tenantId: 16 })
    expect(compareMetricScope({ id: 'mention-rate', display: '15', unit: '%', state: 'available' }, saved, { tenantId: 16 })).toMatchObject({ status: 'ready', currentDisplay: '15%', savedDisplay: '12.5%', deltaDisplay: '+2.5%' })
    expect(compareMetricScope({ id: 'mention-rate', display: '15', unit: '次', state: 'available' }, saved, { tenantId: 16 }).status).toBe('incomparable')
  })
})
