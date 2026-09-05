export function retestDiagnosis(run) {
  if (!run) return null
  if (['pending', 'running'].includes(run.status)) return { label: '复测尚未结束', note: '等待本次采样结束后查看样本匹配结果。', missing: [] }
  const result = run.result
  if (run.status === 'failed') return { label: '复测执行失败', note: run.error || '请查看执行条件和采样记录；不要手工追加样本改变本周权重。', missing: [] }
  if (run.status !== 'completed' || typeof result?.comparable !== 'boolean') return { label: '样本匹配结果未知', note: '缺少服务端匹配结果，请刷新执行条件；不能据此认定达标。', missing: [] }
  if (result.comparable) return { label: '采样矩阵匹配', note: '问题与引擎的有效采样次数匹配；仍需完整周指标及发布证据验收，不代表目标已达成。', missing: [] }
  const missing = Array.isArray(result.missing) ? result.missing.filter(row => Number.isSafeInteger(row.prompt_id) && row.prompt_id > 0 && typeof row.engine === 'string' && row.engine && Number.isSafeInteger(row.count) && row.count > 0) : []
  return { label: '采样矩阵不匹配', note: missing.length ? '以下问题与引擎缺少合格样本。先查看原始记录和失败原因，不要追加采样改变本周权重。' : '有效样本的数量或分布与计划不一致；即使总数相同也不能认为匹配。请查看采样记录。', missing }
}
