// 有效模式由后端按客户、推广账户和动作白名单返回，页面不提供开关。
export const SEM_READ_ONLY_MESSAGE = '当前客户为只读演练模式：操作只加入待回写台账，不会修改百度账户。'

export const SEM_LIMITED_LIVE_MESSAGE = '当前客户已开启受控真实回写：仅指定推广账户和动作可修改百度，其余操作仍保持演练。'

export const SEM_WRITE_SCOPE_LABELS = Object.freeze({
  account_budget: '账户预算',
  adgroup_bid: '单元出价',
  adgroup_landing_url: '单元落地页',
  adgroup_negative_words: '单元否词',
  adgroup_pause: '单元启停',
  campaign_budget: '计划预算',
  campaign_negative_words: '计划否词',
  campaign_pause: '计划启停',
  campaign_region: '计划地域',
  campaign_schedule: '计划时段',
  keyword_bid: '关键词出价',
  keyword_create: '新增关键词',
  keyword_match_type: '关键词匹配方式',
  keyword_pause: '关键词启停',
})
