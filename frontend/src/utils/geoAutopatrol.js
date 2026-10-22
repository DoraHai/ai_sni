export const PATROL_PLATFORMS = [
  ['doubao', '豆包'], ['deepseek', 'DeepSeek'], ['qwen', '千问'],
  ['hunyuan', '元宝（混元 API）'], ['wenxin', '文心'], ['kimi', 'Kimi'],
]
export const PLATFORM_STATUS = {
  available: '可用', not_configured: '平台未配置',
  auth_error: '平台鉴权/权限异常，等待平台处理', disabled: '平台未启用',
}
export const RUN_STATUS = {
  pending: '等待运行', running: '运行中', success: '成功',
  partial_success: '部分成功', failed: '全部失败', cancelled: '已取消',
}
export const EVENT_ACTION = {
  enable: '开启', disable: '关闭', force_disable: '强制关闭并加锁',
  unlock: '解锁', migrate: '切入每日自助模式', manual_limit_change: '修改手动次数',
}
const BLOCKED = {
  admin_locked: '管理员锁定', authorization_changed: '授权或项目负责关系已变更',
  no_prompts: '没有有效问题', no_platforms: '六家平台均不可用',
  geo_unavailable: 'GEO 服务不可用', demo_tenant: '演示客户不可开启',
  daily_budget_exhausted: '平台今日总额度已满', in_flight: '已有检测正在排队或运行',
  reserved_retest: '精确复测预约占用', write_disabled: '顾问操作暂未开放',
}
export function blockedLabel(reason) { return reason ? BLOCKED[reason] || '检测暂时受阻，请刷新状态' : '' }
export function patrolError(error) {
  if (error?.status === 404) return '功能未就绪'
  if (error?.status === 409) return '状态已变更或当前操作受阻，已刷新，请核对后重试'
  if (error?.status === 423) return '管理员已锁定，已刷新状态'
  return '操作未完成，请刷新状态后重试'
}
export function beijingTime(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}
export function scheduleMode(mode) {
  return mode === 'daily_self_service' ? '每日自助检测' : mode === 'legacy' ? '旧定时模式' : '模式未就绪'
}
export function patrolStatus(data) {
  if (data?.admin_locked) return '管理员锁定'
  if (data?.blocked_reason) return `受阻：${blockedLabel(data.blocked_reason)}`
  if (!data?.enabled) return '已关闭'
  if (data?.last_run?.status === 'pending' || data?.last_run?.status === 'running') return RUN_STATUS[data.last_run.status]
  return '已开启'
}
// Permissions come from the API. Never infer a grant from local role/project data.
export function toggleAllowed(data) {
  return !!data && !data.admin_locked && data.can_toggle === true
    && (data.enabled === true || data.can_enable === true)
}
export function manualLimitEditable(row) {
  return Number.isSafeInteger(row?.manual_limit_revision) && row.manual_limit_revision >= 0
    && Number.isInteger(row?.manual_quota?.limit) && row.manual_quota.limit >= 0 && row.manual_quota.limit <= 100
}

export function createSelfServiceController({ state, read, write }) {
  let tenantId = null, generation = 0, abort = null
  function clear() {
    generation++
    abort?.abort()
    Object.assign(state, { data: null, error: '', loading: false, busy: false })
  }
  async function load() {
    const id = tenantId
    clear()
    if (!id) return
    const version = generation
    abort = new AbortController()
    state.loading = true
    try {
      const data = await read(id, abort.signal)
      if (generation === version) state.data = data
    } catch (error) {
      if (generation === version) state.error = patrolError(error)
    } finally {
      if (generation === version) state.loading = false
    }
  }
  return {
    async setTenant(id) { tenantId = id; await load() },
    load,
    dispose() { tenantId = null; clear() },
    async toggle() {
      if (state.busy || state.loading || !toggleAllowed(state.data)) return
      const version = generation, id = tenantId
      const body = { tenant_id: id, enabled: !state.data.enabled, expected_revision: state.data.revision }
      state.busy = true
      state.error = ''
      try {
        const data = await write(body)
        if (generation === version) state.data = data
      } catch (error) {
        if (generation !== version) return
        if ([409, 423].includes(error?.status)) {
          const refreshVersion = generation + 1
          await load()
          if (generation !== refreshVersion) return
        }
        if (tenantId === id) state.error = patrolError(error)
      } finally {
        if (generation === version) state.busy = false
      }
    },
  }
}
