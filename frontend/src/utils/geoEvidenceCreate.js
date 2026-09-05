const metrics = new Set(['geo.visibility.ai_mention_rate_7d', 'geo.visibility.ai_mention_count_7d', 'geo.visibility.ai_visibility_score'])
export function evidenceRequest(contentId, form) {
  const delta = Number(form.delta)
  if (!Number.isSafeInteger(contentId) || contentId <= 0) throw new Error('请选择有效的关联文章')
  if (!metrics.has(form.metric)) throw new Error('请选择有效的目标指标')
  if (!Number.isFinite(delta) || delta <= 0) throw new Error('提升量必须大于零')
  if (!form.title.trim() || !form.role.trim()) throw new Error('请填写任务标题和负责人角色')
  return { module: 'geo', action_type: 'improve_content', title: form.title.trim(), assignee_role: form.role.trim(),
    params: { content_task_id: contentId, metric_key: form.metric, direction: 'increase', min_delta: delta } }
}
export function createEvidenceSubmitter(state, api, getTenant, getContent) {
  let epoch = 0
  return {
    invalidate() { epoch++ },
    async submit(body) {
      if (state.busy || !getTenant()) return
      const token = ++epoch, tenant = getTenant(), content = getContent()
      if (body.params.content_task_id !== content) return
      const current = () => token === epoch && tenant === getTenant() && content === getContent()
      Object.assign(state, { busy: true, error: '', result: null })
      try {
        const result = await api.create(tenant, body)
        if (current()) state.result = result
      } catch (e) { if (current()) state.error = e.message || '创建失败，请重试' }
      finally { if (current()) state.busy = false }
    },
  }
}
