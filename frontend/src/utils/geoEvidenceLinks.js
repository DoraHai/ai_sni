export function evidenceTaskLink(tenant, taskId) {
  return { path: '/geo/tickets', query: { evidence_task_id: String(taskId), evidence_tenant_id: String(tenant) } }
}
export function evidenceLinkTarget(query, tenant) {
  if (query.evidence_task_id == null) return { id: null, error: '' }
  const raw = query.evidence_task_id
  if (typeof raw !== 'string' || !/^[1-9][0-9]*$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
    return { id: null, error: '链接中的验收任务编号无效' }
  }
  if (typeof query.evidence_tenant_id !== 'string' || query.evidence_tenant_id !== String(tenant)) {
    return { id: null, error: '此任务链接属于其他客户，请先选择对应客户再查看' }
  }
  return { id: Number(raw), error: '' }
}
