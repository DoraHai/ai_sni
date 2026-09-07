export function urgencyReply({ unresolvedModules, businessUrgentItems }) {
  const modules = Number.isSafeInteger(unresolvedModules) && unresolvedModules > 0 ? unresolvedModules : 0
  const actions = Number.isSafeInteger(businessUrgentItems) && businessUrgentItems > 0 ? businessUrgentItems : 0
  if (modules && actions) return `有 ${modules} 个模块还未完成数据读取；已读取的数据中有 ${actions} 项业务事项建议现在处理。`
  if (modules) return `有 ${modules} 个模块还需要选择业务范围，或处理读取异常。`
  if (actions) return `已读取的数据中有 ${actions} 项业务事项建议现在处理，可以从行动台账进入。`
  return ''
}
