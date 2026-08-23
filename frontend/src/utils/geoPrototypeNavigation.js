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
      { label: '评价分析', path: '/geo/evaluation', key: 'geo.content', icon: '◉' },
      { label: '信源分析', path: '/geo/citations', key: 'geo.content', icon: '▤' },
    ],
  },
  {
    label: 'GEO 执行',
    children: [
      { label: 'GEO 文章', path: '/geo/tasks', key: 'geo.content', icon: 'Aa' },
      { label: '媒体 / 信源策略', path: '/geo/placements', key: 'geo.content', icon: '⌂' },
      { label: '分发平台', path: '/geo/publishing', key: 'geo.content', icon: '⇧' },
      { label: '官网结构优化', path: '/geo/geo-diagnosis', key: 'geo.content', icon: '⌗' },
    ],
  },
  {
    label: '设置',
    children: [
      { label: '品牌信息', path: '/geo/brand', key: 'geo.content', icon: '▰' },
      { label: '知识库', path: '/geo/knowledge', key: 'geo.content', icon: '▣' },
      { label: 'AI 引擎管理', path: '/geo/models', key: 'geo.content', icon: '◇' },
    ],
  },
]
