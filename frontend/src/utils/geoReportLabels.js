/**
 * GEO 报表共用文案与格式化 — 保证各页字段表述一致、可维护。
 */

export const SENTIMENT_LABEL = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
  unknown: '未知',
}

export const POSITION_LABEL = {
  first: '首位推荐',
  alternative: '备选/次选',
  mentioned: '有提及',
  absent: '未出现',
  unknown: '未知',
}

export const CITATION_FORMAT_LABEL = {
  linked: '链接引用',
  plaintext: '纯文本提及',
  mixed: '链接+文本混合',
  none: '无引用',
  unknown: '未标注',
}

export const CITATION_ACCURACY_LABEL = {
  accurate: '准确',
  partial: '部分准确',
  inaccurate: '不准确',
  unknown: '未校验',
}

export const HEAT_LABEL = {
  rising: '覆盖上升',
  falling: '覆盖回落',
  stable: '覆盖平稳',
}

export const ENGINE_LABEL = {
  chatgpt: 'ChatGPT',
  deepseek: 'DeepSeek',
  doubao: '豆包',
  kimi: 'Kimi',
  qwen: '通义千问',
  tongyi: '通义千问',
  yuanbao: '腾讯元宝',
  hunyuan: '腾讯元宝',
  claude: 'Claude',
  gemini: 'Gemini',
  perplexity: 'Perplexity',
  other: '其他',
}

export const TASK_STATUS_LABEL = {
  draft: '草稿',
  facts_bound: '已绑事实',
  editing: '写稿中',
  generating: '生成中',
  needs_fix: '待修补',
  ready: '可发布',
  exported: '已导出',
  published: '已发布',
  archived: '已归档',
  failed: '生成失败',
}

export const PIPELINE_LABEL = {
  opportunity: '补策略',
  evidence: '绑事实',
  draft: '写母稿',
  adapt: '出渠道稿',
  publish: '发布',
}

export const REVIEW_STATUS_LABEL = {
  none: '未提交审校',
  pending: '待审校',
  approved: '审校已通过',
  rejected: '审校已驳回',
}

export function taskStatusLabel(status) {
  return TASK_STATUS_LABEL[status] || status || '—'
}

export function pipelineLabel(step) {
  return PIPELINE_LABEL[step] || step || '—'
}

export function reviewStatusLabel(status) {
  return REVIEW_STATUS_LABEL[status] || status || '—'
}

/**
 * 任务编辑器「当前下一步」。只告诉人现在该做什么，不改流程。
 */
export function nextEditorStep(task, extras = {}) {
  const facts = extras.boundFacts || task?.facts || []
  const verified = facts.filter((f) => f.trust_level === 'verified').length
  const hasArticle = extras.hasArticle ?? !!(task?.article)
  const variants = extras.variants || task?.variants || []
  const pubs = extras.publications || task?.publications || []
  const review = task?.review_status || 'none'
  const status = task?.status || 'draft'
  const briefReady = !!task?.brief_ready
  const checkFailed = !!extras.checkFailed
  const blocked = extras.blocked || ''

  if (status === 'published' || pubs.some((p) => p.published_url)) {
    return {
      key: 'impact',
      title: '看这篇发出去之后有没有用',
      detail: '核对提及率和引用命中。样本不够就去复测。',
      action: '看效果',
    }
  }
  if (!briefReady) {
    return {
      key: 'brief',
      title: '先写清这篇要回答什么',
      detail: '行业、受众、意图、号召保存后，才能生成能用的母稿。',
      action: '去保存策略',
    }
  }
  if (facts.length < 3 || verified < 3) {
    return {
      key: 'facts',
      title: '绑上至少 3 条已核验事实',
      detail: `现在已核验 ${verified} / 共 ${facts.length} 条。没有事实，生成会空转或编造。`,
      action: '去绑事实',
    }
  }
  if (!hasArticle) {
    return {
      key: 'generate',
      title: '生成母稿',
      detail: '策略和事实齐了，可以出第一版正文。',
      action: '生成母稿',
    }
  }
  if (status === 'needs_fix' || checkFailed) {
    return {
      key: 'check',
      title: '先过检查再往下',
      detail: blocked || '母稿还有未过项，点检查看卡在哪。',
      action: '去检查',
    }
  }
  if (!variants.length) {
    return {
      key: 'variants',
      title: '生成渠道稿',
      detail: '母稿好了，按官网 / 微信 / 知乎拆一版再发。',
      action: '生成渠道稿',
    }
  }
  if (review === 'none') {
    return {
      key: 'submit-review',
      title: '提交审校',
      detail: '渠道稿已出，通过审校后才能回填发布地址。',
      action: '提交审校',
    }
  }
  if (review === 'pending') {
    return {
      key: 'wait-review',
      title: '等审校通过',
      detail: '已经交上去了。通过后才能回填网址或推送。',
      action: '看审校',
    }
  }
  if (review === 'rejected') {
    return {
      key: 'fix-review',
      title: '按审校意见改完再提',
      detail: '上次没过。改完母稿或渠道稿后重新提交。',
      action: '去修改',
    }
  }
  return {
    key: 'publish',
    title: '回填发布地址',
    detail: '审校已过。贴上发出去的网址，系统才能证明这篇有用。',
    action: '去回填',
  }
}

