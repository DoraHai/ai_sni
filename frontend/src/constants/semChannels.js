// UI reservations only: these IDs are not backend provider identifiers.
export const SEM_PLANNED_CHANNELS = Object.freeze([
  Object.freeze({ id: 'bing', name: '必应', subtitle: 'Microsoft Advertising', description: '预留搜索广告工作区，账户授权、报表同步和投放管理尚未接入。' }),
  Object.freeze({ id: '360', name: '360', subtitle: '360 点睛', description: '预留国内搜索广告工作区，账户授权、报表同步和投放管理尚未接入。' }),
  Object.freeze({ id: 'soso', name: '搜搜', subtitle: '平台待确认', description: '暂按需求保留“搜搜”名称；正式广告平台及接入方式确认后再开发，不视为已支持搜狗或腾讯广告。' }),
])

export const semChannelPath = (id) => `/sem/channels/${id}`
