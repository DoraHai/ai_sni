/**
 * GEO 侧栏 — 对齐原型 geo/assets/geo-sidebar-v1.js
 * 仅保留原型有的入口；不在侧栏暴露业务单元/关键词/周期对比/交付物/话题热度等扩展页。
 */
export const GEO_WORKBENCH_START = '/geo/overview'

export const GEO_WORKBENCH_NAV = [
  {
    label: '数据看板',
    children: [
      { label: 'GEO 概览', path: '/geo/overview', key: 'geo.content', icon: '▦' },
      { label: 'AI 可见度', path: '/geo/visibility', key: 'geo.content', icon: '✦' },
    ],
  },
  {
    label: '智能监测',
    children: [
      { label: '优化意图词', path: '/geo/questions', key: 'geo.content', icon: '◌' },
      { label: '竞品分析', path: '/geo/competitors', key: 'geo.content', icon: '≋' },
      { label: 'AI 引用次数', path: '/geo/citations', key: 'geo.content', icon: '↗' },
      { label: '事实库 / 信源', path: '/geo/knowledge', key: 'geo.content', icon: '▤' },
    ],
  },
  {
    label: '内容与信源',
    children: [
      { label: '优化文章', path: '/geo/tasks', key: 'geo.content', icon: 'Aa' },
      { label: '信源策略', path: '/geo/placements', key: 'geo.content', icon: '⌂' },
      { label: '分发平台', path: '/geo/publishing', key: 'geo.content', icon: '◎' },
    ],
  },
  {
    label: '设置',
    children: [
      { label: '品牌信息', path: '/geo/brand', key: 'geo.content', icon: '▰' },
      { label: 'AI 能力配置', path: '/geo/ai-settings', key: 'geo.content', icon: '⚙' },
      { label: '渠道成稿提示词', path: '/geo/channel-polish-prompts', key: 'geo.content', icon: '✎' },
      { label: '引擎', path: '/geo/models', key: 'geo.content', icon: '◇' },
    ],
  },
]