/** 各报表页口径说明（短句，放页头或折叠「统计口径」） */
export const REPORT_GLOSSARY = {
  citations: [
    '数据来源：回答快照里的引用 URL（cited_urls），不是全网外链抓取。',
    '引用次数：同一域名在多条快照中重复出现会累加。',
    '自有域：发布渠道中「官网/文档」的域名；未配置则无法计算自有引用率。',
    '引用格式/准确性：来自快照标注（可人工改，也可在可见度页点「校验引用」）。',
  ],
  evaluation: [
    '数据来源：可见度回答快照的人工/建议标注。',
    '本品位置：首位 / 备选 / 提及 / 未出现；与竞品对比页口径一致。',
    '情感：对本品的评价倾向；未提及品牌时多为「未知」。',
    '引用质量：格式与准确性字段，需持续标注才有分析价值。',
  ],
  topicHeat: [
    '覆盖热度：按「意图词 × 引擎 × 日」去重后的覆盖格，避免巡检重复刷高。',
    '监测活跃度：原始快照条数，并拆分巡检 / 人工。',
    '上升/下降：窗口后半段相对前半段变化 ≥30% 且样本足够。',
    '外部市场热度请看「AI 动态」，不与本页混算。',
  ],
  competitors: [
    '竞品名来自快照 competitors 字段（人工或 AI 建议）。',
    '日监测：写入按天汇总表，支持业务/单元/意图词/引擎切片；缺行时页面静默补算。',
    '同题对比：同一意图词下本品提及 vs 竞品提及。',
  ],
  periodDiff: [
    '对比两个时间窗的可见性指标差值（百分点 pp）。',
    '品牌提及率排除探测题；点名认知率仅统计探测题。',
    '自有域引用率：含引用 URL 的快照中，至少一条指向自有域的占比。',
  ],
  deliverables: [
    '交付包汇总选定周期内的日指标、任务与引用样本，便于对外说明。',
    '可按优化业务 / 单元切片；导出 Markdown 便于粘贴周报。',
  ],
  aiTrends: [
    '动态目录为人工维护的公开信息摘要，非实时新闻抓取。',
    '策略建议结合本租户引擎配置、巡检与监测数据生成。',
  ],
  overview: [
    'KPI 优先取日指标切片；无切片时回退内容统计。',
    '本周洞察对比近 7 天与前 7 天；依赖日指标与快照积累。',
    '品牌提及率排除探测题；点名认知率仅统计探测题。',
  ],
  visibility: [
    '快照是报表的原始样本：巡检自动落库或本页手工登记均可。',
    '提及 / 位置 / 情感 / 引用质量可在列表里改，会立刻影响下游报表。',
    '「用 AI 探测」只填草稿不写库；批量真采样请用「全自动巡检」。',
    '引用 URL 决定引用分析与自有域占比；保存前可用「抽取 URL / 校验引用」。',
  ],
  businesses: [
    '结构：优化业务 → 优化单元（关键词）→ 优化意图词 → 优化文章。',
    '按天汇总跟随顶栏观察期；切片含租户 / 业务 / 单元，可按引擎过滤。',
    '品牌提及率排除探测题；点名认知率仅探测题；引用次数来自 cited_urls。',
    '领先竞品取当日可见快照里出现最多的竞品名及其提及率。',
  ],
  prompts: [
    '意图词是巡检与可见度登记的问题清单；需挂到优化单元才进业务切片。',
    '探测题（品牌点名）不计入品牌提及率，只进点名认知率。',
    '归档后默认不参与巡检队列；可筛选「已归档」找回。',
  ],
  dailyMetrics: [
    '可见快照：非探测题回答样本；探测快照：品牌点名题样本。',
    '首位推荐率：brand_position=first 占可见快照比例。',
    'AI 引用次数：cited_urls 出现总次数；独立域名去重计数。',
  ],
  patrol: [
    '巡检 = 活跃意图词 × 所选引擎批量探测；结果可自动落库为回答快照。',
    '真采样：引擎已配 openai_compat Key 时走真实接口；否则用租户 LLM + 引擎人设模拟。',
    '自动落库开启后直接写库；关闭则只产生运行明细，需到「登记快照」手工确认。',
    '定时由主站 scheduler 每小时 :05 检查时段与间隔；受日配额限制。',
  ],
  engines: [
    '启用引擎会出现在可见度登记与全自动巡检的引擎列表中。',
    '人设模拟：走租户 LLM + 该引擎人设，适合联调；不代表真实厂牌回答。',
    '兼容接口真采样：需填写 Base URL、Model，并配置 API Key（≥8 字符才写入）。',
    '巡检页「真采样就绪」= 模式为兼容接口且已配置 Key。',
  ],
}

