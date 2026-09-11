import { ElMessage, ElMessageBox } from 'element-plus'

import { matchTypeWriteback, pauseKeywordBatch, writebackKeyword } from '../api/keywords'
import { createWritebackIdempotencyKey } from '../api/idempotency'
import { fetchWritebackMode, WRITEBACK_CONFIRMATION } from '../api/writeback'
import { createLatestRequestGuard } from '../utils/latestRequest'
import { keywordBidPreflight, writebackTrace } from '../utils/writebackPreflight'

export const MATCH_TYPE_OPTIONS = {
  exact: { matchType: 1, phraseType: 1, label: '精确匹配' },
  phrase: { matchType: 2, phraseType: 1, label: '短语匹配' },
  smart: { matchType: 2, phraseType: 3, label: '智能匹配' },
}

/** Reusable keyword writeback controls for the workbench and detail view. */
export function useKeywordWriteback({ tenantId, onSuccess, readContext } = {}) {
  const pendingBidWrites = new Set()
  const actionGuard = createLatestRequestGuard(() => (
    readContext?.() || { tenantId: tenantId.value }
  ))

  async function notifySuccess(result, attempt) {
    if (result?.success && attempt.isCurrent()) await onSuccess?.(result.response)
    return result
  }

  async function applyWriteback(keywordId, price, keywordText, currentPrice, accountId = null) {
    if (price == null || !(Number(price) > 0)) {
      ElMessage.warning('请先填写有效的最终执行价')
      return null
    }

    const attempt = actionGuard.begin()
    const scopedTenantId = attempt.context.tenantId
    const writeKey = `${scopedTenantId}:${accountId ?? ''}:${keywordId}`
    if (pendingBidWrites.has(writeKey)) return null
    pendingBidWrites.add(writeKey)

    let preflight
    try {
      const mode = await fetchWritebackMode(scopedTenantId)
      if (!attempt.isCurrent()) return null
      preflight = keywordBidPreflight(mode, { tenantId: scopedTenantId, accountId })
      if (!preflight.ok) {
        ElMessage.error(preflight.message)
        return null
      }
    } catch (error) {
      if (attempt.isCurrent()) {
        ElMessage.error(error.response?.data?.detail || '无法完成关键词调价预检，已禁止提交，请刷新后重试')
      }
      return null
    } finally {
      if (!preflight?.ok) pendingBidWrites.delete(writeKey)
    }

    const idempotencyKey = createWritebackIdempotencyKey()

    try {
      await ElMessageBox.confirm(
        `将把「${keywordText || `关键词 #${keywordId}`}」的建议出价 ¥${Number(price).toFixed(2)}${currentPrice == null ? '' : `（当前 ¥${Number(currentPrice).toFixed(2)}）`}提交回写。\n${preflight.message}`,
        '确认关键词出价',
        { confirmButtonText: preflight.confirmButtonText, cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      pendingBidWrites.delete(writeKey)
      return null
    }
    if (!attempt.isCurrent()) {
      pendingBidWrites.delete(writeKey)
      return null
    }

    try {
      const response = await writebackKeyword({
        keywordId,
        tenantId: scopedTenantId,
        price: Number(price),
        confirmation: WRITEBACK_CONFIRMATION,
        idempotencyKey,
      })
      if (!attempt.isCurrent()) return null
      const trace = writebackTrace(response.writeback)
      const traceSuffix = trace ? `（${trace}）` : ''
      if (response.dry_run) {
        ElMessage.success(`已加入待回写台账，百度账户未修改，未创建或消费资金确认${traceSuffix}`)
        return { response, success: false, dryRun: true }
      }
      if (['pending', 'reconcile'].includes(response.writeback?.status)) {
        ElMessage.warning(`${response.writeback.error_msg || '百度执行结果未知，已转入人工对账'}${traceSuffix}`)
        return { response, success: false, reconciliationRequired: true }
      }
      if (response.writeback?.status !== 'success') {
        ElMessage.error(`${response.writeback.error_msg || '回写出价失败'}${traceSuffix}`)
        return { response, success: false }
      }
      ElMessage.success(`已回写百度：¥${Number(price).toFixed(2)}${traceSuffix}`)
      return await notifySuccess({ response, success: true }, attempt)
    } catch (error) {
      if (attempt.isCurrent()) ElMessage.error(error.response?.data?.detail || error.message)
      return null
    } finally {
      pendingBidWrites.delete(writeKey)
    }
  }

  async function changeMatchType(keywordId, keywordText, currentMatchLabel, command, accountId = null) {
    const target = MATCH_TYPE_OPTIONS[command]
    if (!target) return null
    const attempt = actionGuard.begin()
    const scopedTenantId = attempt.context.tenantId

    try {
      await ElMessageBox.confirm(
        `确认将「${keywordText}」的匹配模式从「${currentMatchLabel || '—'}」改为「${target.label}」？\n系统将按当前客户、推广账户和动作门禁决定演练或真实执行；真实执行会修改百度账户。`,
        '确认修改匹配模式',
        { confirmButtonText: '确认修改', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return null
    }
    if (!attempt.isCurrent()) return null

    try {
      const response = await matchTypeWriteback({
        keywordId,
        tenantId: scopedTenantId,
        matchType: target.matchType,
        phraseType: target.phraseType,
      })
      if (!attempt.isCurrent()) return null
      if (response.dry_run) {
        ElMessage.warning('演练模式：已记入台账，未真改线上匹配模式')
        return { response, success: false, dryRun: true }
      }
      if (response.writeback?.status === 'failed') {
        ElMessage.error(response.writeback.error_msg || '修改匹配模式失败')
        return { response, success: false }
      }
      ElMessage.success(`已回写百度：${target.label}`)
      return await notifySuccess({ response, success: true }, attempt)
    } catch (error) {
      if (attempt.isCurrent()) ElMessage.error(error.response?.data?.detail || error.message)
      return null
    }
  }

  async function togglePause(keywordId, keywordText, currentPause, accountId = null) {
    const attempt = actionGuard.begin()
    const scopedTenantId = attempt.context.tenantId
    const pause = !currentPause
    const action = pause ? '暂停' : '启用'

    try {
      await ElMessageBox.confirm(
        `将${action}关键词「${keywordText}」。\n系统将按当前客户、推广账户和动作门禁决定演练或真实执行；真实执行会修改百度账户。`,
        `确认${action}`,
        { confirmButtonText: `确认${action}`, cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return null
    }
    if (!attempt.isCurrent()) return null

    try {
      const response = await pauseKeywordBatch({
        tenantId: scopedTenantId,
        keywordIds: [keywordId],
        pause,
      })
      if (!attempt.isCurrent()) return null
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
        return await notifySuccess({ response, success: true }, attempt)
      }
      ElMessage.error(`${action}未执行`)
      return { response, success: false }
    } catch (error) {
      if (attempt.isCurrent()) ElMessage.error(error.response?.data?.detail || error.message)
      return null
    }
  }

  return { applyWriteback, changeMatchType, togglePause, invalidate: actionGuard.invalidate }
}
