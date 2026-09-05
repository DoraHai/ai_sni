const ISSUE_RULES = {
  title: ['Title 需优化', '核对长度、主题与搜索意图，保留品牌和核心词。'],
  title_missing: ['缺少 Title', '补充唯一 Title，明确页面主题、核心词与品牌。'],
  title_too_long: ['Title 过长', '删除重复与模板词，优先保留主题、核心词和品牌。'],
  description: ['Description 需优化', '重写为可核实的页面摘要，避免空泛模板话术。'],
  description_missing: ['缺少 Description', '补充与页面现有内容一致的摘要，不添加无证据卖点。'],
  h1: ['H1 需优化', '保留一个表达页面主题的 H1，与 Title 分工而不是堆词。'],
  h1_missing: ['缺少 H1', '补充一个与页面主题和主关键词一致的 H1。'],
  h1_multiple: ['H1 过多', '合并为一个主 H1，其余标题降为 H2/H3。'],
  canonical: ['Canonical 需优化', '核对 Canonical 是否指向当前首选页，上线前由技术人员确认。'],
  indexable: ['索引设置异常', '先确认人工索引意图，再复核 robots meta 和 X-Robots-Tag。'],
  noindex: ['检测到 noindex', '不要自动移除；先确认该页是否应参与自然搜索。'],
  robots_blocked: ['Robots 拦截', '先复核抓取规则与页面用途；拦截抓取不等于已禁止索引。'],
  heading_depth: ['标题结构不足', '按内容逻辑补齐 H2/H3，不为了层级而制造空标题。'],
  substantial: ['内容量不足', '根据真实用户问题补充定义、适用场景、步骤与可核实参数。'],
  thin_content: ['内容过少', '优先补充能解决搜索意图的实质内容，不用重复句子凑字数。'],
  schema: ['缺少 Schema', '根据页面真实类型选择 Schema，字段必须与可见内容一致。'],
  image_alt_missing: ['图片缺少 Alt', '进入图片 Alt 工作台逐图人工判断用途，装饰图保持空 Alt。'],
  html_lang_missing: ['缺少 HTML lang', '按页面实际语言补充 lang，不根据域名臆测。'],
}

const text = (value, fallback = '—') => String(value ?? '').trim() || fallback

export function sourcePageRemediationContext(page) {
  if (!page) return null
  const issueCodes = Array.isArray(page.issue_codes) ? page.issue_codes.slice(0, 12) : []
  return {
    score: page.audit_score ?? null,
    checkedAt: page.last_checked_at || null,
    assessmentState: page.diagnostic?.assessment_state || 'unknown',
    current: {
      title: text(page.title),
      description: text(page.meta_description),
      h1: text(page.h1),
    },
    suggested: {
      title: text(page.title_suggestion, '待人工拟定'),
      description: text(page.description_suggestion, '待人工拟定'),
      h1: issueCodes.some(code => ['h1', 'h1_missing', 'h1_multiple'].includes(code))
        ? '根据页面主题拟定唯一 H1（需人工确认）'
        : '保持当前 H1，上线前复核',
    },
    issues: issueCodes.map(code => ({
      code,
      label: ISSUE_RULES[code]?.[0] || code,
      action: ISSUE_RULES[code]?.[1] || '根据页面检测证据人工复核，不自动修改官网。',
    })),
  }
}

export function buildSourcePageAssistInstruction(page, keywordNames = []) {
  const context = sourcePageRemediationContext(page)
  if (!context) return ''
  const lines = [
    `承接页：${text(page.url)}`,
    `目标关键词：${keywordNames.length ? keywordNames.join('、') : '待人工确认'}`,
    `当前 Title：${context.current.title}`,
    `已存档 Title 建议（可能经 AI 或人工编辑）：${context.suggested.title}`,
    `当前 Description：${context.current.description}`,
    `已存档 Description 建议（可能经 AI 或人工编辑）：${context.suggested.description}`,
    `当前 H1：${context.current.h1}`,
    ...context.issues.map(item => `程序检测 ${item.label}：${item.action}`),
    '仅基于上述已存档证据辅助拟稿；不虚构参数、案例或效果，结果须人工审核，勿直接发布。',
  ]
  return lines.join('\n').slice(0, 5000)
}
