// Spreadsheet programs must treat sampled questions and answers as text.
export function opportunityExportRows(items) {
  const textCell = (value) => {
    const text = String(value ?? '')
    return /^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text) ? `'${text}` : text
  }
  return items.flatMap((item) => item.evidence.map((evidence) => [
    item.question, item.priority, item.reason, item.next_action,
    evidence.snapshot_id, evidence.engine, evidence.captured_at,
    evidence.mentions_brand ? '是' : '否', evidence.urls.join(' | '),
  ].map(textCell)))
}
