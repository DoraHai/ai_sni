(function () {
  var sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  var page = window.location.pathname.split('/').pop() || 'dashboard.html';
  var activePage = page === 'editor.html' ? 'articles.html' : page;

  function item(file, icon, label) {
    var active = activePage === file.split('?')[0];
    return '<a class="nav-item' + (active ? ' active' : '') + '" href="' + file + '"' +
      (active ? ' aria-current="page"' : '') + '><span class="ico">' + icon + '</span> ' + label + '</a>';
  }

  sidebar.innerHTML =
    '<div class="brand"><div class="logo">G</div><div>GEO 工作台<small>生成式引擎获客</small></div></div>' +
    '<div class="nav-group">数据看板</div>' +
    item('dashboard.html', '▦', 'GEO 概览') +
    item('visibility.html', '✦', 'AI 可见度') +
    '<div class="nav-group">智能监测</div>' +
    item('prompts.html', '◌', '提问监控') +
    item('competitors.html', '≋', '竞品分析') +
    item('evaluation.html', '◉', '评价分析') +
    item('sources.html', '▤', '信源分析') +
    '<div class="nav-group">内容与信源</div>' +
    item('articles.html', 'Aa', 'GEO 文章') +
    item('media.html', '⌂', '媒体 / 信源策略') +
    item('channels.html', '⇧', '分发平台') +
    '<div class="nav-group">设置</div>' +
    item('engines.html', '◇', 'AI 引擎管理') +
    '<div class="spacer"></div>' +
    '<a class="nav-item" href="../content/audit.html"><span class="ico">!</span> 诊断中心</a>' +
    '<a class="nav-item" href="../seo/articles.html"><span class="ico">S</span> SEO 内容工作台</a>' +
    '<a class="back-link" href="../hub/dashboard.html">⌂ 全域驾驶舱</a>' +
    '<a class="back-link" style="border-top:none;padding-top:0;" href="../index.html">← 平台门户</a>';
})();
