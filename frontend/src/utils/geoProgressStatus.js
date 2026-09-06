export function staleProgressHint(row, subject = '后台任务') {
  if (!row?.stale || !['pending', 'running'].includes(row?.stored_status || row?.status)) {
    return ''
  }
  return `${subject}疑似超时，等待后台恢复确认`
}
