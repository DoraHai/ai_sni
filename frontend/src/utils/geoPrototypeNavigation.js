/**
 * GEO 侧栏 — 对齐 5173 原型分组与文案，路由保持独立 GEO 的 canonical path。
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
      { label: '提问监控', path: '/geo/questions', key: 'geo.content', icon: '◌' },
      { label: '竞品分析', path: '/geo/competitors', key: 'geo.content', icon: '≋' },
      { label: '信源分析', path: '/geo/citations', key: 'geo.content', icon: '▤' },
    ],
  },
  {
    label: '内容与信源',
    children: [
      { label: 'GEO 文章', path: '/geo/tasks', key: 'geo.content', icon: 'Aa' },
      { label: '媒体 / 信源策略', path: '/geo/placements', key: 'geo.content', icon: '⌂' },
      { label: '分发平台', path: '/geo/publishing', key: 'geo.content', icon: '⇧' },
      { label: '官网结构优化', path: '/geo/structure', key: 'geo.content', icon: '⌗' },
    ],
  },
  {
    label: '设置',
    children: [
      { label: '品牌信息', path: '/geo/brand', key: 'geo.content', icon: '▰' },
      { label: '知识库', path: '/geo/knowledge', key: 'geo.content', icon: '▣' },
      { label: 'AI 能力配置', path: '/geo/ai-settings', key: 'geo.content', icon: '⚙' },
      { label: 'AI 引擎管理', path: '/geo/models', key: 'geo.content', icon: '◇' },
    ],
  },
]
