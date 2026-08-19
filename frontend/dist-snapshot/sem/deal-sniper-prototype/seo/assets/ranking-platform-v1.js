(function () {
  var platforms = {
    all: { label: '综合', color: '#1e2330', scope: '综合汇总', top10: '470', top10Delta: '▲ 28', average: '14.2', averageDelta: '▲ 2.1', value: '¥86k', valueDelta: '▲ 9.3%', visibility: '37.5%', visibilityDelta: '▼ 1.2%' },
    baidu: { label: '百度', color: '#2563eb', scope: '百度自然搜索', top10: '342', top10Delta: '▲ 21', average: '12.8', averageDelta: '▲ 2.6', value: '¥54k', valueDelta: '▲ 11.8%', visibility: '41.2%', visibilityDelta: '▲ 2.4%' },
    google: { label: 'Google', color: '#4285f4', scope: 'Google 自然搜索', top10: '186', top10Delta: '▲ 9', average: '18.6', averageDelta: '▲ 1.3', value: '¥28k', valueDelta: '▲ 7.6%', visibility: '24.9%', visibilityDelta: '▲ 1.1%' },
    bing: { label: 'Bing', color: '#0f9f9a', scope: 'Bing 自然搜索', top10: '228', top10Delta: '▲ 18', average: '15.4', averageDelta: '▲ 3.1', value: '¥31k', valueDelta: '▲ 13.2%', visibility: '29.8%', visibilityDelta: '▲ 3.6%' },
    '360': { label: '360', color: '#22a559', scope: '360 搜索', top10: '201', top10Delta: '▲ 7', average: '16.1', averageDelta: '▲ 1.2', value: '¥19k', valueDelta: '▲ 4.8%', visibility: '27.6%', visibilityDelta: '▼ 0.6%' },
    sogou: { label: '搜狗', color: '#f06449', scope: '搜狗搜索', top10: '164', top10Delta: '▼ 4', average: '19.3', averageDelta: '▼ 0.8', value: '¥13k', valueDelta: '▼ 2.1%', visibility: '21.4%', visibilityDelta: '▼ 1.5%' }
  };

  var rows = [
    { keyword: '智能客服系统', intent: '商业意图', landing: '/product/chat', difficulty: 55, volumes: { baidu: 12000, google: 6200, bing: 4800, '360': 5100, sogou: 3600 }, ranks: { baidu: 3, google: 8, bing: 5, '360': 6, sogou: 9 }, changes: { baidu: 8, google: 3, bing: 5, '360': 2, sogou: -1 } },
    { keyword: '在线表单工具', intent: '商业意图', landing: '/forms', difficulty: 32, volumes: { baidu: 8100, google: 4800, bing: 3100, '360': 3500, sogou: 2200 }, ranks: { baidu: 5, google: 11, bing: 7, '360': 8, sogou: 12 }, changes: { baidu: 5, google: 2, bing: 4, '360': 1, sogou: 2 } },
    { keyword: '免费 crm 软件', intent: '高竞争', landing: '/crm', difficulty: 84, volumes: { baidu: 22000, google: 18500, bing: 9200, '360': 11000, sogou: 7600 }, ranks: { baidu: 11, google: 19, bing: 14, '360': 17, sogou: 23 }, changes: { baidu: 4, google: -3, bing: 2, '360': -1, sogou: -5 } },
    { keyword: '企业邮箱注册', intent: '商业意图', landing: '/mail', difficulty: 48, volumes: { baidu: 5400, google: 2900, bing: 2600, '360': 2400, sogou: 1800 }, ranks: { baidu: 18, google: 24, bing: 16, '360': 21, sogou: 27 }, changes: { baidu: -6, google: -2, bing: 1, '360': -4, sogou: -3 } },
    { keyword: '数据分析平台', intent: '商业意图', landing: '/analytics', difficulty: 72, volumes: { baidu: 14800, google: 12100, bing: 7200, '360': 6800, sogou: 4600 }, ranks: { baidu: 24, google: 15, bing: 18, '360': 26, sogou: 31 }, changes: { baidu: -9, google: 4, bing: 3, '360': -5, sogou: -7 } },
    { keyword: '项目管理软件推荐', intent: '决策意图', landing: '/blog/pm-tools', difficulty: 51, volumes: { baidu: 9900, google: 7600, bing: 4400, '360': 3900, sogou: 2800 }, ranks: { baidu: 7, google: 12, bing: 9, '360': 10, sogou: 15 }, changes: { baidu: 2, google: 5, bing: 1, '360': 3, sogou: 2 } },
    { keyword: '如何提升网站收录', intent: '信息意图', landing: '/blog/index', difficulty: 24, volumes: { baidu: 3200, google: 2100, bing: 1800, '360': 1500, sogou: 900 }, ranks: { baidu: 2, google: 6, bing: 4, '360': 5, sogou: 8 }, changes: { baidu: 0, google: 2, bing: 1, '360': 0, sogou: -1 } }
  ];

  var platformKeys = ['baidu', 'google', 'bing', '360', 'sogou'];

  function formatNumber(value) {
    return Number(value).toLocaleString('zh-CN');
  }

  function bestPlatform(row) {
    return platformKeys.reduce(function (best, key) {
      return row.ranks[key] < row.ranks[best] ? key : best;
    }, platformKeys[0]);
  }

  function deltaClass(text) {
    return text.indexOf('▼') === 0 ? 'down' : 'up';
  }

  function sparkline(change, color) {
    var rising = change > 0;
    var falling = change < 0;
    var points = rising ? '0,19 13,17 26,15 40,13 53,10 66,8 80,5' :
      falling ? '0,6 13,8 26,10 40,12 53,15 66,17 80,20' :
      '0,12 13,11 26,12 40,11 53,12 66,11 80,12';
    var stroke = rising ? '#16a34a' : falling ? '#dc2626' : color;
    return '<svg width="80" height="24" viewBox="0 0 80 24" aria-hidden="true"><polyline points="' + points + '" fill="none" stroke="' + stroke + '" stroke-width="2"/></svg>';
  }

  function difficultyBar(value) {
    var tone = value >= 70 ? 'red' : value >= 45 ? 'amber' : 'green';
    return '<div class="row" style="gap:8px"><div class="bar ' + tone + '" style="width:54px"><span style="width:' + value + '%"></span></div>' + value + '</div>';
  }

  function setDelta(id, value) {
    var el = document.getElementById(id);
    el.textContent = value;
    el.className = 'delta ' + deltaClass(value);
  }

  function render(platformKey) {
    var platform = platforms[platformKey];
    document.querySelectorAll('.platform-tab').forEach(function (button) {
      var selected = button.dataset.platform === platformKey;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });

    document.getElementById('platformScopeText').textContent = platform.label + '视图 · 共追踪 1,274 个关键词';
    document.getElementById('platformMeta').innerHTML = '<strong>' + platform.scope + '</strong> · 全国 · 桌面端 · 今日 02:38 更新';
    document.getElementById('statTop10').textContent = platform.top10;
    document.getElementById('statAverage').textContent = platform.average;
    document.getElementById('statValue').textContent = platform.value;
    document.getElementById('statVisibility').textContent = platform.visibility;
    setDelta('deltaTop10', platform.top10Delta);
    setDelta('deltaAverage', platform.averageDelta);
    setDelta('deltaValue', platform.valueDelta);
    setDelta('deltaVisibility', platform.visibilityDelta);
    document.getElementById('rankListTitle').textContent = '关键词列表 · ' + platform.label;
    document.getElementById('rankColumnTitle').textContent = platformKey === 'all' ? '最佳排名' : platform.label + '排名';

    document.getElementById('rankTableBody').innerHTML = rows.map(function (row) {
      var rowPlatformKey = platformKey === 'all' ? bestPlatform(row) : platformKey;
      var rowPlatform = platforms[rowPlatformKey];
      var rank = row.ranks[rowPlatformKey];
      var change = row.changes[rowPlatformKey];
      var changeHtml = change > 0 ? '<span class="rank-up">▲ ' + change + '</span>' :
        change < 0 ? '<span class="rank-down">▼ ' + Math.abs(change) + '</span>' : '<span class="badge gray">—</span>';
      var volume = row.volumes[rowPlatformKey];
      var trendUrl = 'keyword-trend.html?keyword=' + encodeURIComponent(row.keyword) + '&platform=' + encodeURIComponent(rowPlatformKey) + '&rev=content-v9';
      return '<tr>' +
        '<td><div class="kw">' + row.keyword + '</div><span class="tag">' + row.intent + '</span></td>' +
        '<td><span class="platform-chip" style="--chip-color:' + rowPlatform.color + '"><i></i>' + rowPlatform.label + '</span></td>' +
        '<td><div class="rank-cell"><b>' + rank + '</b><small>' + (platformKey === 'all' ? '最佳' : '当前') + '</small></div></td>' +
        '<td>' + changeHtml + '</td>' +
        '<td><a href="' + trendUrl + '" title="查看该关键词历史趋势">' + sparkline(change, rowPlatform.color) + '</a></td>' +
        '<td>' + formatNumber(volume) + '</td>' +
        '<td>' + difficultyBar(row.difficulty) + '</td>' +
        '<td class="muted">' + row.landing + '</td>' +
        '<td><a class="history-drill" href="' + trendUrl + '">历史趋势 →</a></td>' +
      '</tr>';
    }).join('');
  }

  document.querySelectorAll('.platform-tab').forEach(function (button) {
    button.addEventListener('click', function () { render(button.dataset.platform); });
  });

  render('all');
})();
