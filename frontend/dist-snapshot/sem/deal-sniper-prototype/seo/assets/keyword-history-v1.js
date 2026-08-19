(function () {
  'use strict';

  var page = document.body.getAttribute('data-history-page') || '';
  var params = new URLSearchParams(window.location.search);
  var platformKey = params.get('platform') || 'baidu';
  var requestedRange = Number(params.get('range'));
  var rangeDays = [30, 90, 180].indexOf(requestedRange) >= 0 ? requestedRange : 90;
  var selectedKeywords = ['智能客服系统', '数据分析平台', '免费 crm 软件'];
  var chartColors = ['#2563eb', '#0f9f9a', '#dc5d3f', '#7c3aed', '#c88719'];

  var platforms = {
    baidu: { label: '百度', color: '#2563eb' },
    google: { label: 'Google', color: '#4285f4' },
    bing: { label: 'Bing', color: '#0f9f9a' },
    '360': { label: '360', color: '#22a559' },
    sogou: { label: '搜狗', color: '#f06449' }
  };

  var keywordData = [
    { keyword: '智能客服系统', intent: '商业意图', landing: '/product/chat', difficulty: 55, volumes: { baidu: 12000, google: 6200, bing: 4800, '360': 5100, sogou: 3600 }, ranks: { baidu: 3, google: 8, bing: 5, '360': 6, sogou: 9 }, changes: { baidu: 8, google: 3, bing: 5, '360': 2, sogou: -1 } },
    { keyword: '在线表单工具', intent: '商业意图', landing: '/forms', difficulty: 32, volumes: { baidu: 8100, google: 4800, bing: 3100, '360': 3500, sogou: 2200 }, ranks: { baidu: 5, google: 11, bing: 7, '360': 8, sogou: 12 }, changes: { baidu: 5, google: 2, bing: 4, '360': 1, sogou: 2 } },
    { keyword: '免费 crm 软件', intent: '高竞争', landing: '/crm', difficulty: 84, volumes: { baidu: 22000, google: 18500, bing: 9200, '360': 11000, sogou: 7600 }, ranks: { baidu: 11, google: 19, bing: 14, '360': 17, sogou: 23 }, changes: { baidu: 4, google: -3, bing: 2, '360': -1, sogou: -5 } },
    { keyword: '企业邮箱注册', intent: '商业意图', landing: '/mail', difficulty: 48, volumes: { baidu: 5400, google: 2900, bing: 2600, '360': 2400, sogou: 1800 }, ranks: { baidu: 18, google: 24, bing: 16, '360': 21, sogou: 27 }, changes: { baidu: -6, google: -2, bing: 1, '360': -4, sogou: -3 } },
    { keyword: '数据分析平台', intent: '商业意图', landing: '/analytics', difficulty: 72, volumes: { baidu: 14800, google: 12100, bing: 7200, '360': 6800, sogou: 4600 }, ranks: { baidu: 24, google: 15, bing: 18, '360': 26, sogou: 31 }, changes: { baidu: -9, google: 4, bing: 3, '360': -5, sogou: -7 } },
    { keyword: '项目管理软件推荐', intent: '决策意图', landing: '/blog/pm-tools', difficulty: 51, volumes: { baidu: 9900, google: 7600, bing: 4400, '360': 3900, sogou: 2800 }, ranks: { baidu: 7, google: 12, bing: 9, '360': 10, sogou: 15 }, changes: { baidu: 2, google: 5, bing: 1, '360': 3, sogou: 2 } },
    { keyword: '如何提升网站收录', intent: '信息意图', landing: '/blog/index', difficulty: 24, volumes: { baidu: 3200, google: 2100, bing: 1800, '360': 1500, sogou: 900 }, ranks: { baidu: 2, google: 6, bing: 4, '360': 5, sogou: 8 }, changes: { baidu: 0, google: 2, bing: 1, '360': 0, sogou: -1 } }
  ];

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function notify(message) {
    if (window.geToast) {
      window.geToast(message);
      return;
    }
    var toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText = 'position:fixed;left:50%;bottom:26px;z-index:20000;transform:translateX(-50%);padding:10px 16px;border-radius:7px;background:#202838;color:#fff;font-size:12px;box-shadow:0 10px 28px rgba(0,0,0,.22)';
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 1700);
  }

  function hash(text) {
    var value = 0;
    for (var index = 0; index < text.length; index += 1) value = ((value << 5) - value + text.charCodeAt(index)) | 0;
    return Math.abs(value);
  }

  function formatDate(date) {
    return String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
  }

  function fullDate(date) {
    return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
  }

  function findKeyword(name) {
    return keywordData.find(function (item) { return item.keyword.toLowerCase() === String(name || '').toLowerCase(); }) || keywordData[0];
  }

  function buildSeries(item, platform, days, pointCount) {
    var count = pointCount || (days === 30 ? 16 : days === 90 ? 19 : 25);
    var current = item.ranks[platform];
    var change = item.changes[platform];
    var scale = days === 30 ? .72 : days === 90 ? 1 : 1.45;
    var start = Math.max(1, Math.min(48, Math.round(current + change * scale)));
    var seed = hash(item.keyword + platform + days);
    var points = [];
    var endDate = new Date(2026, 6, 14);
    for (var i = 0; i < count; i += 1) {
      var progress = i / (count - 1);
      var base = start + (current - start) * progress;
      var wave = (((seed + i * 13) % 7) - 3) * (i === count - 1 ? 0 : .42);
      var rank = Math.max(1, Math.min(50, Math.round(base + wave)));
      var date = new Date(endDate);
      date.setDate(endDate.getDate() - Math.round(days * (1 - progress)));
      points.push({ rank: rank, date: date, label: formatDate(date) });
    }
    points[points.length - 1].rank = current;
    return points;
  }

  function chartCoordinates(points) {
    var left = 48;
    var right = 944;
    var top = 18;
    var bottom = 262;
    return points.map(function (point, index) {
      return {
        x: left + (right - left) * index / (points.length - 1),
        y: top + (bottom - top) * (point.rank - 1) / 49,
        rank: point.rank,
        date: point.date,
        label: point.label
      };
    });
  }

  function pointsToPath(coords) {
    return coords.map(function (point, index) { return (index ? 'L' : 'M') + point.x.toFixed(1) + ',' + point.y.toFixed(1); }).join(' ');
  }

  function axisMarkup() {
    var labels = [1, 10, 20, 30, 40, 50];
    return labels.map(function (rank) {
      var y = 18 + 244 * (rank - 1) / 49;
      return '<line class="chart-grid" x1="48" y1="' + y.toFixed(1) + '" x2="944" y2="' + y.toFixed(1) + '"></line><text class="chart-axis-label" x="8" y="' + (y + 3).toFixed(1) + '">#' + rank + '</text>';
    }).join('');
  }

  function xAxisMarkup(points) {
    var indices = [0, Math.round((points.length - 1) * .25), Math.round((points.length - 1) * .5), Math.round((points.length - 1) * .75), points.length - 1];
    return indices.map(function (index) {
      var x = 48 + 896 * index / (points.length - 1);
      return '<text class="chart-axis-label" x="' + x.toFixed(1) + '" y="286" text-anchor="middle">' + points[index].label + '</text>';
    }).join('');
  }

  function bindTooltips(svg, wrap, tooltip) {
    if (!svg || !wrap || !tooltip) return;
    svg.querySelectorAll('.chart-point').forEach(function (point) {
      point.addEventListener('mouseenter', function (event) {
        var rect = wrap.getBoundingClientRect();
        tooltip.innerHTML = '<b>' + escapeHtml(point.getAttribute('data-keyword') || '') + '</b><span>' + escapeHtml(point.getAttribute('data-date')) + ' · 排名 #' + escapeHtml(point.getAttribute('data-rank')) + '</span>';
        tooltip.style.left = Math.min(rect.width - 150, Math.max(8, event.clientX - rect.left + 10)) + 'px';
        tooltip.style.top = Math.max(8, event.clientY - rect.top - 52) + 'px';
        tooltip.classList.add('show');
      });
      point.addEventListener('mouseleave', function () { tooltip.classList.remove('show'); });
    });
  }

  function miniTrend(item, platform) {
    var series = buildSeries(item, platform, 30, 8);
    var min = Math.min.apply(null, series.map(function (point) { return point.rank; }));
    var max = Math.max.apply(null, series.map(function (point) { return point.rank; }));
    var coords = series.map(function (point, index) {
      var x = 2 + index * 72 / (series.length - 1);
      var y = max === min ? 12 : 3 + (point.rank - min) * 18 / (max - min);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var color = item.changes[platform] >= 0 ? '#16a34a' : '#dc2626';
    return '<svg class="mini-trend" viewBox="0 0 76 24"><polyline points="' + coords + '" fill="none" stroke="' + color + '" stroke-width="2"></polyline></svg>';
  }

  function detailUrl(item, platform) {
    return 'keyword-trend.html?keyword=' + encodeURIComponent(item.keyword) + '&platform=' + encodeURIComponent(platform) + '&rev=content-v9';
  }

  function updateSegmentState(attribute, value) {
    document.querySelectorAll('[' + attribute + ']').forEach(function (button) {
      button.classList.toggle('active', button.getAttribute(attribute) === String(value));
    });
  }

  function syncHistoryUrl() {
    var url = new URL(window.location.href);
    url.searchParams.set('platform', platformKey);
    url.searchParams.set('range', rangeDays);
    window.history.replaceState(null, '', url.toString());
  }

  function renderOverviewChart() {
    var svg = document.getElementById('overviewChart');
    if (!svg) return;
    var selected = selectedKeywords.map(findKeyword);
    var markup = axisMarkup();
    var firstSeries = buildSeries(selected[0], platformKey, rangeDays);
    markup += xAxisMarkup(firstSeries);
    selected.forEach(function (item, seriesIndex) {
      var points = buildSeries(item, platformKey, rangeDays);
      var coords = chartCoordinates(points);
      var color = chartColors[seriesIndex];
      markup += '<path class="chart-line" d="' + pointsToPath(coords) + '" stroke="' + color + '"></path>';
      coords.forEach(function (point, pointIndex) {
        if (pointIndex % 4 !== 0 && pointIndex !== coords.length - 1) return;
        markup += '<circle class="chart-point" cx="' + point.x.toFixed(1) + '" cy="' + point.y.toFixed(1) + '" r="3.8" fill="' + color + '" data-keyword="' + escapeHtml(item.keyword) + '" data-date="' + escapeHtml(point.label) + '" data-rank="' + point.rank + '"></circle>';
      });
    });
    svg.innerHTML = markup;
    document.getElementById('overviewLegend').innerHTML = selected.map(function (item, index) { return '<span><i style="background:' + chartColors[index] + '"></i>' + escapeHtml(item.keyword) + '</span>'; }).join('');
    document.getElementById('selectionCount').textContent = '已选 ' + selected.length + ' / 5';
    document.getElementById('overviewChartMeta').textContent = platforms[platformKey].label + ' · 最近 ' + rangeDays + ' 天 · 排名数字越小越好';
    bindTooltips(svg, document.getElementById('overviewChartWrap'), document.getElementById('overviewTooltip'));

    var currentRanks = selected.map(function (item) { return item.ranks[platformKey]; });
    var average = currentRanks.reduce(function (sum, value) { return sum + value; }, 0) / currentRanks.length;
    var top10 = currentRanks.filter(function (rank) { return rank <= 10; }).length;
    var best = selected.slice().sort(function (a, b) { return b.changes[platformKey] - a.changes[platformKey]; })[0];
    var anomalies = selected.filter(function (item) { return item.changes[platformKey] <= -4; }).length;
    document.getElementById('overviewAverage').textContent = average.toFixed(1);
    document.getElementById('overviewAverageDelta').textContent = '较周期初' + (selected.reduce(function (sum, item) { return sum + item.changes[platformKey]; }, 0) >= 0 ? '提升' : '下降') + ' 2.1 位';
    document.getElementById('overviewTop10').textContent = top10 + ' / ' + selected.length;
    document.getElementById('overviewBestGain').textContent = (best.changes[platformKey] >= 0 ? '+' : '') + best.changes[platformKey];
    document.getElementById('overviewBestKeyword').textContent = best.keyword;
    document.getElementById('overviewAnomaly').textContent = anomalies;
  }

  function renderOverviewRows() {
    var body = document.getElementById('overviewKeywordRows');
    if (!body) return;
    body.innerHTML = keywordData.map(function (item) {
      var rank = item.ranks[platformKey];
      var change = item.changes[platformKey];
      var changeHtml = change > 0 ? '<span class="rank-up">▲ ' + change + '</span>' : change < 0 ? '<span class="rank-down">▼ ' + Math.abs(change) + '</span>' : '<span class="badge gray">—</span>';
      var volatility = 2 + hash(item.keyword + platformKey) % 9;
      return '<tr><td class="trend-keyword"><strong>' + escapeHtml(item.keyword) + '</strong><small>' + escapeHtml(item.intent) + ' · ' + platforms[platformKey].label + '</small></td><td><b>#' + rank + '</b></td><td>' + changeHtml + '</td><td>' + volatility + ' 位</td><td>' + miniTrend(item, platformKey) + '</td><td class="muted">' + escapeHtml(item.landing) + '</td><td><a class="drill-link" href="' + detailUrl(item, platformKey) + '">查看历史 →</a></td></tr>';
    }).join('');
    filterOverviewRows();
  }

  function filterOverviewRows() {
    var input = document.getElementById('trendKeywordSearch');
    var query = input ? input.value.trim().toLowerCase() : '';
    document.querySelectorAll('#overviewKeywordRows tr').forEach(function (row) { row.style.display = !query || row.textContent.toLowerCase().indexOf(query) >= 0 ? '' : 'none'; });
  }

  function renderKeywordPicker() {
    var grid = document.getElementById('keywordPickerGrid');
    if (!grid) return;
    grid.innerHTML = keywordData.map(function (item) {
      var checked = selectedKeywords.indexOf(item.keyword) >= 0;
      return '<label class="keyword-picker-item"><input type="checkbox" data-picker-keyword="' + escapeHtml(item.keyword) + '"' + (checked ? ' checked' : '') + '><span><strong>' + escapeHtml(item.keyword) + '</strong><small>' + platforms[platformKey].label + '当前 #' + item.ranks[platformKey] + ' · ' + escapeHtml(item.intent) + '</small></span></label>';
    }).join('');
    grid.querySelectorAll('[data-picker-keyword]').forEach(function (input) {
      input.addEventListener('change', function () {
        var checked = grid.querySelectorAll('[data-picker-keyword]:checked');
        if (checked.length > 5) {
          input.checked = false;
          notify('一张图最多对比 5 个关键词');
        }
        if (grid.querySelectorAll('[data-picker-keyword]:checked').length === 0) {
          input.checked = true;
          notify('至少保留 1 个对比关键词');
        }
      });
    });
  }

  function renderOverview() {
    updateSegmentState('data-history-platform', platformKey);
    updateSegmentState('data-history-range', rangeDays);
    renderOverviewChart();
    renderOverviewRows();
  }

  function detailItem() {
    return findKeyword(params.get('keyword') || '智能客服系统');
  }

  function detailEvents(item, series) {
    var eventDefinitions = [
      { index: Math.max(2, Math.round(series.length * .28)), title: '更新落地页核心内容', detail: '补充选型维度、价格说明与 FAQ', color: '#2563eb' },
      { index: Math.max(4, Math.round(series.length * .57)), title: '百度完成重新收录', detail: '页面快照显示标题与摘要已更新', color: '#0f9f9a' },
      { index: Math.max(6, Math.round(series.length * .78)), title: '行业媒体发布专题稿', detail: '新增 3 个相关信源与品牌提及', color: '#d18b17' }
    ];
    return eventDefinitions.map(function (event) {
      var point = series[Math.min(series.length - 1, event.index)];
      return { index: event.index, date: point.date, label: point.label, rank: point.rank, title: event.title, detail: event.detail, color: event.color };
    });
  }

  function renderDetailChart(item, series) {
    var svg = document.getElementById('detailChart');
    var coords = chartCoordinates(series);
    var color = platforms[platformKey].color;
    var events = detailEvents(item, series);
    var path = pointsToPath(coords);
    var areaPath = path + ' L' + coords[coords.length - 1].x.toFixed(1) + ',262 L' + coords[0].x.toFixed(1) + ',262 Z';
    var markup = '<defs><linearGradient id="detailArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + color + '" stop-opacity=".38"></stop><stop offset="1" stop-color="' + color + '" stop-opacity="0"></stop></linearGradient></defs>' + axisMarkup() + xAxisMarkup(series);
    markup += '<path class="chart-area" d="' + areaPath + '" fill="url(#detailArea)"></path><path class="chart-line" d="' + path + '" stroke="' + color + '"></path>';
    events.forEach(function (event) {
      var coord = coords[Math.min(coords.length - 1, event.index)];
      markup += '<line class="chart-event-line" x1="' + coord.x.toFixed(1) + '" y1="18" x2="' + coord.x.toFixed(1) + '" y2="262"></line><circle class="chart-event-dot" cx="' + coord.x.toFixed(1) + '" cy="' + coord.y.toFixed(1) + '" r="5"></circle>';
    });
    coords.forEach(function (point, index) {
      if (index % 2 !== 0 && index !== coords.length - 1) return;
      markup += '<circle class="chart-point" cx="' + point.x.toFixed(1) + '" cy="' + point.y.toFixed(1) + '" r="3.7" fill="' + color + '" data-keyword="' + escapeHtml(item.keyword) + '" data-date="' + escapeHtml(point.label) + '" data-rank="' + point.rank + '"></circle>';
    });
    svg.innerHTML = markup;
    bindTooltips(svg, document.getElementById('detailChartWrap'), document.getElementById('detailTooltip'));
    document.getElementById('detailEvents').innerHTML = events.map(function (event) { return '<li style="--event-color:' + event.color + '"><strong>' + escapeHtml(event.title) + '</strong><span>' + fullDate(event.date) + ' · 当日排名 #' + event.rank + ' · ' + escapeHtml(event.detail) + '</span></li>'; }).join('');
  }

  function renderCompetitors(item) {
    var current = item.ranks[platformKey];
    var competitors = [
      { name: '我方 · Growth Sniper', rank: current, color: platforms[platformKey].color },
      { name: '竞品 A', rank: Math.max(1, current - 1), color: '#ef6a53' },
      { name: '竞品 B', rank: Math.min(45, current + 4), color: '#8b95a3' },
      { name: '行业媒体页', rank: Math.min(48, current + 7), color: '#c88719' }
    ];
    document.getElementById('competitorBars').innerHTML = competitors.map(function (competitor) {
      var width = Math.max(8, 100 - competitor.rank * 1.8);
      return '<div class="competitor-row"><span>' + escapeHtml(competitor.name) + '</span><div class="competitor-track"><i style="width:' + width + '%;--bar-color:' + competitor.color + '"></i></div><b>#' + competitor.rank + '</b></div>';
    }).join('');
  }

  function renderSnapshots(item, series) {
    var rows = [];
    var reversed = series.slice().reverse();
    var step = Math.max(1, Math.floor(reversed.length / 10));
    for (var index = 0; index < reversed.length && rows.length < 10; index += step) rows.push(reversed[index]);
    document.getElementById('detailSnapshotRows').innerHTML = rows.map(function (point, rowIndex) {
      var previous = rows[rowIndex + 1];
      var delta = previous ? previous.rank - point.rank : 0;
      var deltaHtml = delta > 0 ? '<span class="rank-up">▲ ' + delta + '</span>' : delta < 0 ? '<span class="rank-down">▼ ' + Math.abs(delta) + '</span>' : '<span class="badge gray">—</span>';
      var feature = point.rank <= 3 ? '站点链接' : point.rank <= 10 ? '精选摘要' : rowIndex % 3 === 0 ? '相关问题' : '普通结果';
      return '<tr><td>' + fullDate(point.date) + '</td><td><b>#' + point.rank + '</b></td><td>' + deltaHtml + '</td><td class="muted">' + escapeHtml(item.landing) + '</td><td><span class="tag">' + feature + '</span></td><td><span class="badge green">已收录</span></td><td>自建排名爬虫</td></tr>';
    }).join('');
    document.getElementById('snapshotCount').textContent = '共 ' + rangeDays + ' 条';
  }

  function renderDetail() {
    var item = detailItem();
    if (!platforms[platformKey]) platformKey = 'baidu';
    var series = buildSeries(item, platformKey, rangeDays);
    var current = series[series.length - 1].rank;
    var start = series[0].rank;
    var change = start - current;
    var best = series.reduce(function (value, point) { return point.rank < value.rank ? point : value; }, series[0]);
    var topCount = series.filter(function (point) { return point.rank <= 10; }).length;
    var topDays = Math.round(rangeDays * topCount / series.length);
    var platform = platforms[platformKey];

    document.title = 'SEO · ' + item.keyword + '历史趋势';
    document.getElementById('detailKeywordName').textContent = item.keyword;
    document.getElementById('detailBreadcrumbKeyword').textContent = item.keyword;
    document.getElementById('detailKeywordSub').textContent = '关键词历史趋势 · ' + platform.label + ' · 全国 · 桌面端';
    document.getElementById('detailSyncText').textContent = platform.label + '排名 · 今日 02:38 已更新';
    document.getElementById('detailCurrentRank').textContent = current;
    document.getElementById('detailCurrentDelta').textContent = '较周期初' + (change >= 0 ? '提升 ' + change : '下降 ' + Math.abs(change)) + ' 位';
    document.getElementById('detailCurrentDelta').className = change >= 0 ? '' : 'down';
    document.getElementById('detailCurrentPlatform').textContent = platform.label + ' · 桌面端';
    document.getElementById('detailBestRank').textContent = best.rank;
    document.getElementById('detailBestDate').textContent = best.label + ' 达到';
    document.getElementById('detailTopDays').textContent = topDays;
    document.getElementById('detailTopRate').textContent = '覆盖 ' + Math.round(topDays / rangeDays * 100) + '% 天数';
    document.getElementById('detailVolume').textContent = Number(item.volumes[platformKey]).toLocaleString('zh-CN');
    document.getElementById('detailChartTitle').textContent = item.keyword + ' · 排名变化';
    document.getElementById('detailChartMeta').textContent = platform.label + ' · 最近 ' + rangeDays + ' 天 · 数字越小排名越靠前';
    document.getElementById('detailLegendColor').style.background = platform.color;
    document.getElementById('detailLegendText').textContent = platform.label + '自然排名';
    document.getElementById('competitorMeta').textContent = platform.label + '前 10 名页面对比';
    document.getElementById('detailLandingPage').textContent = item.landing;
    updateSegmentState('data-history-platform', platformKey);
    updateSegmentState('data-history-range', rangeDays);
    renderDetailChart(item, series);
    renderCompetitors(item);
    renderSnapshots(item, series);
  }

  function openOverlay(id) {
    var overlay = document.getElementById(id);
    if (overlay) overlay.classList.add('open');
  }

  function closeOverlays() {
    document.querySelectorAll('.history-overlay.open').forEach(function (overlay) { overlay.classList.remove('open'); });
  }

  function downloadCsv(filename, rows) {
    var content = '\ufeff' + rows.map(function (row) { return row.map(function (cell) { return '"' + String(cell).replace(/"/g, '""') + '"'; }).join(','); }).join('\n');
    var blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 200);
  }

  function exportOverview() {
    var rows = [['关键词', '平台', '当前排名', '周期变化', '落地页']].concat(keywordData.map(function (item) { return [item.keyword, platforms[platformKey].label, item.ranks[platformKey], item.changes[platformKey], item.landing]; }));
    downloadCsv('SEO关键词趋势总览.csv', rows);
    notify('趋势总览已导出');
  }

  function exportDetail() {
    var item = detailItem();
    var series = buildSeries(item, platformKey, rangeDays);
    var rows = [['日期', '关键词', '搜索引擎', '自然排名', '落地页']].concat(series.map(function (point) { return [fullDate(point.date), item.keyword, platforms[platformKey].label, point.rank, item.landing]; }));
    downloadCsv(item.keyword + '-历史排名.csv', rows);
    notify('关键词历史数据已导出');
  }

  function handleAction(action) {
    if (action === 'choose-keywords') {
      renderKeywordPicker();
      openOverlay('keywordPickerOverlay');
    } else if (action === 'apply-keywords') {
      selectedKeywords = Array.from(document.querySelectorAll('[data-picker-keyword]:checked')).map(function (input) { return input.getAttribute('data-picker-keyword'); });
      closeOverlays();
      renderOverviewChart();
      notify('对比关键词已更新');
    } else if (action === 'close-overlay') closeOverlays();
    else if (action === 'export') exportOverview();
    else if (action === 'export-detail') exportDetail();
    else if (action === 'add-annotation') {
      var date = document.getElementById('annotationDate');
      if (date) date.value = '2026-07-14';
      openOverlay('annotationOverlay');
    } else if (action === 'save-annotation') {
      var list = document.getElementById('detailEvents');
      var dateValue = document.getElementById('annotationDate').value || '2026-07-14';
      var typeValue = document.getElementById('annotationType').value;
      var textValue = document.getElementById('annotationText').value.trim();
      var item = document.createElement('li');
      item.style.setProperty('--event-color', '#7c3aed');
      item.innerHTML = '<strong>' + escapeHtml(typeValue) + '</strong><span>' + escapeHtml(dateValue) + ' · 人工备注 · ' + escapeHtml(textValue) + '</span>';
      list.insertBefore(item, list.firstChild);
      closeOverlays();
      notify('趋势备注已保存');
    }
  }

  document.addEventListener('click', function (event) {
    var overlay = event.target.classList && event.target.classList.contains('history-overlay') ? event.target : null;
    var target = event.target.closest('[data-history-action], [data-history-platform], [data-history-range]');
    if (!target && !overlay) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (overlay) { closeOverlays(); return; }
    if (target.hasAttribute('data-history-platform')) {
      platformKey = target.getAttribute('data-history-platform');
      syncHistoryUrl();
      if (page === 'overview') renderOverview(); else renderDetail();
      return;
    }
    if (target.hasAttribute('data-history-range')) {
      rangeDays = Number(target.getAttribute('data-history-range')) || 90;
      syncHistoryUrl();
      if (page === 'overview') renderOverview(); else renderDetail();
      return;
    }
    handleAction(target.getAttribute('data-history-action'));
  }, true);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeOverlays();
  });

  if (page === 'overview') {
    var search = document.getElementById('trendKeywordSearch');
    if (search) search.addEventListener('input', filterOverviewRows);
    renderOverview();
  } else if (page === 'detail') {
    renderDetail();
  }
})();
