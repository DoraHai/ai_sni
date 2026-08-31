/** Turn channel-polish quality_issues into a short title + how-to-fix hint. */

export function filterGateIssuesForBody(items, body) {
  const bodyText = String(body || '').replace(/\s+/g, '')
  return (Array.isArray(items) ? items : []).flatMap((raw) => {
    const text = String(raw || '').trim()
    if (!/无依据表述/.test(text)) return text ? [text] : []
    const claims = [...text.matchAll(/(数字|性能表述|案例表述)「([^」]+)」/g)]
    if (!claims.length) return text ? [text] : []
    const visible = claims.filter((match) => bodyText.includes(String(match[2]).replace(/\s+/g, '')))
    if (!visible.length) return []
    return [`无依据表述：${visible.map((match) => `${match[1]}「${match[2]}」`).join('、')}`]
  })
}

export function explainGateIssue(raw) {
  const text = String(raw || '').replace(/\s+/g, ' ').trim()
  if (!text) return { title: '未过门控', hint: '' }

  if (/无依据表述/.test(text)) {
    const quoted = [...text.matchAll(/「([^」]+)」/g)].map((m) => m[1])
    const shown = quoted.length ? quoted.map((t) => `「${t}」`).join('、') : '未在事实中出现的数字或案例'
    return {
      title: `AI 候选渠道稿包含未绑定数字${shown}`,
      hint: '这是被门控拒绝的 AI 候选稿问题；当前显示的回退稿可能不包含该数字。请重新生成，或在确认数字真实后补充事实卡。',
    }
  }

  const para = text.match(/完整论述段落不足[（(](\d+)\s*\/\s*(\d+)[）)]/)
  if (para) {
    return {
      title: `完整论述只有 ${para[1]} 段，需要 ${para[2]} 段`,
      hint: '把列表和短句收成连贯段落；每段大约 100 字以上，列表和表格不计入。',
    }
  }

  const paraAlt = text.match(/完整论述段落不足.*?现在\s*(\d+)\s*段.*?需要\s*(\d+)\s*段/)
  if (paraAlt) {
    return {
      title: `完整论述只有 ${paraAlt[1]} 段，需要 ${paraAlt[2]} 段`,
      hint: '把列表和短句收成连贯段落；每段大约 100 字以上，列表和表格不计入。',
    }
  }

  const split = text.match(/^([^：:]{2,24})[：:](.+)$/)
  if (split) {
    return { title: split[1].trim(), hint: split[2].trim() }
  }
  return { title: text, hint: '' }
}

export function formatGateFailRows(items, channelLabel, limit = 4) {
  const rows = (Array.isArray(items) ? items : []).map((f, i) => {
    const raw = (f.issues && f.issues[0]) || f.message || '未过门控'
    const { title, hint } = explainGateIssue(raw)
    const label = typeof channelLabel === 'function' ? channelLabel(f.channel) : f.channel
    return {
      key: String(f.channel || i),
      channel: label || f.channel || '渠道',
      title,
      hint,
    }
  })
  return {
    rows: rows.slice(0, limit),
    extra: Math.max(0, rows.length - limit),
  }
}
