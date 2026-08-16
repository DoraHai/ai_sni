/**
 * 监测空态：把「没数」说成能处理的原因。
 * 优先级：没引擎 → 巡检没开 → 还没跑 → 跑了但没落下回答 → 跑了但没提到品牌。
 */

export function diagnoseEmptyMonitoring({
  engineCount = 0,
  enabledEngines = 0,
  patrolEnabled = false,
  lastRunAt = null,
  snapshotCount = 0,
  mentionCount = null,
} = {}) {
  if (Number(engineCount) <= 0 || Number(enabledEngines) <= 0) {
    return {
      key: 'no_engine',
      title: '还没配监测引擎',
      detail: '没有启用的引擎，巡检查不到任何回答。先到引擎页打开至少一个。',
      action: '去配引擎',
      href: '/geo/engines',
      need: 'engines',
    }
  }
  if (!patrolEnabled && Number(snapshotCount) <= 0) {
    return {
      key: 'patrol_off',
      title: '定时巡检还没打开',
      detail: '引擎有了，但不会自动跑。打开巡检，或先手动登记一条回答。',
      action: '去开巡检',
      href: '/geo/visibility/patrol',
      need: 'patrol',
    }
  }
  if (Number(snapshotCount) <= 0 && !lastRunAt) {
    return {
      key: 'not_run',
      title: '今天还没跑过巡检',
      detail: '配置齐了，还没有样本。点一次「立即巡检」，或在可见度里手工登记。',
      action: '去跑巡检',
      href: '/geo/visibility/patrol',
      need: 'patrol',
    }
  }
  if (Number(snapshotCount) <= 0 && lastRunAt) {
    return {
      key: 'ran_empty',
      title: '巡检跑过了，但没有落下回答',
      detail: '可能没勾选自动落库，或引擎调用失败。打开最近一次巡检看明细。',
      action: '看巡检记录',
      href: '/geo/visibility/patrol',
      need: 'patrol',
    }
  }
  if (mentionCount != null && Number(snapshotCount) > 0 && Number(mentionCount) <= 0) {
    return {
      key: 'no_mention',
      title: '跑了，但品牌没被提到',
      detail: '有回答样本，本品没出现。这是内容缺口，不是系统没跑。',
      action: '去补缺口',
      href: '/geo/gaps',
      need: 'gaps',
    }
  }
  return null
}

export function needQuery(item) {
  if (!item?.href) return item?.href || '/'
  return {
    path: item.href,
    query: {
      need: item.need || item.key,
      why: item.detail || item.hint || '',
    },
  }
}
