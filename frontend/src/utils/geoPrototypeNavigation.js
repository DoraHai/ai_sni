/**
 * GEO 侧栏 — 对齐原型 geo/assets/geo-sidebar-v1.js
 * Canonical 名称（侧栏 / 页面 h1 / documentTitle 必须一致）：
 * GEO 概览 · AI 可见度 · 采集与判断 · 优化意图词 · 竞品分析 · AI 引用次数 ·
 * 知识库 · 优化文章 · 信源策略 · 分发平台 · 品牌资料 · AI 能力配置 ·
 * 渠道成稿提示词 · 引擎
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
      { label: '知识库', path: '/geo/knowledge', key: 'geo.content', icon: '▤' },
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
      { label: '品牌资料', path: '/geo/brand', key: 'geo.content', icon: '▰' },
      { label: 'AI 能力配置', path: '/geo/ai-settings', key: 'geo.content', icon: '⚙' },
      { label: '渠道成稿提示词', path: '/geo/channel-polish-prompts', key: 'geo.content', icon: '✎' },
      { label: '引擎', path: '/geo/models', key: 'geo.content', icon: '◇' },
    ],
  },
]
