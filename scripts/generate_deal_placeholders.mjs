import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve('frontend/public/deal-sniper-prototype')

const modules = {
  hub: {
    brand: '全域层',
    sub: '跨渠道机会与待办',
    icon: 'S',
    groups: [
      {
        title: '经营',
        items: [
          ['dashboard.html', '全域驾驶舱', '▦'],
          ['intents.html', '意图中心', '⌁'],
          ['todos.html', '统一待办', '✓'],
          ['reports.html', '周/月报告', 'R'],
          ['sources.html', '数据源接入', 'S'],
          ['onboarding.html', '新项目建档', '+'],
        ],
      },
      {
        title: '获客渠道',
        items: [
          ['/monitor/dashboard', 'SEM 投放', '￥'],
          ['../seo/dashboard.html', 'SEO 优化', '搜'],
          ['../geo/dashboard.html', 'GEO 可见度', 'AI'],
        ],
      },
      {
        title: '诊断与资产',
        items: [
          ['../content/audit.html', '诊断中心', '!'],
          ['../content/brand.html', '品牌资产', 'B'],
        ],
      },
    ],
  },
  seo: {
    brand: 'SEO 工作台',
    sub: '搜索引擎获客',
    icon: 'S',
    groups: [
      { title: '今日概览', items: [['dashboard.html', 'SEO 工作台', '▦']] },
      {
        title: '关键词资产',
        items: [
          ['manage.html', '关键词管理', '⌕'],
          ['keywords.html', '排名监控', '↗'],
          ['keyword-trend.html', '单关键词历史', '⌁'],
          ['trends.html', '趋势总览', '⌁'],
          ['competitors.html', '竞品表现', '≋'],
        ],
      },
      {
        title: '内容增长',
        items: [
          ['articles.html', '原创文章', 'Aa'],
          ['rewrites.html', '伪原创文章', '↻'],
          ['questions.html', '问答运营', 'Q'],
          ['editor.html', '在线编辑器', 'E'],
          ['answer-editor.html', '问答编辑器', 'A'],
          ['channels.html', '分发平台', '⇧'],
        ],
      },
      { title: '站内优化', items: [['tdk.html', 'TDK / 站内优化', 'T']] },
    ],
  },
  geo: {
    brand: 'GEO 工作台',
    sub: '生成式引擎获客',
    icon: 'G',
    groups: [
      {
        title: '数据看板',
        items: [
          ['dashboard.html', 'GEO 概览', '▦'],
          ['visibility.html', 'AI 可见度', '✦'],
        ],
      },
      {
        title: '智能监测',
        items: [
          ['prompts.html', '提问监控', '◌'],
          ['competitors.html', '竞品分析', '≋'],
          ['evaluation.html', '评价分析', '◉'],
          ['sources.html', '信源分析', '▤'],
        ],
      },
      {
        title: '内容与信源',
        items: [
          ['articles.html', 'GEO 文章', 'Aa'],
          ['editor.html', '在线编辑器', 'E'],
          ['media.html', '媒体 / 信源策略', '⌂'],
          ['channels.html', '分发平台', '⇧'],
        ],
      },
      { title: '设置', items: [['engines.html', 'AI 引擎管理', '◇']] },
    ],
  },
  content: {
    brand: '诊断中心',
    sub: '只诊断不执行',
    icon: '!',
    groups: [
      {
        title: '诊断',
        items: [
          ['audit.html', '网站体检', '!'],
          ['tdk.html', 'TDK 优化', 'T'],
          ['schema.html', '结构化数据', '{}'],
          ['optimize.html', '优化建议', '✓'],
        ],
      },
      {
        title: '共享资产',
        items: [
          ['brand.html', '品牌资料', 'B'],
          ['audience.html', '目标用户', 'U'],
          ['knowledge.html', '知识库', 'K'],
          ['accounts.html', '发布账号', 'A'],
          ['media.html', '媒体平台', 'M'],
          ['library.html', '内容库', 'L'],
          ['records.html', '分发记录', 'R'],
          ['produce.html', '内容生产', 'P'],
          ['own.html', '自有资产', 'O'],
        ],
      },
    ],
  },
}

