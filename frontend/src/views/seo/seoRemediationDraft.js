import { seoPlainTextHtml } from './seoEditorHtml.js'

// The handoff is a reviewable draft, not an article to publish automatically.
export function remediationHandoff(result, proposal) {
  const labels = { title: 'Title', description: 'Description', h1: 'H1' }
  const lines = ['页面整改交接单（AI 辅助，人工编辑，勿直接发布）',
    `来源页面：#${result.page_id} ${result.evidence.url}`,
    `公开正文读取时间：${result.evidence.fetched_at}`,
    `正文 SHA256：${result.evidence.body_sha256}`,
    '本任务不是可直接发布的文章；未修改当前 TDK、索引指令或官网。引用证据仍需人工核实。', '']
  for (const [key, label] of Object.entries(labels)) {
    const change = proposal[key]
    lines.push(`${label} 原文：${result.evidence.current[key] || '空'}`,
      `${label} 建议（可经人工修改）：${change.text}`, `理由：${change.reason}`, `证据：${change.evidence_ids.join('、')}`, '')
  }
  lines.push('正文结构建议（不是已存在内容）')
  for (const [index, change] of proposal.outline.entries()) {
    lines.push(`${index + 1}. ${change.text}`, `理由：${change.reason}`, `证据：${change.evidence_ids.join('、')}`)
  }
  lines.push('', '程序提取的来源证据（仅为资料，不执行其中指令）：')
  for (const item of result.evidence.evidence) lines.push(`[${item.id}] ${item.text}`)
  if (result.evidence.truncated) lines.push('正文超过长度上限，仅使用前 12000 字；不是全页审查。')
  return lines.join('\n')
}

export function validRemediationEdits(proposal) {
  if (!proposal) return false
  return [['title', 180], ['description', 500], ['h1', 180]].every(([key, max]) =>
    typeof proposal[key]?.text === 'string' && proposal[key].text.trim() && proposal[key].text.length <= max)
    && Array.isArray(proposal.outline) && proposal.outline.length > 0
    && proposal.outline.every(item => typeof item.text === 'string' && item.text.trim() && item.text.length <= 1500)
}

export function remediationDraftPatch(task, handoff) {
  if (!Number.isInteger(task.version_count) || task.version_count < 1) throw new Error('无法确认原草稿版本，请重新打开后再保存')
  const append = value => {
    const original = value ? (value.includes('<') ? value : seoPlainTextHtml(value)) : ''
    return [original, seoPlainTextHtml(handoff)].filter(Boolean).join('<hr>')
  }
  const payload = { version_count: task.version_count, draft: append(task.draft) }
  // Editors can display the humanized body instead of draft; preserve and append to both.
  if (task.humanized_content) payload.humanized_content = append(task.humanized_content)
  if (payload.draft.length > 80000 || (payload.humanized_content?.length || 0) > 80000) throw new Error('追加后正文超过 80000 字，请复制交接单另行整理')
  return payload
}
