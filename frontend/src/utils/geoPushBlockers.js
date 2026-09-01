export function pushBlockLabels(row) {
  const labels = []
  for (const reason of row?.blockReasons || []) {
    const text = String(reason || '')
    if (text.includes('发布模式不是')) labels.push('未开启自动发布')
    else if (text.includes('无渠道稿')) labels.push('未生成渠道稿')
    else if (text.includes('渠道稿未导出') || text.includes('渠道稿还是空')) labels.push('渠道稿未就绪')
    else if (text.includes('缺少 webhook') || text.includes('缺少社交账号') || text.includes('无兼容推送账号')) labels.push('未配置发布账号')
  }
  return [...new Set(labels.length ? labels : ['该渠道仅支持手动发布'])]
}
