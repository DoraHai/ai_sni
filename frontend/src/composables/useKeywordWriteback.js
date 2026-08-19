import { ElMessage, ElMessageBox } from 'element-plus'

import { matchTypeWriteback, pauseKeywordBatch, writebackKeyword } from '../api/keywords'

export const MATCH_TYPE_OPTIONS = {
  exact: { matchType: 1, phraseType: 1, label: '精确匹配' },
  phrase: { matchType: 2, phraseType: 1, label: '短语匹配' },
  smart: { matchType: 2, phraseType: 3, label: '智能匹配' },
}

/** Reusable keyword writeback controls for the workbench and detail view. */
export function useKeywordWriteback({ tenantId, onSuccess } = {}) {
  async function notifySuccess(result) {
    if (result?.success) await onSuccess?.(result.response)
    return result
  }

  async function applyWriteback(keywordId, price, keywordText, currentPrice) {
    if (price == null || !(Number(price) > 0)) {
      ElMessage.warning('请先填写有效的最终执行价')
      return null
    }

    try {
      await ElMessageBox.confirm(
        `将把「${keywordText || `关键词 #${keywordId}`}」出价回写为 ¥${Number(price).toFixed(2)}${currentPrice == null ? '' : `（当前 ¥${Number(currentPrice).toFixed(2)}）`}。\n系统受 ±20% 渐进调价硬上限保护，并全程记入回写台账。\n若当前为演练模式，仅记台账、不会真改线上出价。`,
        '回写出价到百度',
        { confirmButtonText: '确认回写', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return null
    }

    try {
      const response = await writebackKeyword({ keywordId, tenantId: tenantId.value, price: Number(price) })
      if (response.dry_run) {
        ElMessage.warning('演练模式：已记入回写台账，未真改线上出价（管理员开启真写后方可生效）')
        return { response, success: false, dryRun: true }
      }
      if (response.writeback?.status === 'failed') {
        ElMessage.error(response.writeback.error_msg || '回写出价失败')
        return { response, success: false }
      }
      ElMessage.success(`已回写百度：¥${Number(price).toFixed(2)}`)
      return await notifySuccess({ response, success: true })
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message)
      return null
    }
  }

  async function changeMatchType(keywordId, keywordText, currentMatchLabel, command) {
    const target = MATCH_TYPE_OPTIONS[command]
    if (!target) return null

    try {
      await ElMessageBox.confirm(
        `确认将「${keywordText}」的匹配模式从「${currentMatchLabel || '—'}」改为「${target.label}」？\n当前为演练模式时，仅记入回写台账、不会真改线上匹配模式。`,
        '确认修改匹配模式',
        { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return null
    }

    try {
      const response = await matchTypeWriteback({
        keywordId,
        tenantId: tenantId.value,
        matchType: target.matchType,
        phraseType: target.phraseType,
      })
      if (response.dry_run) {
        ElMessage.warning('演练模式：已记入台账，未真改线上匹配模式')
        return { response, success: false, dryRun: true }
      }
      if (response.writeback?.status === 'failed') {
        ElMessage.error(response.writeback.error_msg || '修改匹配模式失败')
        return { response, success: false }
      }
      ElMessage.success(`已回写百度：${target.label}`)
      return await notifySuccess({ response, success: true })
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message)
      return null
    }
  }

  async function togglePause(keywordId, keywordText, currentPause) {
    const pause = !currentPause
    const action = pause ? '暂停' : '启用'

    try {
      await ElMessageBox.confirm(
        `将${action}关键词「${keywordText}」。\n受 dry-run 保护，演练模式下不真改线上。`,
        `确认${action}`,
        { confirmButtonText: `确认${action}`, cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return null
    }

    try {
      const response = await pauseKeywordBatch({
        tenantId: tenantId.value,
        keywordIds: [keywordId],
        pause,
      })
      if (response.simulated?.includes(keywordId)) {
        ElMessage.warning(`演练 ${action} 1（未真改线上）`)
        return { response, success: false, dryRun: true }
      }
      if (response.failed?.length) {
        ElMessage.error(response.failed[0]?.reason || `${action}失败`)
        return { response, success: false }
      }
      if (response.applied?.includes(keywordId)) {
        ElMessage.success(`已${action}`)
        return await notifySuccess({ response, success: true })
      }
      ElMessage.error(`${action}未执行`)
      return { response, success: false }
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message)
      return null
    }
  }

  return { applyWriteback, changeMatchType, togglePause }
}