/** 巡检运行状态 */
export const PATROL_STATUS_LABEL = {
  pending: '排队中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

/** 巡检触发方式 */
export const PATROL_TRIGGER_LABEL = {
  manual: '手动',
  scheduled: '定时',
  api: 'API',
}

/** 采样模式 */
export const SAMPLE_MODE_LABEL = {
  openai_compat: '兼容接口真采样',
  mock_persona: '人设模拟',
  simulated: '模拟',
  real: '真采样',
}

/** 日指标表头：短标签 + 悬停说明 */
export const DAILY_METRIC_COLUMNS = {
  brand_mention_rate: {
    label: '品牌提及率',
    hint: '非探测题快照中提及本品的比例',
  },
  brand_probe_recognition_rate: {
    label: '点名认知率',
    hint: '仅探测题：被问到品牌时是否识别到本品',
  },
  top1_rate: {
    label: '首位推荐率',
    hint: '可见快照中位置标注为「首位」的比例',
  },
  citation_count: {
    label: 'AI 引用次数',
    hint: '回答里引用 URL 出现总次数（非全网抓取）',
  },
  distinct_cited_domains: {
    label: '独立域名',
    hint: '被引 URL 去重后的域名数',
  },
  snapshots_visibility: {
    label: '可见快照',
    hint: '非探测题回答样本数',
  },
  snapshots_probe: {
    label: '探测快照',
    hint: '品牌点名题样本数',
  },
  top_competitor: {
    label: '领先竞品',
    hint: '当日可见快照中出现最多的竞品名',
  },
  top_competitor_rate: {
    label: '竞品提及率',
    hint: '领先竞品在可见快照中的提及比例',
  },
}

export function labelOf(map, key, fallback = '—') {
  if (key == null || key === '') return fallback
  return map[key] ?? String(key)
}

export function fmtPct(v, digits = 1) {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

export function fmtInt(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('zh-CN')
}

export function fmtDeltaPct(v, digits = 1) {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

export function fmtDeltaPp(v, digits = 1) {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(digits)} pp`
}

export function fmtCaptured(iso) {
  if (!iso) return '—'
  const s = String(iso)
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  if (m) return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}`
  return s.length > 16 ? s.slice(0, 16) : s
}

export function engineDisplay(key) {
  return labelOf(ENGINE_LABEL, key, key || '—')
}

/** 简单 CSV 导出（UTF-8 BOM，Excel 友好） */
export function downloadCsv(filename, headers, rows) {
  const escape = (cell) => {
    const s = cell == null ? '' : String(cell)
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [headers.map(escape).join(',')]
  for (const row of rows) {
    lines.push(row.map(escape).join(','))
  }
  const blob = new Blob(['\ufeff' + lines.join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.click()
  URL.revokeObjectURL(href)
}

export function countsToRows(counts, labelMap, dim) {
  if (!counts || typeof counts !== 'object') return []
  return Object.entries(counts).map(([k, v]) => ({
    dim,
    code: k,
    value: labelOf(labelMap, k, k),
    count: Number(v) || 0,
  }))
}
