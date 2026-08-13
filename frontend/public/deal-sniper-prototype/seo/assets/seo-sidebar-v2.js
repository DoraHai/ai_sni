(function () {
  var sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  var page = window.location.pathname.split('/').pop() || 'dashboard.html';
  var params = new URLSearchParams(window.location.search);
  var activePage = page;

  if (page === 'editor.html') {
    activePage = params.get('type') === 'rewrite' ? 'rewrites.html' : 'articles.html';
  }

  if (page === 'answer-editor.html') {
    activePage = 'questions.html';
  }

  if (page === 'keyword-trend.html') {
    activePage = 'keywords.html';
  }

  function item(file, icon, label) {
    var active = activePage === file.split('?')[0];
    return '<a class="nav-item' + (active ? ' active' : '') + '" href="' + file + '"' +
      (active ? ' aria-current="page"' : '') + '><span class="ico">' + icon + '</span> ' + label + '</a>';
  }

  sidebar.innerHTML =
    '<div class="brand"><div class="logo">S</div><div>SEO 工作台<small>搜索引擎获客</small></div></div>' +
    '<div class="nav-group">今日概览</div>' +
    item('dashboard.html', '▦', 'SEO 工作台') +
    '<div class="nav-group">关键词资产</div>' +
    item('manage.html', '⌕', '关键词管理') +
    item('keywords.html?rev=platform-v1', '↗', '排名监控') +
    item('trends.html', '⌁', '趋势总览') +
    item('competitors.html', '≋', '竞品表现') +
    '<div class="nav-group">内容增长</div>' +
    item('articles.html', 'Aa', '原创文章') +
    item('rewrites.html', '↻', '文章改写') +
    item('questions.html', 'Q', '问答运营') +
    item('channels.html?source=seo', '⇧', '分发平台') +
    '<div class="nav-group">站内优化</div>' +
    item('tdk.html', 'T', 'TDK / 站内优化') +
    '<div class="spacer"></div>' +
    '<a class="nav-item" href="../content/audit.html"><span class="ico">!</span> 诊断中心</a>' +
    '<a class="nav-item" href="../geo/dashboard.html"><span class="ico">G</span> GEO 工作台</a>' +
    '<a class="back-link" href="../hub/dashboard.html">⌂ 全域驾驶舱</a>' +
    '<a class="back-link" style="border-top:none;padding-top:0;" href="../index.html">← 平台门户</a>';
})();
