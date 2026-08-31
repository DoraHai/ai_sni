export const GEO_WORKBENCH_START = '/geo/overview'

/** 对齐 geo-v2 `assets/geo-sidebar-v1.js` */
export const GEO_PROTOTYPE_GROUPS = [
  { label: '数据看板', pages: ['overview', 'visibility'] },
  { label: '智能监测', pages: ['prompts', 'competitors', 'sources'] },
  { label: '内容与信源', pages: ['articles', 'media', 'channels', 'structure'] },
  { label: '设置', pages: ['brand', 'knowledge', 'ai-settings', 'engines'] },
]

export const GEO_PROTOTYPE_PAGES = [
  { id: 'overview', label: 'GEO 概览', path: '/geo/overview', icon: '▦' },
  { id: 'visibility', label: 'AI 可见度', path: '/geo/visibility', icon: '✦' },
  { id: 'prompts', label: '提问监控', path: '/geo/prompts', icon: '◌' },
  { id: 'competitors', label: '竞品分析', path: '/geo/competitors', icon: '≋' },
  { id: 'evaluation', label: '评价分析', path: '/geo/evaluation', hidden: true },
  { id: 'sources', label: '信源分析', path: '/geo/sources', icon: '▤' },
  { id: 'articles', label: 'GEO 文章', path: '/geo/articles', icon: 'Aa' },
  { id: 'import', label: '导入已有文章', path: '/geo/import', hidden: true },
  { id: 'editor', label: '在线编辑器', path: '/geo/articles/:taskId', hidden: true },
  { id: 'distribution', label: '分发记录', path: '/geo/articles/:taskId/distribution', hidden: true },
  { id: 'media', label: '媒体 / 信源策略', path: '/geo/media', icon: '⌂' },
  { id: 'channels', label: '分发平台', path: '/geo/channels', icon: '⇧' },
  { id: 'structure', label: '官网结构优化', path: '/geo/structure', icon: '⌗' },
  { id: 'brand', label: '品牌信息', path: '/geo/brand', icon: '▰' },
  { id: 'knowledge', label: '知识库', path: '/geo/knowledge', icon: '▣' },
  { id: 'ai-settings', label: 'AI 能力配置', path: '/geo/ai-settings', icon: '⚙' },
  { id: 'engines', label: 'AI 引擎管理', path: '/geo/engines', icon: '◇' },
]
