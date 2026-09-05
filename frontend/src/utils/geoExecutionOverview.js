export function executionNext(task, detail, error = '') {
  const status = detail?.status || task.status
  if (status === 'done') return { stage: '已完成', next: '查看指标变化证据' }
  if (status === 'cancelled') return { stage: '已取消', next: '查看历史记录' }
  if (error || !detail) return { stage: '条件未知', next: error || '尚未读取执行条件' }
  if (typeof detail.baseline_valid !== 'boolean') return { stage: '条件未知', next: '执行条件缺少有效的基线状态，请刷新重试' }
  if (!detail.baseline_valid) return { stage: '缺少有效基线', next: detail.baseline_blocker || '采集已结束自然周的真实样本基线' }
  if (task.params?.content_task_id && !detail.publication_evidence) {
    return detail.publication_candidates?.length
      ? { stage: '发布待核实', next: '已有发布记录，重新抓取当前稿件验证是否上线' }
      : { stage: '缺少发布证据', next: '完成发布并登记当前稿件的真实发布记录' }
  }
  if (['pending', 'running'].includes(detail.latest_retest?.status)) return { stage: '复测执行中', next: '查看采样进度，等待本次执行结束' }
  if (detail.can_retest === true) return { stage: '可启动复测', next: '检查计划后启动同题同模型复测，会调用 AI 引擎' }
  if (detail.latest_retest?.status === 'failed') return { stage: '复测异常', next: detail.latest_retest.error || detail.retest_blocker || '查看失败原因和执行条件' }
  return { stage: '等待后测或验收', next: detail.retest_blocker || '查看完整周结果，再由服务端核验指标变化；采样结束不代表达标' }
}

// Three read-only requests at a time; stop scheduling when customer/page changes.
export function createOverviewLoader(state, api) {
  let epoch = 0, active = 0
  const waiting = []
  const acquire = token => new Promise(resolve => {
    const attempt = () => {
      if (token !== epoch) { resolve(false); return }
      if (active < 3) { active++; resolve(true) }
      else waiting.push(attempt)
    }
    attempt()
  })
  const release = () => {
    active--
    while (active < 3 && waiting.length) waiting.shift()()
  }
  const invalidate = () => { epoch++ }
  async function load(tenant, tasks) {
    const token = ++epoch
    state.rows = tasks.map(task => ({ task, detail: null, error: '' }))
    state.loading = !!tenant && tasks.length > 0
    if (!tenant) { state.rows = []; return }
    let cursor = 0
    const worker = async () => {
      while (token === epoch && cursor < tasks.length) {
        const index = cursor++, task = tasks[index]
        if (['done', 'cancelled'].includes(task.status)) continue
        if (!await acquire(token)) return
        try {
          if (token !== epoch) continue
          const detail = await api.readiness(tenant, task.id)
          if (token === epoch) state.rows[index] = { task, detail, error: '' }
        } catch (e) {
          if (token === epoch) state.rows[index] = { task, detail: null, error: e.message || '读取失败，请刷新重试' }
        } finally { release() }
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, tasks.length) }, worker))
    if (token === epoch) state.loading = false
  }
  return { load, invalidate }
}
