(function () {
  'use strict';

  var page = document.body.dataset.keywordPage || 'manage';
  var STORE_KEY = 'growthEngine.seo.keywordAssets.prototype.v2';
  var engines = {
    baidu: { label: '百度', short: '百' },
    google: { label: 'Google', short: 'G' },
    bing: { label: 'Bing', short: 'B' },
  };
  var state = { engine: 'baidu', query: '', priority: '', intent: '', range: 14 };

  var baseKeywords = [
    { id: 'crm-system', keyword: 'CRM系统', cluster: 'CRM 核心词', intent: '产品', volume: 8900, difficulty: 78, priority: 'P0', landing: '/products/crm', status: '重点监控', ranks: { baidu: 8, google: 12, bing: 5 }, delta: { baidu: 3, google: 1, bing: -1 }, history: [18,17,17,15,16,14,13,12,10,11,10,9,8,8], competitor: [6,11,15] },
    { id: 'crm-price', keyword: 'CRM系统价格', cluster: '价格意图', intent: '价格', volume: 3600, difficulty: 64, priority: 'P0', landing: '/pricing/crm', status: '重点监控', ranks: { baidu: 5, google: 9, bing: 7 }, delta: { baidu: 2, google: 3, bing: 0 }, history: [13,12,11,12,10,10,9,8,9,7,6,7,5,5], competitor: [3,8,12] },
    { id: 'crm-selection', keyword: 'CRM软件怎么选', cluster: '选型指南', intent: '指南', volume: 2100, difficulty: 48, priority: 'P1', landing: '/guides/crm-selection', status: '增长机会', ranks: { baidu: 14, google: 7, bing: 9 }, delta: { baidu: 6, google: 2, bing: 4 }, history: [31,29,27,25,24,22,20,19,18,17,16,15,14,14], competitor: [9,18,21] },
    { id: 'manufacturing-crm', keyword: '制造业CRM', cluster: '行业方案', intent: '方案', volume: 1600, difficulty: 57, priority: 'P1', landing: '/solutions/manufacturing', status: '重点监控', ranks: { baidu: 11, google: 18, bing: 10 }, delta: { baidu: -2, google: 1, bing: 2 }, history: [16,15,14,13,12,11,10,9,10,10,9,10,11,11], competitor: [7,13,16] },
    { id: 'customer-management', keyword: '客户管理软件', cluster: 'CRM 核心词', intent: '产品', volume: 6800, difficulty: 82, priority: 'P1', landing: '/products/customer-management', status: '排名波动', ranks: { baidu: 22, google: 16, bing: 13 }, delta: { baidu: -7, google: -2, bing: 1 }, history: [12,13,13,14,15,14,16,15,17,18,19,20,21,22], competitor: [4,7,10] },
    { id: 'sales-automation', keyword: '销售自动化工具', cluster: '销售效率', intent: '产品', volume: 1300, difficulty: 45, priority: 'P2', landing: '/features/automation', status: '增长机会', ranks: { baidu: 19, google: 25, bing: 18 }, delta: { baidu: 4, google: 5, bing: 2 }, history: [33,31,29,28,26,25,25,24,23,22,21,20,19,19], competitor: [17,14,28] },
    { id: 'crm-ranking', keyword: 'CRM软件排名', cluster: '对比评测', intent: '对比', volume: 4200, difficulty: 73, priority: 'P1', landing: '/compare/crm-ranking', status: '内容待补', ranks: { baidu: 28, google: 21, bing: 34 }, delta: { baidu: 1, google: -3, bing: 2 }, history: [35,34,33,32,32,31,30,31,30,29,30,29,28,28], competitor: [2,5,8] },
    { id: 'free-crm', keyword: '免费CRM软件', cluster: '价格意图', intent: '价格', volume: 5200, difficulty: 69, priority: 'P2', landing: '', status: '缺少落地页', ranks: { baidu: null, google: 43, bing: 36 }, delta: { baidu: 0, google: 7, bing: 3 }, history: [50,49,48,48,47,46,45,45,44,44,43,43,43,43], competitor: [5,9,13] },
  ];

  function readAdded() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]'); } catch (error) { return []; }
  }
  var keywords = baseKeywords.concat(readAdded());
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, function (char) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char];
    });
  }
  function num(value) { return Number(value || 0).toLocaleString('zh-CN'); }
  function avg(values) {
    var list = values.filter(function (v) { return Number.isFinite(v); });
    return list.length ? Math.round(list.reduce(function (a, b) { return a + b; }, 0) / list.length * 10) / 10 : null;
  }
  function toast(message) {
    var old = document.querySelector('.kw-toast'); if (old) old.remove();
    var el = document.createElement('div'); el.className = 'kw-toast'; el.textContent = message;
    document.body.appendChild(el); requestAnimationFrame(function () { el.classList.add('show'); });
    setTimeout(function () { el.classList.remove('show'); setTimeout(function () { el.remove(); }, 220); }, 1800);
  }
  function hero(kicker, title, copy, actions) {
    return '<section class="kw-hero"><div><div class="kw-kicker">' + esc(kicker) + '</div><h2>' + esc(title) + '</h2><p>' + esc(copy) + '</p></div><div class="kw-actions">' + (actions || '') + '</div></section>';
  }
  function metric(label, value, note, mark, tone) {
    return '<article class="kw-metric" data-mark="' + esc(mark) + '"><span class="label">' + esc(label) + '</span><strong>' + esc(value) + '</strong><small class="' + (tone || '') + '">' + esc(note) + '</small></article>';
  }
  function card(title, sub, body, extra) {
    return '<section class="kw-card"><header class="kw-card-head"><div><h3>' + esc(title) + '</h3>' + (sub ? '<p>' + esc(sub) + '</p>' : '') + '</div>' + (extra ? '<div class="push">' + extra + '</div>' : '') + '</header>' + body + '</section>';
  }
  function priority(value) { return '<span class="kw-priority ' + value.toLowerCase() + '">' + esc(value) + '</span>'; }
  function status(value) {
    var tone = /重点/.test(value) ? 'blue' : /增长/.test(value) ? 'green' : /波动|缺少/.test(value) ? 'red' : /待补/.test(value) ? 'orange' : 'gray';
    return '<span class="kw-pill ' + tone + '">' + esc(value) + '</span>';
  }
  function rankCell(item, engine) {
    var rank = item.ranks[engine]; var delta = item.delta[engine] || 0;
    if (!rank) return '<span class="kw-empty-rank">100+</span>';
    var deltaHtml = delta === 0 ? '<i>—</i>' : '<i class="' + (delta > 0 ? 'up' : 'down') + '">' + (delta > 0 ? '↑' : '↓') + Math.abs(delta) + '</i>';
    return '<span class="kw-rank"><strong>' + rank + '</strong>' + deltaHtml + '</span>';
  }
  function difficulty(item) {
    return '<span class="kw-difficulty"><span><i style="width:' + item.difficulty + '%"></i></span><b>' + item.difficulty + '</b></span>';
  }
  function filtered() {
    return keywords.filter(function (item) {
      var q = state.query.toLowerCase();
      return (!q || (item.keyword + item.cluster + item.landing).toLowerCase().indexOf(q) >= 0) &&
        (!state.priority || item.priority === state.priority) && (!state.intent || item.intent === state.intent);
    });
  }
  function detailUrl(item) { return 'keyword-trend.html?id=' + encodeURIComponent(item.id) + '&engine=' + state.engine; }
  function sparkline(values, color) {
    var w = 92, h = 28, pad = 2; var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var points = values.map(function (v, i) {
      var x = pad + i * ((w - pad * 2) / Math.max(values.length - 1, 1));
      var y = pad + (v - min) / Math.max(max - min, 1) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    return '<svg width="92" height="28" viewBox="0 0 92 28" aria-hidden="true"><polyline points="' + points + '" fill="none" stroke="' + (color || '#2457d6') + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  function lineChart(series, options) {
    options = options || {}; var w = 760, h = 250, left = 38, right = 16, top = 16, bottom = 28;
    var all = []; series.forEach(function (s) { all = all.concat(s.values); });
    var min = options.rank ? 1 : Math.min.apply(null, all); var max = options.rank ? Math.max(50, Math.max.apply(null, all)) : Math.max.apply(null, all);
    function xy(value, index, length) {
      var x = left + index * ((w - left - right) / Math.max(length - 1, 1));
      var ratio = (value - min) / Math.max(max - min, 1);
      var y = options.rank ? top + ratio * (h - top - bottom) : h - bottom - ratio * (h - top - bottom);
      return [x, y];
    }
    var grid = ''; for (var i = 0; i < 5; i += 1) {
      var y = top + i * ((h - top - bottom) / 4); var label = options.rank ? Math.round(min + i * (max - min) / 4) : Math.round(max - i * (max - min) / 4);
      grid += '<line class="gridline" x1="' + left + '" y1="' + y + '" x2="' + (w-right) + '" y2="' + y + '"/><text class="axis-label" x="2" y="' + (y+4) + '">' + label + '</text>';
    }
    var lines = series.map(function (s, si) {
      var pts = s.values.map(function (v, idx) { return xy(v, idx, s.values.length).join(','); }).join(' ');
      var dots = s.values.map(function (v, idx) { var p = xy(v, idx, s.values.length); return '<circle class="point" style="stroke:' + s.color + '" cx="' + p[0] + '" cy="' + p[1] + '" r="3"/>'; }).join('');
      return '<polyline class="line ' + (si === 1 ? 'alt' : si === 2 ? 'third' : '') + '" style="stroke:' + s.color + '" points="' + pts + '"/>' + (series.length === 1 ? dots : '');
    }).join('');
    var labels = ['07/26','07/28','07/30','08/01','08/03','08/05','今天'].map(function (label, idx) {
      return '<text class="axis-label" x="' + (left + idx * ((w-left-right)/6)) + '" y="244" text-anchor="middle">' + label + '</text>';
    }).join('');
    return '<div class="kw-chart"><svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' + grid + lines + labels + '</svg><div class="kw-chart-note">' + series.map(function (s) { return '<span><i style="background:' + s.color + '"></i>' + esc(s.label) + '</span>'; }).join('') + '</div></div>';
  }

  function renderManage(root) {
    var actions = '<button class="kw-btn" data-action="export">⇩ 导出词库</button><button class="kw-btn primary" data-action="add">＋ 添加关键词</button>';
    var content = hero('Keyword library', '关键词管理', '沉淀可持续运营的核心词库，把搜索需求、竞争难度、优先级与承接页面放在同一张资产表里。', actions);
    content += '<div class="kw-metrics">' +
      metric('核心关键词', keywords.length, '其中 5 个进入重点监控', 'K', 'up') +
      metric('月搜索需求', num(keywords.reduce(function (s, i) { return s + i.volume; }, 0)), '百度规划师月均搜索量', 'V') +
      metric('已有承接页', keywords.filter(function (i) { return i.landing; }).length + '/' + keywords.length, '1 个关键词缺少落地页', 'L', 'down') +
      metric('高优先级', keywords.filter(function (i) { return /P0|P1/.test(i.priority); }).length, 'P0–P1 优先投入内容资源', 'P', 'up') + '</div>';
    content += card('关键词资产清单', '搜索量为月均值；难度为 0–100 的综合竞争评分', '<div id="manageTable"></div>',
      '<span id="manageCount" class="kw-pill gray">' + keywords.length + ' 个关键词</span>');
    root.innerHTML = content; renderManageTable();
  }
  function renderManageTable() {
    var host = document.getElementById('manageTable'); if (!host) return; var rows = filtered();
    host.innerHTML = '<div class="kw-card-body"><div class="kw-toolbar"><div class="kw-search"><input class="kw-input" data-filter="query" placeholder="搜索关键词、词簇或落地页" value="' + esc(state.query) + '"></div>' +
      '<select class="kw-select" data-filter="priority"><option value="">全部优先级</option>' + ['P0','P1','P2','P3'].map(function (v) { return '<option ' + (state.priority === v ? 'selected' : '') + '>' + v + '</option>'; }).join('') + '</select>' +
      '<select class="kw-select" data-filter="intent"><option value="">全部意图</option>' + ['产品','价格','方案','指南','对比'].map(function (v) { return '<option ' + (state.intent === v ? 'selected' : '') + '>' + v + '</option>'; }).join('') + '</select><button class="kw-btn ghost" data-action="cluster">词簇视图</button></div></div>' +
      '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>关键词 / 词簇</th><th>搜索意图</th><th>月搜索量</th><th>竞争难度</th><th>优先级</th><th>承接页面</th><th>状态</th><th>操作</th></tr></thead><tbody>' +
      (rows.length ? rows.map(function (item) { return '<tr><td class="keyword-cell"><span class="kw-name"><a href="' + detailUrl(item) + '">' + esc(item.keyword) + '</a></span><small class="kw-sub">' + esc(item.cluster) + '</small></td><td><span class="kw-pill gray">' + esc(item.intent) + '</span></td><td><b>' + num(item.volume) + '</b></td><td>' + difficulty(item) + '</td><td>' + priority(item.priority) + '</td><td><div class="kw-link">' + (item.landing ? esc(item.landing) : '<span class="kw-pill red">待创建</span>') + '</div></td><td>' + status(item.status) + '</td><td><div class="kw-row-actions"><a class="kw-icon-btn" href="' + detailUrl(item) + '" title="查看详情" style="display:grid;place-items:center">↗</a><button class="kw-icon-btn" data-action="edit" data-id="' + item.id + '" title="编辑">✎</button></div></td></tr>'; }).join('') : '<tr><td colspan="8"><div class="kw-empty"><b>没有符合条件的关键词</b>调整筛选条件后再试</div></td></tr>') + '</tbody></table></div>';
    var count = document.getElementById('manageCount'); if (count) count.textContent = rows.length + ' 个关键词'; bindFilters();
  }

  function renderRanking(root) {
    var avgRank = avg(keywords.map(function (i) { return i.ranks[state.engine]; }));
    var top10 = keywords.filter(function (i) { return i.ranks[state.engine] && i.ranks[state.engine] <= 10; }).length;
    var actions = '<button class="kw-btn" data-action="export-ranks">⇩ 导出排名</button><button class="kw-btn primary" data-action="refresh">↻ 更新排名</button>';
    root.innerHTML = hero('Ranking monitor', '排名监控', '按搜索引擎查看自然排名、周期变化与承接页，优先处理排名骤降和进入首页临界区的关键词。', actions) +
      '<div class="kw-metrics">' + metric('监控关键词', keywords.length, '覆盖 5 个核心词簇', 'K') + metric('平均自然排名', avgRank || '—', engines[state.engine].label + ' · 排名越小越好', 'R', 'up') + metric('前 10 名', top10, '首页覆盖率 ' + Math.round(top10 / keywords.length * 100) + '%', '10', 'up') + metric('本周净提升', '+18', '上涨 5 个 · 下跌 2 个', 'Δ', 'up') + '</div>' +
      card('自然排名明细', '最近更新：今天 02:38 · 桌面端 · 全国', '<div id="rankTable"></div>', '<div class="kw-segment" id="engineSegment">' + Object.keys(engines).map(function (key) { return '<button data-engine="' + key + '" class="' + (state.engine === key ? 'active' : '') + '">' + engines[key].label + '</button>'; }).join('') + '</div>');
    renderRankTable();
  }
  function renderRankTable() {
    var host = document.getElementById('rankTable'); if (!host) return; var rows = filtered();
    host.innerHTML = '<div class="kw-card-body"><div class="kw-toolbar"><div class="kw-search"><input class="kw-input" data-filter="query" placeholder="搜索监控关键词" value="' + esc(state.query) + '"></div><select class="kw-select" data-filter="priority"><option value="">全部优先级</option>' + ['P0','P1','P2','P3'].map(function (v) { return '<option ' + (state.priority === v ? 'selected' : '') + '>' + v + '</option>'; }).join('') + '</select><button class="kw-btn ghost" data-action="alerts">仅看异常 2</button></div></div>' +
      '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>关键词</th><th>优先级</th><th>' + engines[state.engine].label + ' 当前排名</th><th>14 天趋势</th><th>月搜索量</th><th>承接页面</th><th>状态</th><th>详情</th></tr></thead><tbody>' + rows.map(function (item) { return '<tr><td class="keyword-cell"><span class="kw-name"><a href="' + detailUrl(item) + '">' + esc(item.keyword) + '</a></span><small class="kw-sub">' + esc(item.cluster) + '</small></td><td>' + priority(item.priority) + '</td><td>' + rankCell(item, state.engine) + '</td><td>' + sparkline(item.history, item.delta[state.engine] >= 0 ? '#248a64' : '#d9544d') + '</td><td>' + num(item.volume) + '</td><td><div class="kw-link">' + (esc(item.landing) || '—') + '</div></td><td>' + status(item.status) + '</td><td><a class="kw-btn small" href="' + detailUrl(item) + '">查看历史 →</a></td></tr>'; }).join('') + '</tbody></table></div>';
    bindFilters(); document.querySelectorAll('[data-engine]').forEach(function (button) { button.onclick = function () { state.engine = button.dataset.engine; renderRanking(document.getElementById('keywordApp')); }; });
  }

  function currentItem() {
    var params = new URLSearchParams(location.search); var id = params.get('id') || 'crm-system';
    state.engine = params.get('engine') || 'baidu'; return keywords.find(function (i) { return i.id === id; }) || keywords[0];
  }
  function renderDetail(root) {
    var item = currentItem(); var actions = '<a class="kw-btn" href="keywords.html">← 返回排名监控</a><button class="kw-btn primary" data-action="task">＋ 创建优化任务</button>';
    var chart = lineChart([{ label: engines[state.engine].label + '自然排名', color: '#2457d6', values: item.history }], { rank: true });
    var historyRows = item.history.slice().reverse().map(function (rank, idx) { var previous = item.history[item.history.length - 2 - idx]; var delta = previous == null ? 0 : previous - rank; return '<tr><td>2026-08-' + String(8-idx).padStart(2,'0') + '</td><td><b>#' + rank + '</b></td><td>' + (delta ? '<span class="' + (delta > 0 ? 'rank-up' : 'rank-down') + '">' + (delta > 0 ? '↑' : '↓') + Math.abs(delta) + '</span>' : '—') + '</td><td><span class="kw-pill blue">自然结果</span></td><td><div class="kw-link">' + (esc(item.landing) || '—') + '</div></td></tr>'; }).slice(0, 8).join('');
    root.innerHTML = hero('Keyword detail', item.keyword, item.cluster + ' · ' + item.intent + '意图 · 当前由“' + (item.landing || '未绑定页面') + '”承接。', actions) +
      '<div class="kw-metrics">' + metric(engines[state.engine].label + '当前排名', item.ranks[state.engine] || '100+', item.delta[state.engine] > 0 ? '本周期提升 ' + item.delta[state.engine] + ' 位' : '本周期下降 ' + Math.abs(item.delta[state.engine]) + ' 位', 'R', item.delta[state.engine] >= 0 ? 'up' : 'down') + metric('月搜索量', num(item.volume), '需求规模稳定', 'V') + metric('竞争难度', item.difficulty + '/100', item.difficulty >= 70 ? '高竞争关键词' : '中等竞争关键词', 'D') + metric('优化优先级', item.priority, item.status, 'P') + '</div>' +
      '<div class="kw-grid-2">' + card('14 天排名曲线', '排名数字越小越好；优化事件会标记在时间轴中', chart, '<div class="kw-segment">' + Object.keys(engines).map(function (key) { return '<button data-detail-engine="' + key + '" class="' + (state.engine === key ? 'active' : '') + '">' + engines[key].label + '</button>'; }).join('') + '</div>') +
      card('关键词诊断', '基于排名、内容与承接页的行动建议', '<div class="kw-card-body"><div class="kw-alert-list"><div class="kw-alert"><span class="mark">01</span><div><h4>补强页面主题覆盖</h4><p>建议补充价格、选型维度与真实使用场景。</p></div><time>P1</time></div><div class="kw-alert"><span class="mark">02</span><div><h4>增加相关内链</h4><p>从 3 篇行业文章链接至当前承接页。</p></div><time>P2</time></div><div class="kw-alert"><span class="mark">03</span><div><h4>观察竞品首页占位</h4><p>竞品 A 当前领先 ' + Math.max(1, (item.ranks[state.engine] || 50) - item.competitor[0]) + ' 位。</p></div><time>P2</time></div></div></div>') + '</div>' +
      card('历史排名记录', '用于定位内容上线与排名变化之间的关联', '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>日期</th><th>自然排名</th><th>较前日</th><th>结果类型</th><th>排名 URL</th></tr></thead><tbody>' + historyRows + '</tbody></table></div>');
    document.querySelectorAll('[data-detail-engine]').forEach(function (button) { button.onclick = function () { var params = new URLSearchParams(location.search); params.set('engine', button.dataset.detailEngine); location.search = params.toString(); }; });
  }

  function renderTrends(root) {
    var actions = '<div class="kw-segment"><button class="active">近 14 天</button><button>近 30 天</button><button>近 90 天</button></div><button class="kw-btn" data-action="report">生成周报</button>';
    var line = lineChart([
      { label: '前 10 名关键词', color: '#2457d6', values: [2,2,3,3,3,4,4,5,5,5,6,6,7,7] },
      { label: '前 20 名关键词', color: '#22a6a1', values: [4,4,4,5,5,5,6,6,6,7,7,7,7,8] },
      { label: '前 50 名关键词', color: '#e78a38', values: [6,6,7,7,7,7,8,8,8,8,8,8,8,8] },
    ]);
    root.innerHTML = hero('Portfolio trends', '趋势总览', '从单词波动上升到词库资产视角，观察首页覆盖、排名分布与本周期净增长。', actions) +
      '<div class="kw-metrics">' + metric('SEO 可见度指数', '62.4', '较上周期 +8.6%', 'S', 'up') + metric('前 10 名覆盖', '7', '新增 2 个首页关键词', '10', 'up') + metric('平均排名', '15.8', '较上周期提升 3.2 位', 'R', 'up') + metric('预估自然流量', '3,480', '月度访问潜力 +14%', 'T', 'up') + '</div>' +
      '<div class="kw-grid-2">' + card('关键词覆盖趋势', '同一批监控词在不同排名区间的累计数量', line) + card('当前排名分布', '共 ' + keywords.length + ' 个监控关键词', '<div class="kw-card-body"><div class="kw-distribution"><div class="kw-dist-row"><span>第 1–3 名</span><div class="track"><i style="width:13%"></i></div><b>1</b></div><div class="kw-dist-row"><span>第 4–10 名</span><div class="track"><i style="width:38%"></i></div><b>3</b></div><div class="kw-dist-row"><span>第 11–20 名</span><div class="track"><i style="width:50%"></i></div><b>4</b></div><div class="kw-dist-row"><span>第 21–50 名</span><div class="track"><i style="width:25%"></i></div><b>2</b></div></div></div>') + '</div>' +
      '<div class="kw-grid-equal" style="margin-top:15px">' + card('本周提升最快', '值得继续投入内容与内链资源', '<div class="kw-card-body"><div class="kw-alert-list"><div class="kw-alert"><span class="mark" style="color:#23775a;background:#eaf7f1">↑6</span><div><h4>CRM软件怎么选</h4><p>#20 → #14 · 新增选型对比表</p></div><time>P1</time></div><div class="kw-alert"><span class="mark" style="color:#23775a;background:#eaf7f1">↑4</span><div><h4>销售自动化工具</h4><p>#23 → #19 · 产品页内容扩充</p></div><time>P2</time></div></div></div>') + card('本周重点关注', '优先排查排名下降与承接缺口', '<div class="kw-card-body"><div class="kw-alert-list"><div class="kw-alert"><span class="mark">↓7</span><div><h4>客户管理软件</h4><p>#15 → #22 · 建议检查竞品更新与页面改动</p></div><time>P1</time></div><div class="kw-alert"><span class="mark">!</span><div><h4>免费CRM软件</h4><p>搜索需求高，但尚未配置承接页面</p></div><time>P2</time></div></div></div>') + '</div>';
  }

  function renderCompetitors(root) {
    var domains = [
      ['G-Snipers','g-snipers.com',62,'我的网站'], ['A','competitor-a.com',74,'竞品 A'], ['B','competitor-b.com',58,'竞品 B'], ['C','competitor-c.com',46,'竞品 C']
    ];
    var actions = '<button class="kw-btn" data-action="competitor">＋ 添加竞品</button><button class="kw-btn primary" data-action="compare">生成对比报告</button>';
    var strip = '<div class="kw-competitor-strip">' + domains.map(function (d, idx) { return '<article class="kw-domain-card ' + (idx === 0 ? 'mine' : '') + '"><div class="domain"><span class="favicon">' + d[0] + '</span><div>' + d[3] + '<small style="display:block;margin-top:2px">' + d[1] + '</small></div></div><strong>' + d[2] + '</strong><small>关键词可见度指数</small></article>'; }).join('') + '</div>';
    var tableRows = keywords.slice(0, 7).map(function (item) { return '<tr><td class="keyword-cell"><span class="kw-name">' + item.keyword + '</span><small class="kw-sub">' + item.cluster + '</small></td><td>' + rankCell(item, 'baidu') + '</td>' + item.competitor.map(function (r, idx) { return '<td><span class="kw-rank"><strong>' + r + '</strong>' + (r < (item.ranks.baidu || 100) ? '<i class="down">领先</i>' : '<i class="up">落后</i>') + '</span></td>'; }).join('') + '<td>' + ((item.ranks.baidu || 100) > item.competitor[0] ? '<span class="kw-pill red">需追赶</span>' : '<span class="kw-pill green">占优</span>') + '</td></tr>'; }).join('');
    root.innerHTML = hero('Competitive landscape', '竞品表现', '在同一批核心关键词下比较自然排名与可见度，找出被竞品占据的高价值搜索入口。', actions) + strip +
      card('核心词排名对标', '百度桌面端 · 全国 · 今日 02:38', '<div class="kw-table-wrap"><table class="kw-table"><thead><tr><th>关键词</th><th>我的网站</th><th>竞品 A</th><th>竞品 B</th><th>竞品 C</th><th>竞争状态</th></tr></thead><tbody>' + tableRows + '</tbody></table></div>', '<div class="kw-segment"><button class="active">排名对比</button><button>内容差距</button></div>') +
      '<div class="kw-grid-equal" style="margin-top:15px">' + card('最大内容缺口', '竞品已有稳定承接，而本站覆盖不足', '<div class="kw-card-body"><div class="kw-alert-list"><div class="kw-alert"><span class="mark">P0</span><div><h4>CRM软件排名</h4><p>竞品 A 位于第 2 名；本站当前第 28 名。</p></div><time>差距 26</time></div><div class="kw-alert"><span class="mark">P1</span><div><h4>免费CRM软件</h4><p>本站缺少承接页，竞品 A 已进入首页。</p></div><time>待建页</time></div></div></div>') + card('建议行动', '把竞品优势转化为可执行任务', '<div class="kw-card-body"><div class="kw-alert-list"><div class="kw-alert"><span class="mark" style="color:#2853b6;background:#edf2ff">01</span><div><h4>建立对比评测内容</h4><p>覆盖功能、价格、适用团队和实施周期。</p></div><time>内容</time></div><div class="kw-alert"><span class="mark" style="color:#2853b6;background:#edf2ff">02</span><div><h4>补齐价格意图落地页</h4><p>承接 8,800 月搜索需求并建立内链入口。</p></div><time>站内</time></div></div></div>') + '</div>';
  }

  function bindFilters() {
    document.querySelectorAll('[data-filter]').forEach(function (input) {
      input.oninput = function () { state[input.dataset.filter] = input.value; page === 'manage' ? renderManageTable() : renderRankTable(); };
      input.onchange = input.oninput;
    });
  }
  function csvDownload(filename, rows) {
    var text = '\ufeff' + rows.map(function (row) { return row.map(function (cell) { return '"' + String(cell == null ? '' : cell).replace(/"/g, '""') + '"'; }).join(','); }).join('\n');
    var blob = new Blob([text], { type: 'text/csv;charset=utf-8' }); var link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = filename; link.click(); setTimeout(function () { URL.revokeObjectURL(link.href); }, 500);
  }
  function openAddModal(item) {
    var modal = document.getElementById('keywordModal'); modal.classList.add('show');
    modal.querySelector('[name="keyword"]').value = item ? item.keyword : '';
    modal.querySelector('[name="volume"]').value = item ? item.volume : '';
    modal.querySelector('[name="intent"]').value = item ? item.intent : '产品';
    modal.querySelector('[name="priority"]').value = item ? item.priority : 'P2';
    modal.querySelector('[name="landing"]').value = item ? item.landing : '';
    modal.dataset.editId = item ? item.id : '';
  }
  function saveModal() {
    var modal = document.getElementById('keywordModal'); var keyword = modal.querySelector('[name="keyword"]').value.trim();
    if (!keyword) { toast('请填写关键词'); return; }
    var entry = {
      id: 'custom-' + Date.now(), keyword: keyword, cluster: '待归类', intent: modal.querySelector('[name="intent"]').value,
      volume: Number(modal.querySelector('[name="volume"]').value || 0), difficulty: 0, priority: modal.querySelector('[name="priority"]').value,
      landing: modal.querySelector('[name="landing"]').value.trim(), status: '待获取排名', ranks: { baidu: null, google: null, bing: null },
      delta: { baidu: 0, google: 0, bing: 0 }, history: [50,50,50,50,50,50,50,50,50,50,50,50,50,50], competitor: [0,0,0]
    };
    var added = readAdded(); var editId = modal.dataset.editId;
    if (editId) {
      var target = keywords.find(function (i) { return i.id === editId; });
      if (target) { target.keyword = entry.keyword; target.volume = entry.volume; target.intent = entry.intent; target.priority = entry.priority; target.landing = entry.landing; }
      var stored = added.find(function (i) { return i.id === editId; }); if (stored) Object.assign(stored, entry, { id: editId });
    } else { added.push(entry); keywords.push(entry); }
    localStorage.setItem(STORE_KEY, JSON.stringify(added)); modal.classList.remove('show'); renderManage(document.getElementById('keywordApp')); toast(editId ? '关键词资料已更新' : '关键词已加入资产库');
  }
  function modalHtml() {
    return '<div class="kw-modal-mask" id="keywordModal"><div class="kw-modal"><header class="kw-modal-head"><h3>添加关键词资产</h3><button class="kw-modal-close" data-action="close-modal">×</button></header><div class="kw-modal-body"><div class="kw-field full"><label>关键词 *</label><input class="kw-input" name="keyword" placeholder="例如：CRM 系统价格"></div><div class="kw-field"><label>月搜索量</label><input class="kw-input" name="volume" type="number" min="0" placeholder="待数据源同步"></div><div class="kw-field"><label>搜索意图</label><select class="kw-select" name="intent" style="width:100%"><option>产品</option><option>价格</option><option>方案</option><option>指南</option><option>对比</option></select></div><div class="kw-field"><label>优先级</label><select class="kw-select" name="priority" style="width:100%"><option>P0</option><option>P1</option><option selected>P2</option><option>P3</option></select></div><div class="kw-field"><label>承接页面</label><input class="kw-input" name="landing" placeholder="/products/example"></div></div><footer class="kw-modal-foot"><button class="kw-btn" data-action="close-modal">取消</button><button class="kw-btn primary" data-action="save-keyword">保存关键词</button></footer></div></div>';
  }

  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-action]'); if (!target) return; var action = target.dataset.action;
    if (action === 'add') openAddModal();
    else if (action === 'edit') openAddModal(keywords.find(function (i) { return i.id === target.dataset.id; }));
    else if (action === 'close-modal') document.getElementById('keywordModal').classList.remove('show');
    else if (action === 'save-keyword') saveModal();
    else if (action === 'export') csvDownload('SEO关键词资产.csv', [['关键词','词簇','意图','月搜索量','难度','优先级','承接页','状态']].concat(keywords.map(function (i) { return [i.keyword,i.cluster,i.intent,i.volume,i.difficulty,i.priority,i.landing,i.status]; })));
    else if (action === 'export-ranks') csvDownload('SEO自然排名.csv', [['关键词','搜索引擎','自然排名','周期变化','承接页']].concat(keywords.map(function (i) { return [i.keyword,engines[state.engine].label,i.ranks[state.engine],i.delta[state.engine],i.landing]; })));
    else if (action === 'refresh') toast('原型演示：已创建排名更新任务');
    else if (action === 'cluster') toast('原型演示：已切换为词簇视角');
    else if (action === 'alerts') toast('已筛出 2 个排名异常关键词');
    else if (action === 'task') toast('优化任务已进入统一待办');
    else if (action === 'report') toast('关键词资产周报已生成');
    else if (action === 'competitor') toast('原型演示：打开竞品配置');
    else if (action === 'compare') toast('竞品对比报告已生成');
  });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') document.querySelectorAll('.kw-modal-mask.show').forEach(function (m) { m.classList.remove('show'); }); });

  var root = document.getElementById('keywordApp'); if (!root) return;
  if (page === 'manage') renderManage(root);
  else if (page === 'ranking') renderRanking(root);
  else if (page === 'detail') renderDetail(root);
  else if (page === 'trends') renderTrends(root);
  else if (page === 'competitors') renderCompetitors(root);
  document.body.insertAdjacentHTML('beforeend', modalHtml());
})();
