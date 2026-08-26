// 当前生产安全策略：百度写回关闭。所有写操作只形成演练台账，供后续审核执行。
// 真写启用必须经过项目发布规范中的独立审批，不能由页面或用户自行切换。
export const SEM_WRITEBACK_ENABLED = false

export const SEM_READ_ONLY_MESSAGE = '当前为只读演练模式：数据、告警和建议可正常使用；操作只加入待回写台账，不会修改百度账户。'
