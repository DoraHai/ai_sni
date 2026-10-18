export const BACKFILL_CHANNELS = [
  { value: 'website', label: '官网 / 博客' },
  { value: 'wechat', label: '微信公众号' },
  { value: 'zhihu', label: '知乎' },
  { value: 'baijiahao', label: '百家号' },
  { value: 'news_source', label: '新闻源' },
  { value: 'baidu_zhidao', label: '百度问答（百度知道）' },
  { value: 'baidu_tieba', label: '百度贴吧' },
  { value: 'toutiao', label: '今日头条' },
  { value: 'other', label: '其他' },
]

export function backfillChannelLabel(channel) {
  return BACKFILL_CHANNELS.find(item => item.value === channel)?.label
    || { docs: '文档', industry_media: '行业媒体' }[channel] || channel || '—'
}

export function customChannelError(value) {
  const name = value.trim()
  if (!name || [...name].length > 30 || !/[\p{L}\p{N}]/u.test(name)) {
    return '请填写渠道名称，最多30个字，不能只填符号'
  }
  if (/[\p{C}\p{Zl}\p{Zp}]/u.test(name)) return '渠道名称不能包含换行或不可见字符'
  return ''
}

export function isHttpsPublicationUrl(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !!url.hostname && url.port !== '0'
      && !url.username && !url.password && !/[\s\p{C}]/u.test(value)
  } catch { return false }
}