function html(moduleKey, fileName) {
  const mod = modules[moduleKey]
  const pageLabels = new Map()
  for (const group of mod.groups) {
    for (const [href, label] of group.items) {
      if (!href.startsWith('/') && !href.startsWith('..')) pageLabels.set(href, label)
    }
  }
  const pageTitle = pageLabels.get(fileName) || mod.brand
  const nav = mod.groups.map((group) => `
    <div class="nav-group">${group.title}</div>
    ${group.items.map(([href, label, icon]) => {
      const active = href === fileName ? ' active' : ''
      const target = href.startsWith('/monitor') ? ' target="_top"' : ''
      return `<a class="nav-item${active}" href="${href}"${target}><span class="ico">${icon}</span>${label}</a>`
    }).join('\n    ')}
  `).join('\n')

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>${pageTitle} · 开发中</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    min-height: 100vh;
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    background: #f5f7fb;
    color: #1f2937;
  }
  .layout { min-height: 100vh; display: grid; grid-template-columns: 238px minmax(0, 1fr); }
  .sidebar {
    height: 100vh;
    position: sticky;
    top: 0;
    display: flex;
    flex-direction: column;
    background: #fff;
    border-right: 1px solid #e5e9f1;
  }
  .brand {
    min-height: 76px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 18px 18px;
    border-bottom: 1px solid #edf0f5;
    font-weight: 760;
  }
  .logo {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border-radius: 9px;
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    color: #fff;
    font-weight: 850;
  }
  .brand small {
    display: block;
    margin-top: 3px;
    color: #9aa3b2;
    font-size: 12px;
    font-weight: 600;
  }
  .nav { flex: 1; overflow: auto; padding: 14px 10px; }
  .nav-group {
    margin: 16px 10px 8px;
    color: #9aa3b2;
    font-size: 12px;
    font-weight: 760;
  }
  .nav-item {
    min-height: 36px;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 10px;
    border-radius: 7px;
    color: #586274;
    font-size: 13px;
    font-weight: 650;
    text-decoration: none;
  }
  .nav-item:hover { background: #f4f7fb; color: #2563eb; }
  .nav-item.active {
    background: #eef4ff;
    color: #1d4ed8;
  }
  .ico {
    width: 22px;
    flex: none;
    color: inherit;
    opacity: 0.88;
    text-align: center;
    font-size: 13px;
  }
  .side-foot {
    display: grid;
    gap: 8px;
    padding: 14px 18px 18px;
    border-top: 1px solid #edf0f5;
  }
  .side-foot a {
    color: #7b8494;
    font-size: 12px;
    font-weight: 650;
    text-decoration: none;
  }
  .main { min-width: 0; display: flex; flex-direction: column; }
  .topbar {
    min-height: 58px;
    display: flex;
    align-items: center;
    padding: 0 26px;
    border-bottom: 1px solid #e5e9f1;
    background: #fff;
    color: #6b7280;
    font-size: 14px;
    font-weight: 650;
  }
  .topbar b { color: #1f2937; font-weight: 760; }
  .content {
    flex: 1;
    min-height: 0;
    display: grid;
    place-items: center;
    padding: 24px;
  }
  .empty {
    transform: translateY(-5vh);
    text-align: center;
    color: #9aa3b2;
  }
  .box { width: 188px; height: 188px; opacity: 0.42; margin-bottom: 18px; }
  .title { font-size: 17px; font-weight: 650; line-height: 1.7; }
  @media (max-width: 760px) {
    .layout { grid-template-columns: 1fr; }
    .sidebar { position: static; height: auto; }
    .nav { max-height: 42vh; }
    .empty { transform: none; }
  }
</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="brand">
      <span class="logo">${mod.icon}</span>
      <div>${mod.brand}<small>${mod.sub}</small></div>
    </div>
    <nav class="nav">${nav}
    </nav>
    <div class="side-foot">
      <a href="/deal-sniper-prototype/index.html">← 返回平台门户</a>
      <a href="/monitor/dashboard" target="_top">进入已实现 SEM</a>
    </div>
  </aside>
  <main class="main">
    <header class="topbar">${mod.brand} &nbsp;/&nbsp; <b>${pageTitle}</b></header>
    <section class="content">
      <div class="empty">
        <svg class="box" viewBox="0 0 240 240" aria-hidden="true">
          <defs>
            <linearGradient id="g1" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stop-color="#ffffff"/>
              <stop offset="1" stop-color="#d9dde7"/>
            </linearGradient>
            <linearGradient id="g2" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0" stop-color="#eef1f7"/>
              <stop offset="1" stop-color="#cfd5e1"/>
            </linearGradient>
          </defs>
          <ellipse cx="122" cy="195" rx="86" ry="13" fill="#e9edf4"/>
          <path d="M74 100h92v92H74z" fill="url(#g1)"/>
          <path d="M74 100l28-42h92l-28 42z" fill="#f8fafc"/>
          <path d="M166 100l28-42 34 52-30 42z" fill="url(#g2)"/>
          <path d="M74 100l-31 44h31z" fill="#d9dee8"/>
          <path d="M166 100l31 44h-31z" fill="#cfd5e1"/>
          <path d="M102 58l64 42h-92z" fill="#eef1f7"/>
          <path d="M142 69l48 22 10 24-47-22z" fill="#d9dee8"/>
          <path d="M74 100h92v92H74z" fill="none" stroke="#e2e6ee"/>
        </svg>
        <div class="title">「${pageTitle}」开发中，接入真实功能后开放</div>
      </div>
    </section>
  </main>
</div>
</body>
</html>
`
}

for (const moduleKey of Object.keys(modules)) {
  const dir = path.join(root, moduleKey)
  for (const file of fs.readdirSync(dir)) {
    if (!file.endsWith('.html')) continue
    if (moduleKey === 'content' && ['audit.html', 'optimize.html'].includes(file)) continue
    fs.writeFileSync(path.join(dir, file), html(moduleKey, file))
  }
}

fs.writeFileSync(path.join(root, 'acquisition-preview.html'), html('hub', 'dashboard.html'))
