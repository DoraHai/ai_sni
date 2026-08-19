(function () {
  'use strict';

  var STORAGE_CHANNELS = 'growthEngine.seo.channels.v1';
  var STORAGE_MANUAL_PUBLISHES = 'growthEngine.manualPublishes.v1';
  var STORAGE_MANUAL_MEDIA = 'growthEngine.manualMediaPlatforms.v1';
  var page = document.body.getAttribute('data-content-page') || '';
  var params = new URLSearchParams(window.location.search);
  var selectedPublishIds = new Set();
  var activeManualChannelId = '';
  var autosaveTimer = null;

  var defaultChannels = [
    { id: 'website', name: '官网 CMS', short: '站', color: '#1d4ed8', type: '自有渠道', account: 'example.com / 官网博客', auth: 'API Key', endpoint: 'https://example.com/api/posts', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布', '数据回流'], last: '今天 10:18', review: '内容负责人审核', format: 'HTML' },
    { id: 'wechat', name: '微信公众号', short: '微', color: '#168a52', type: '自有渠道', account: 'Growth Sniper 研究院', auth: 'OAuth 2.0', endpoint: '服务号 · 已认证', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布'], last: '今天 09:42', review: '品牌负责人审核', format: '富文本' },
    { id: 'baijia', name: '百家号', short: '百', color: '#315efb', type: '内容平台', account: 'Growth Sniper 官方', auth: '账号授权', endpoint: '企业蓝 V', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布', '数据回流'], last: '昨天 18:20', review: '平台审核', format: '富文本' },
    { id: 'tieba', name: '百度贴吧', short: '贴', color: '#2932e1', type: '内容平台', account: 'Growth Sniper 品牌吧', auth: '账号授权', endpoint: '企业吧主账号', connected: true, enabled: true, capabilities: ['原创', '文章改写', '数据回流'], last: '昨天 17:40', review: '运营审核', format: '富文本' },
    { id: 'toutiao', name: '今日头条', short: '头', color: '#f04142', type: '内容平台', account: '尚未授权', auth: '账号授权', endpoint: '等待管理员授权', connected: false, enabled: false, capabilities: ['原创', '文章改写', '定时发布'], last: '未同步', review: '平台审核', format: '富文本' },
    { id: 'lofter', name: '网易 LOFTER', short: 'L', color: '#2b706b', type: '内容平台', account: 'Growth Sniper 官方', auth: '账号授权', endpoint: '品牌创作者账号', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布'], last: '昨天 16:48', review: '运营审核', format: '富文本' },
    { id: 'zhihu', name: '知乎', short: '知', color: '#1772f6', type: '内容平台', account: 'Growth Sniper 科技', auth: 'OAuth 2.0', endpoint: '机构号 · 已认证', connected: true, enabled: true, capabilities: ['原创', '文章改写', '数据回流'], last: '昨天 16:05', review: '运营审核', format: 'Markdown' },
    { id: 'sohu', name: '搜狐号', short: '狐', color: '#d64b45', type: '内容平台', account: 'Growth Sniper', auth: '账号授权', endpoint: '企业账号', connected: true, enabled: true, capabilities: ['文章改写', '定时发布'], last: '07-13 14:30', review: '允许自动发布', format: '富文本' },
    { id: 'penguin', name: '企鹅号', short: '企', color: '#1479d7', type: '内容平台', account: 'Growth Sniper 科技', auth: '账号授权', endpoint: '腾讯内容开放平台', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布', '数据回流'], last: '07-14 11:26', review: '平台审核', format: '富文本' },
    { id: 'netease', name: '网易号', short: '易', color: '#d71920', type: '内容平台', account: 'Growth Sniper 增长研究', auth: '账号授权', endpoint: '网易号企业账号', connected: true, enabled: true, capabilities: ['原创', '文章改写', '定时发布', '数据回流'], last: '07-14 10:08', review: '平台审核', format: '富文本' },
    { id: 'media-network', name: '新闻媒体平台', short: '闻', color: '#475569', type: '新闻媒体', account: '媒体资源库 · 18 家', auth: '人工代发', endpoint: '媒体发布资源中心', connected: false, enabled: false, capabilities: ['原创', '媒体投稿', '数据回流'], last: '等待配置媒体套餐', review: '媒体编辑审核', format: '人工适配' },
    { id: 'backlink-network', name: '外链平台', short: '链', color: '#7c3aed', type: '外链渠道', account: '外链资源池 · 42 个站点', auth: '人工代发', endpoint: '外链投放资源库', connected: true, enabled: true, capabilities: ['外链发布', '数据回流'], last: '今天 08:55', review: '内容负责人审核', format: '人工适配' }
  ];

  var defaultManualMediaPlatforms = [
    '腾讯新闻', '网易新闻', '搜狐新闻', '新浪新闻', '新浪财经', '凤凰网', '中国网', '中华网',
    '央广网', '中国经济网', '东方财富', '财经网', '36氪', '钛媒体', '亿欧网', '雷锋网',
    'DoNews', '砍柴网', '站长之家', '中国机器人网'
  ];

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function getChannels() {
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_CHANNELS));
    } catch (error) {
      // Use prototype defaults when local data cannot be parsed.
    }
    if (!Array.isArray(saved) || !saved.length) {
      return defaultChannels.map(function (item) { return Object.assign({}, item, { capabilities: item.capabilities.slice() }); });
    }

    var defaultsById = {};
    defaultChannels.forEach(function (item) { defaultsById[item.id] = item; });
    var savedById = {};
    saved.forEach(function (item) { if (item && item.id) savedById[item.id] = item; });

    var merged = defaultChannels.map(function (item) {
      var existing = savedById[item.id];
      if (!existing) return Object.assign({}, item, { capabilities: item.capabilities.slice() });
      var channel = Object.assign({}, item, existing);
      channel.capabilities = Array.isArray(existing.capabilities) ? existing.capabilities.slice() : item.capabilities.slice();
      if (item.id === 'toutiao' && existing.name === '头条号') channel.name = item.name;
      if (item.id === 'zhihu' && existing.name === '知乎机构号') channel.name = item.name;
      return channel;
    });

    saved.forEach(function (item) {
      if (item && item.id && !defaultsById[item.id]) merged.push(item);
    });
    return merged;
  }

  function saveChannels(channels) {
    try { localStorage.setItem(STORAGE_CHANNELS, JSON.stringify(channels)); } catch (error) {}
  }

  function manualPublishKey(channelId) {
    return 'seo:' + (params.get('id') || 'draft') + ':' + channelId;
  }

  function getManualPublishes() {
    try {
      var records = JSON.parse(localStorage.getItem(STORAGE_MANUAL_PUBLISHES));
      return records && typeof records === 'object' && !Array.isArray(records) ? records : {};
    } catch (error) {
      return {};
    }
  }

  function getManualPublish(channelId) {
    return getManualPublishes()[manualPublishKey(channelId)] || null;
  }

  function getManualMediaPlatforms() {
    var saved = [];
    try { saved = JSON.parse(localStorage.getItem(STORAGE_MANUAL_MEDIA)); } catch (error) {}
    var seen = {};
    return defaultManualMediaPlatforms.concat(Array.isArray(saved) ? saved : []).filter(function (name) {
      var key = String(name || '').trim();
      if (!key || seen[key]) return false;
      seen[key] = true;
      return true;
    });
  }

  function rememberManualMediaPlatform(name) {
    var value = String(name || '').trim();
    if (!value) return;
    var defaults = {};
    defaultManualMediaPlatforms.forEach(function (item) { defaults[item] = true; });
    if (defaults[value]) return;
    var saved = [];
    try { saved = JSON.parse(localStorage.getItem(STORAGE_MANUAL_MEDIA)); } catch (error) {}
    if (!Array.isArray(saved)) saved = [];
    if (!saved.includes(value)) saved.unshift(value);
    try { localStorage.setItem(STORAGE_MANUAL_MEDIA, JSON.stringify(saved.slice(0, 30))); } catch (error) {}
  }

  function renderManualMediaPicker(selectedName) {
    var picker = document.getElementById('manualMediaPicker');
    if (!picker) return;
    var selected = String(selectedName || '').trim();
    picker.innerHTML = getManualMediaPlatforms().map(function (name) {
      var active = name === selected ? ' active' : '';
      return '<button class="manual-media-chip' + active + '" type="button" data-manual-media="' + escapeHtml(name) + '">' + escapeHtml(name) + '</button>';
    }).join('');
  }

  function selectManualMedia(name) {
    var input = document.getElementById('manualMediaPlatform');
    var value = String(name || '').trim();
    if (input) input.value = value;
    renderManualMediaPicker(value);
  }

  function rememberManualMediaFromInput() {
    var input = document.getElementById('manualMediaPlatform');
    var value = input ? input.value.trim() : '';
    if (!value) {
      notify('请输入媒体平台名称');
      if (input) input.focus();
      return;
    }
    rememberManualMediaPlatform(value);
    renderManualMediaPicker(value);
    notify(value + ' 已加入候选');
  }

  function saveManualPublish(channel, url, mediaPlatform) {
    var records = getManualPublishes();
    records[manualPublishKey(channel.id)] = {
      module: 'SEO',
      articleId: params.get('id') || 'draft',
      channelId: channel.id,
      channelName: channel.name,
      mediaPlatform: mediaPlatform || channel.name,
      url: url,
      publishedAt: new Date().toISOString()
    };
    try { localStorage.setItem(STORAGE_MANUAL_PUBLISHES, JSON.stringify(records)); } catch (error) {}
  }

  function removeManualPublish(channelId) {
    var records = getManualPublishes();
    delete records[manualPublishKey(channelId)];
    try { localStorage.setItem(STORAGE_MANUAL_PUBLISHES, JSON.stringify(records)); } catch (error) {}
  }

  function notify(message) {
    if (window.geToast) {
      window.geToast(message);
      return;
    }
    var node = document.createElement('div');
    node.textContent = message;
    node.style.cssText = 'position:fixed;left:50%;bottom:26px;z-index:20000;transform:translateX(-50%);padding:10px 16px;border-radius:7px;background:#202838;color:#fff;font-size:12px;box-shadow:0 10px 28px rgba(0,0,0,.22)';
    document.body.appendChild(node);
    setTimeout(function () { node.remove(); }, 1800);
  }

  function openOverlay(id) {
    var overlay = document.getElementById(id);
    if (overlay) overlay.classList.add('open');
  }

  function closeOverlays() {
    document.querySelectorAll('.seo-overlay.open').forEach(function (overlay) { overlay.classList.remove('open'); });
  }

  function ensureInfoOverlay() {
    var overlay = document.getElementById('infoOverlay');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'seo-overlay';
    overlay.id = 'infoOverlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="seo-dialog">' +
        '<div class="seo-dialog-head"><div><h2 id="infoDialogTitle"></h2><p id="infoDialogSub"></p></div>' +
        '<button class="dialog-close" data-article-action="close-overlay" data-target="seo-content" aria-label="关闭">×</button></div>' +
        '<div class="seo-dialog-body" id="infoDialogBody"></div>' +
        '<div class="seo-dialog-foot" id="infoDialogFoot"></div>' +
      '</div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function showInfoDialog(config) {
    var overlay = ensureInfoOverlay();
    overlay.querySelector('#infoDialogTitle').textContent = config.title || '';
    overlay.querySelector('#infoDialogSub').textContent = config.sub || '';
    overlay.querySelector('#infoDialogBody').innerHTML = config.body || '';
    overlay.querySelector('#infoDialogFoot').innerHTML = config.foot || '<button class="btn" data-article-action="close-overlay" data-target="seo-content">关闭</button>';
    openOverlay('infoOverlay');
  }

  function filterArticleRows(label) {
    var query = ((document.querySelector('[data-article-search]') || {}).value || '').trim().toLowerCase();
    document.querySelectorAll('.article-list-table tbody tr').forEach(function (row) {
      var statusMatch = label === '全部' || row.getAttribute('data-article-status') === label;
      var searchMatch = !query || row.textContent.toLowerCase().indexOf(query) >= 0;
      row.style.display = statusMatch && searchMatch ? '' : 'none';
    });
  }

  function currentArticleFilter() {
    var active = document.querySelector('[data-article-filter].active');
    return active ? active.getAttribute('data-article-filter') : '全部';
  }

  function initArticleLists() {
    var search = document.querySelector('[data-article-search]');
    if (search) search.addEventListener('input', function () { filterArticleRows(currentArticleFilter()); });
  }

  function showTemplates() {
    showInfoDialog({
      title: '选择原创内容模板',
      sub: '模板只规定结构，AI 会结合当前关键词与品牌资料生成独立内容',
      body:
        '<div class="publish-platforms">' +
          '<div class="publish-platform selected" data-template="guide"><i></i><strong>完整选型指南</strong><small>定义、场景、选型维度、FAQ · 2,500 字</small></div>' +
          '<div class="publish-platform" data-template="compare"><i></i><strong>竞品对比评测</strong><small>对比维度、数据表、适用建议 · 2,200 字</small></div>' +
          '<div class="publish-platform" data-template="solution"><i></i><strong>行业解决方案</strong><small>痛点、方案、流程、案例 · 1,800 字</small></div>' +
          '<div class="publish-platform" data-template="howto"><i></i><strong>操作教程</strong><small>步骤、截图位、避坑清单 · 1,500 字</small></div>' +
          '<div class="publish-platform" data-template="opinion"><i></i><strong>行业观点</strong><small>趋势、数据、观点与结论 · 2,000 字</small></div>' +
          '<div class="publish-platform" data-template="faq"><i></i><strong>专题问答</strong><small>覆盖长尾搜索意图 · 1,200 字</small></div>' +
        '</div>',
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="use-template" data-target="seo-content">使用所选模板</button>'
    });
  }

  function showImportSource() {
    showInfoDialog({
      title: '导入待改写原文',
      sub: '可粘贴正文、上传文件，或从历史文章库选择',
      body:
        '<div class="form-grid">' +
          '<div class="form-field full"><label>原文内容 *</label><textarea id="importSourceText" style="min-height:150px;" placeholder="粘贴客户已有文章或参考文章…">智能客服系统可以帮助企业处理重复咨询，通过机器人与人工协同提升服务效率。企业在选型时需要关注部署方式、知识库能力与系统价格。</textarea></div>' +
          '<div class="form-field"><label>原文来源</label><select><option>客户官网旧文</option><option>客户提供文档</option><option>历史文章库</option><option>外部参考资料</option></select></div>' +
          '<div class="form-field"><label>改写强度</label><select><option>深度改写（推荐）</option><option>中度改写</option><option>轻度润色</option></select></div>' +
          '<div class="form-field full"><label>目标关键词</label><input value="智能客服系统价格、客服机器人、客服系统选型"></div>' +
        '</div>',
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="import-confirm" data-target="seo-content">导入并开始改写</button>'
    });
  }

  function showDistributionHistory() {
    showInfoDialog({
      title: '文章分发记录',
      sub: '同一篇内容按平台规则生成了 3 个发布版本',
      body:
        '<table><thead><tr><th>平台</th><th>发布版本</th><th>状态</th><th>发布时间</th><th>结果回流</th></tr></thead><tbody>' +
        '<tr><td class="kw">官网 CMS</td><td>原创首发 V3</td><td><span class="badge green">发布成功</span></td><td>07-12 15:32</td><td>已收录 · 1,284 浏览</td></tr>' +
        '<tr><td class="kw">微信公众号</td><td>摘要与标题适配版</td><td><span class="badge green">发布成功</span></td><td>07-12 16:00</td><td>阅读 826 · 分享 31</td></tr>' +
        '<tr><td class="kw">搜狐号</td><td>文章改写版</td><td><span class="badge green">发布成功</span></td><td>07-12 16:18</td><td>审核通过 · 待收录</td></tr>' +
        '</tbody></table>',
      foot: '<a class="btn" href="channels.html?source=seo">维护平台</a><button class="btn primary" data-article-action="close-overlay" data-target="seo-content">完成</button>'
    });
  }

  function updateWordCount() {
    var editor = document.getElementById('articleEditor');
    var counter = document.getElementById('wordCount');
    if (!editor || !counter) return;
    var count = editor.textContent.replace(/\s/g, '').length;
    counter.textContent = count.toLocaleString('zh-CN') + ' 字';
  }

  function editorStorageKey() {
    return 'growthEngine.seo.editor.' + (params.get('type') || 'original') + '.' + (params.get('id') || 'new');
  }

  function saveEditor(showFeedback) {
    var title = document.getElementById('documentTitle');
    var editor = document.getElementById('articleEditor');
    var state = document.getElementById('saveState');
    if (!title || !editor) return;
    try {
      localStorage.setItem(editorStorageKey(), JSON.stringify({ title: title.value, body: editor.innerHTML, savedAt: Date.now() }));
    } catch (error) {}
    if (state) state.textContent = '刚刚已保存';
    if (showFeedback) notify('文章草稿已保存为新版本');
  }

  function scheduleAutosave() {
    var state = document.getElementById('saveState');
    if (state) state.textContent = '编辑中…';
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(function () { saveEditor(false); }, 700);
    updateWordCount();
  }

  function applyRewriteMode() {
    if (page !== 'editor') return;
    var mode = params.get('type') === 'rewrite' ? 'rewrite' : 'original';
    var sourceSection = document.getElementById('sourceSection');
    var back = document.getElementById('editorBack');
    var heading = document.getElementById('editorHeading');
    var subheading = document.getElementById('editorSubheading');
    var badge = document.getElementById('articleModeBadge');
    var assistant = document.getElementById('assistantModeText');
    var score = document.getElementById('originalityScore');
    var scoreLabel = document.getElementById('originalityLabel');

    if (mode === 'rewrite') {
      document.title = 'SEO · 文章改写编辑';
      if (sourceSection) sourceSection.hidden = false;
      if (back) back.href = 'rewrites.html';
      if (heading) heading.textContent = '文章改写编辑';
      if (subheading) subheading.textContent = '基于客户原文 · 深度改写';
      if (badge) { badge.textContent = '文章改写'; badge.className = 'badge amber'; }
      if (assistant) assistant.textContent = '锁定原文事实，重构表达并植入目标关键词';
      if (score) score.textContent = '82%';
      if (scoreLabel) scoreLabel.textContent = '改写原创度';
    }

    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(editorStorageKey())); } catch (error) {}
    if (saved && !params.get('new')) {
      document.getElementById('documentTitle').value = saved.title;
      document.getElementById('articleEditor').innerHTML = saved.body;
      if (subheading) subheading.textContent += ' · 已恢复上次草稿';
    }
    if (mode === 'rewrite' && params.get('source') === 'imported') {
      try {
        var pendingSource = localStorage.getItem('growthEngine.seo.pendingRewriteSource');
        if (pendingSource && document.getElementById('sourceText')) document.getElementById('sourceText').textContent = pendingSource;
      } catch (error) {}
    }
    updateWordCount();

    ['documentTitle', 'articleEditor', 'sourceText'].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.addEventListener('input', scheduleAutosave);
    });

    if (params.get('publish') === '1') setTimeout(openPublishDialog, 260);
  }

  function runEditorCommand(button) {
    var command = button.getAttribute('data-command');
    var value = button.getAttribute('data-value') || null;
    var editor = document.getElementById('articleEditor');
    if (!editor) return;
    editor.focus();
    try { document.execCommand(command, false, value); } catch (error) {}
    scheduleAutosave();
  }

  function insertLink() {
    var selection = window.getSelection();
    var label = selection && selection.toString() ? selection.toString() : '查看产品详情';
    showInfoDialog({
      title: '插入链接',
      sub: '添加站内链接有助于搜索引擎理解页面关系',
      body: '<div class="form-grid"><div class="form-field full"><label>链接文字</label><input id="linkLabel" value="' + escapeHtml(label) + '"></div><div class="form-field full"><label>目标地址</label><input id="linkUrl" value="https://example.com/product/chat"></div><div class="form-field full"><label class="check-line"><input id="linkNewTab" type="checkbox"> 在新窗口打开</label></div></div>',
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="insert-link-confirm" data-target="seo-content">插入链接</button>'
    });
  }

  function insertLinkConfirm() {
    var editor = document.getElementById('articleEditor');
    var label = document.getElementById('linkLabel').value || '查看详情';
    var url = document.getElementById('linkUrl').value || '#';
    var target = document.getElementById('linkNewTab').checked ? ' target="_blank"' : '';
    if (editor) editor.insertAdjacentHTML('beforeend', '<p><a href="' + escapeHtml(url) + '"' + target + '>' + escapeHtml(label) + '</a></p>');
    closeOverlays();
    scheduleAutosave();
    notify('链接已插入文章末尾');
  }

  function insertImage() {
    showInfoDialog({
      title: '插入文章配图',
      sub: '发布时系统会按平台要求自动裁切封面与正文图片',
      body: '<div class="form-grid"><div class="form-field full"><label>图片地址</label><input id="imageUrl" value="https://images.example.com/customer-service-guide.jpg"></div><div class="form-field"><label>图片说明</label><input id="imageAlt" value="智能客服系统选型流程"></div><div class="form-field"><label>用途</label><select><option>正文配图</option><option>文章封面</option><option>数据图表</option></select></div></div>',
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="insert-image-confirm" data-target="seo-content">插入图片位</button>'
    });
  }

  function insertImageConfirm() {
    var editor = document.getElementById('articleEditor');
    var alt = document.getElementById('imageAlt').value || '文章配图';
    if (editor) editor.insertAdjacentHTML('beforeend', '<figure style="margin:22px 0;padding:26px;text-align:center;border:1px dashed #b8c0cc;background:#f7f8fa;color:#76808e;">图片位 · ' + escapeHtml(alt) + '<figcaption style="margin-top:6px;font-size:11px;">发布时自动生成多平台尺寸</figcaption></figure>');
    closeOverlays();
    scheduleAutosave();
    notify('图片位已插入');
  }

  function runAiAction(action, button) {
    var editor = document.getElementById('articleEditor');
    var title = document.getElementById('documentTitle');
    var message = document.getElementById('assistantMessage');
    if (!editor || !message) return;
    var oldText = button ? button.textContent : '';
    if (button) { button.disabled = true; button.textContent = 'AI 生成中…'; }
    message.className = 'ai-message';
    message.textContent = '正在读取文章结构、目标关键词和品牌资料，生成内容建议…';

    setTimeout(function () {
      if (action === 'ai-generate') {
        editor.insertAdjacentHTML('beforeend', '<h2>五、制造业团队的选型重点</h2><p>制造业企业在选择<mark>智能客服系统</mark>时，还应重点验证设备知识库、经销商协同与售后工单的衔接能力。对于涉及生产数据和客户图纸的场景，私有化部署与权限审计通常比单一的<mark>客服系统价格</mark>更值得优先评估。</p>');
        message.textContent = '已补充制造业案例段落，并自然植入 2 个目标关键词。SEO 友好度预计提升 3 分。';
      } else if (action === 'ai-outline') {
        showInfoDialog({
          title: 'AI 推荐大纲',
          sub: '根据搜索意图与竞品内容缺口生成',
          body: '<ol style="margin:0;padding-left:20px;line-height:2.1;color:#4f5867;"><li>企业为什么需要智能客服系统</li><li>SaaS 与私有化部署对比</li><li>机器人、坐席与知识库能力清单</li><li>客服系统价格与隐性成本</li><li>制造业 / 电商 / 软件行业案例</li><li>选型验证清单与常见问题</li></ol>',
          foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">保留现有结构</button><button class="btn primary" data-article-action="apply-outline" data-target="seo-content">应用此大纲</button>'
        });
        message.textContent = '已生成 6 段式大纲，可预览后应用到正文。';
      } else if (action === 'ai-rewrite') {
        var first = editor.querySelector('p');
        if (first) first.innerHTML = '选择<mark>智能客服系统</mark>并不是简单比较功能数量。企业需要把部署方式、服务规模、数据安全和预算模型放到同一套标准中验证，才能找到真正适配业务流程的方案。';
        message.textContent = '首段已重新表达，核心事实保持不变，句式相似度降低至 18%。';
      } else if (action === 'ai-keywords') {
        editor.innerHTML = editor.innerHTML.replace(/智能客服系统/g, '<mark>智能客服系统</mark>').replace(/<mark><mark>/g, '<mark>').replace(/<\/mark><\/mark>/g, '</mark>');
        message.textContent = '已检查关键词分布：主词 7 次、价格词 3 次、场景词 4 次，密度处于正常区间。';
      } else if (action === 'ai-title') {
        showTitleSuggestions();
        message.textContent = '已生成 5 个标题版本，兼顾主关键词、信息增益与点击意愿。';
      }
      message.className = 'ai-message success';
      if (button) { button.disabled = false; button.textContent = oldText; }
      scheduleAutosave();
    }, 720);
  }

  function showTitleSuggestions() {
    var options = [
      '智能客服系统怎么选？部署、价格与能力的完整指南',
      '2026 智能客服系统选型指南：企业必须验证的 8 项能力',
      '智能客服系统价格怎么算？从坐席到私有化部署一次讲清',
      '企业选择智能客服系统，为什么不能只看机器人准确率？',
      'SaaS 还是私有化？智能客服系统选型与预算对比'
    ];
    showInfoDialog({
      title: 'AI 标题建议',
      sub: '标题均已包含主关键词，长度符合百度与 Google 展示范围',
      body: options.map(function (item, index) {
        return '<label class="radio-line" style="padding:10px;border-bottom:1px solid #eceef2;"><input type="radio" name="title-option" value="' + escapeHtml(item) + '"' + (index === 0 ? ' checked' : '') + '> <span>' + escapeHtml(item) + '</span></label>';
      }).join(''),
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="apply-title" data-target="seo-content">使用所选标题</button>'
    });
  }

  function showAddKeyword() {
    showInfoDialog({
      title: '添加目标关键词',
      sub: '添加后 AI 会重新计算植入次数和内容密度',
      body: '<div class="form-grid"><div class="form-field full"><label>关键词 *</label><input id="newKeyword" value="智能客服软件推荐"></div><div class="form-field"><label>目标次数</label><input id="newKeywordCount" type="number" value="3" min="1" max="20"></div><div class="form-field"><label>搜索意图</label><select><option>商业调研</option><option>产品对比</option><option>信息了解</option><option>采购决策</option></select></div></div>',
      foot: '<button class="btn" data-article-action="close-overlay" data-target="seo-content">取消</button><button class="btn primary" data-article-action="add-keyword-confirm" data-target="seo-content">添加关键词</button>'
    });
  }

  function showPreview() {
    var paper = document.getElementById('previewPaper');
    var title = document.getElementById('documentTitle');
    var editor = document.getElementById('articleEditor');
    if (!paper || !title || !editor) return;
    paper.innerHTML = '<h1>' + escapeHtml(title.value) + '</h1>' + editor.innerHTML;
    openOverlay('previewOverlay');
  }

  function renderPublishPlatforms(preserveSelection) {
    var container = document.getElementById('publishPlatforms');
    if (!container) return;
    var channels = getChannels();
    if (preserveSelection) {
      selectedPublishIds = new Set(channels.filter(function (channel) {
        return selectedPublishIds.has(channel.id);
      }).map(function (channel) { return channel.id; }));
    } else {
      var first = channels.find(function (channel) { return channel.connected && channel.enabled; });
      selectedPublishIds = new Set(first ? [first.id] : []);
    }
    container.innerHTML = channels.map(function (channel) {
      var manual = !channel.connected;
      var paused = channel.connected && !channel.enabled;
      var selected = selectedPublishIds.has(channel.id);
      var manualRecord = manual ? getManualPublish(channel.id) : null;
      var modeClass = manual ? ' manual' + (manualRecord ? ' manual-recorded' : '') : (paused ? ' offline paused' : '');
      var status = manual
        ? '<span class="publish-mode-badge">' + (manualRecord ? '已回填链接' : '手动发布') + '</span>'
        : '';
      var accountLabel = manualRecord && manualRecord.mediaPlatform ? manualRecord.mediaPlatform : channel.account;
      var detail = manual
        ? (manualRecord ? '已保存公开网址，点击可查看或修改' : '未对接：复制内容发布后回填网址')
        : (paused ? '平台已停用，请先到分发平台启用' : '支持：' + channel.capabilities.slice(0, 3).join(' / '));
      return '<div class="publish-platform' + (selected ? ' selected' : '') + modeClass + '" data-publish-platform="' + escapeHtml(channel.id) + '" role="button" tabindex="0">' +
        '<i></i><strong>' + escapeHtml(channel.name) + '</strong>' +
        status +
        '<small>' + escapeHtml(accountLabel) + '</small>' +
        '<small class="publish-platform-detail">' + escapeHtml(detail) + '</small>' +
      '</div>';
    }).join('');
    updatePublishButton();
  }

  function updatePublishButton() {
    var button = document.getElementById('confirmPublishButton');
    if (!button) return;
    var selectedId = Array.from(selectedPublishIds)[0];
    var channel = getChannels().find(function (item) { return item.id === selectedId; });
    button.textContent = channel ? '发布到 ' + channel.name : '发布到已选平台';
    button.disabled = selectedPublishIds.size === 0;
  }

  function openPublishDialog() {
    closeOverlays();
    var selection = document.getElementById('publishSelection');
    var progress = document.getElementById('publishProgress');
    var button = document.getElementById('confirmPublishButton');
    if (selection) selection.style.display = '';
    if (progress) progress.classList.remove('active');
    if (button) { button.dataset.articleAction = 'confirm-publish'; button.style.display = ''; }
    renderPublishPlatforms();
    openOverlay('publishOverlay');
  }

  function closeManualPublishDialog() {
    var overlay = document.getElementById('manualPublishOverlay');
    if (overlay) overlay.classList.remove('open');
    activeManualChannelId = '';
  }

  function openManualPublishDialog(channelId) {
    var channel = getChannels().find(function (item) { return item.id === channelId; });
    if (!channel) return;
    activeManualChannelId = channel.id;
    var record = getManualPublish(channel.id);
    var title = document.getElementById('manualPublishTitle');
    var platform = document.getElementById('manualPublishPlatform');
    var account = document.getElementById('manualPublishAccount');
    var mediaField = document.getElementById('manualMediaField');
    var mediaInput = document.getElementById('manualMediaPlatform');
    var input = document.getElementById('manualPublishUrl');
    var saved = document.getElementById('manualPublishSaved');
    var removeButton = document.getElementById('removeManualPublishButton');
    if (title) title.textContent = '手动发布 · ' + channel.name;
    if (platform) platform.textContent = channel.name;
    if (account) account.textContent = channel.account || '未配置发布账号';
    if (mediaField) mediaField.style.display = channel.id === 'media-network' ? '' : 'none';
    var selectedMedia = record && record.mediaPlatform
      ? record.mediaPlatform
      : (channel.id === 'media-network' ? '' : channel.name);
    if (mediaInput) {
      mediaInput.value = selectedMedia;
    }
    renderManualMediaPicker(selectedMedia);
    if (input) input.value = record ? record.url : '';
    if (saved) {
      saved.style.display = record ? 'block' : 'none';
      saved.textContent = record ? '已回填过发布链接，可在这里更新。' : '';
    }
    if (removeButton) removeButton.style.display = record ? '' : 'none';
    openOverlay('manualPublishOverlay');
    setTimeout(function () { if (input && record) input.select(); }, 60);
  }

  function articlePlainText() {
    var title = document.getElementById('documentTitle');
    var editor = document.getElementById('articleEditor');
    return ((title && title.value ? title.value.trim() + '\n\n' : '') + (editor ? editor.innerText.trim() : '')).trim();
  }

  function fallbackCopy(text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;left:-9999px;top:0;';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (error) {}
    area.remove();
  }

  function copyManualPublishContent(button) {
    var text = articlePlainText();
    if (!text) { notify('当前文章还没有可复制的内容'); return; }
    var complete = function () {
      if (button) {
        button.textContent = '已复制';
        setTimeout(function () { button.textContent = '复制文章内容'; }, 1200);
      }
      notify('文章内容已复制，请前往对应平台发布');
    };
    fallbackCopy(text);
    complete();
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(function () {});
  }

  function saveManualPublishLink() {
    var channel = getChannels().find(function (item) { return item.id === activeManualChannelId; });
    var mediaInput = document.getElementById('manualMediaPlatform');
    var mediaPlatform = mediaInput ? mediaInput.value.trim() : '';
    var input = document.getElementById('manualPublishUrl');
    var value = input ? input.value.trim() : '';
    if (channel && channel.id === 'media-network' && !mediaPlatform) {
      notify('请选择或输入实际发布的新闻媒体平台');
      if (mediaInput) mediaInput.focus();
      return;
    }
    if (!channel || !value) {
      notify('请填写实际发布后的网址链接');
      if (input) input.focus();
      return;
    }
    try {
      var parsed = new URL(value);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('invalid protocol');
    } catch (error) {
      notify('请输入以 http:// 或 https:// 开头的完整网址');
      input.focus();
      return;
    }
    rememberManualMediaPlatform(mediaPlatform);
    saveManualPublish(channel, value, mediaPlatform);
    closeManualPublishDialog();
    renderPublishPlatforms(true);
    notify((mediaPlatform || channel.name) + ' 的发布链接已回填');
  }

  function removeManualPublishLink() {
    var channel = getChannels().find(function (item) { return item.id === activeManualChannelId; });
    if (!channel) return;
    removeManualPublish(channel.id);
    closeManualPublishDialog();
    renderPublishPlatforms(true);
    notify(channel.name + ' 的回填记录已移除');
  }

  function startPublishing() {
    if (!selectedPublishIds.size) return;
    var channels = getChannels().filter(function (channel) { return selectedPublishIds.has(channel.id); });
    if (channels.length === 1 && !channels[0].connected) {
      closeOverlays();
      openManualPublishDialog(channels[0].id);
      return;
    }
    var selection = document.getElementById('publishSelection');
    var progress = document.getElementById('publishProgress');
    var rows = document.getElementById('publishProgressRows');
    var button = document.getElementById('confirmPublishButton');
    if (selection) selection.style.display = 'none';
    if (progress) progress.classList.add('active');
    rows.innerHTML = channels.map(function (channel) {
      return '<div class="publish-progress-row" data-progress-channel="' + escapeHtml(channel.id) + '"><strong>' + escapeHtml(channel.name) + '</strong><div class="bar"><span style="width:8%"></span></div><span>适配中</span></div>';
    }).join('');
    if (button) { button.disabled = true; button.textContent = '正在发布…'; }

    channels.forEach(function (channel, index) {
      setTimeout(function () {
        var row = rows.querySelector('[data-progress-channel="' + channel.id + '"]');
        if (!row) return;
        row.querySelector('.bar span').style.width = '58%';
        row.querySelector('span:last-child').textContent = '提交中';
      }, 420 + index * 180);
      setTimeout(function () {
        var row = rows.querySelector('[data-progress-channel="' + channel.id + '"]');
        if (!row) return;
        row.querySelector('.bar span').style.width = '100%';
        row.querySelector('.bar span').style.background = '#16a34a';
        row.querySelector('span:last-child').textContent = channel.review === '允许自动发布' ? '已发布' : '待审核';
      }, 1050 + index * 260);
    });

    setTimeout(function () {
      if (button) {
        button.disabled = false;
        button.textContent = '完成';
        button.dataset.articleAction = 'finish-publish';
      }
      saveEditor(false);
      notify('文章已提交到 ' + channels.length + ' 个平台');
    }, 1550 + channels.length * 260);
  }

  function renderChannels() {
    var container = document.getElementById('channelGrid');
    if (!container) return;
    var channels = getChannels();
    var activeFilter = (document.querySelector('[data-channel-filter].active') || {}).getAttribute ? document.querySelector('[data-channel-filter].active').getAttribute('data-channel-filter') : '全部';
    var query = ((document.getElementById('channelSearch') || {}).value || '').trim().toLowerCase();
    var visible = channels.filter(function (channel) {
      var filterMatch = activeFilter === '全部' || activeFilter === channel.type || (activeFilter === '未连接' && !channel.connected);
      var queryMatch = !query || (channel.name + channel.account).toLowerCase().indexOf(query) >= 0;
      return filterMatch && queryMatch;
    });

    container.innerHTML = visible.map(function (channel) {
      return '<article class="channel-card" data-channel-card="' + escapeHtml(channel.id) + '">' +
        '<div class="channel-card-head"><span class="channel-logo" style="--channel-color:' + escapeHtml(channel.color) + '">' + escapeHtml(channel.short) + '</span>' +
          '<div class="channel-name"><strong>' + escapeHtml(channel.name) + '</strong><small>' + escapeHtml(channel.type) + '</small></div>' +
          '<span class="connection-state' + (channel.connected ? '' : ' offline') + '">' + (channel.connected ? '已连接' : '未连接') + '</span></div>' +
        '<div class="channel-card-body"><dl class="channel-meta"><dt>发布账号</dt><dd>' + escapeHtml(channel.account) + '</dd><dt>授权方式</dt><dd>' + escapeHtml(channel.auth) + '</dd><dt>最近同步</dt><dd>' + escapeHtml(channel.last) + '</dd></dl>' +
          '<div class="channel-capabilities">' + channel.capabilities.map(function (capability) { return '<span>' + escapeHtml(capability) + '</span>'; }).join('') + '</div>' +
          '<div class="channel-card-actions"><button data-article-action="edit-channel" data-channel-id="' + escapeHtml(channel.id) + '" data-target="seo-content">编辑配置</button>' +
          '<button data-article-action="test-channel" data-channel-id="' + escapeHtml(channel.id) + '" data-target="seo-content">测试连接</button>' +
          '<button class="mini-switch' + (channel.enabled ? ' on' : '') + '" data-article-action="toggle-channel" data-channel-id="' + escapeHtml(channel.id) + '" data-target="seo-content" title="' + (channel.enabled ? '停用平台' : '启用平台') + '"></button></div></div>' +
      '</article>';
    }).join('');

    var count = document.getElementById('connectedCount');
    if (count) count.textContent = channels.filter(function (channel) { return channel.connected; }).length + ' / ' + channels.length;
  }

  function clearChannelForm() {
    var form = document.getElementById('channelForm');
    if (form) {
      form.reset();
      form.dataset.connectionPassed = 'false';
    }
    document.getElementById('channelId').value = '';
    document.getElementById('channelDialogTitle').textContent = '添加分发平台';
    document.getElementById('connectionTestResult').style.display = 'none';
  }

  function openChannelDialog(channelId) {
    clearChannelForm();
    if (channelId) {
      var channel = getChannels().find(function (item) { return item.id === channelId; });
      if (channel) {
        document.getElementById('channelDialogTitle').textContent = '编辑 ' + channel.name;
        document.getElementById('channelId').value = channel.id;
        document.getElementById('channelName').value = channel.name;
        document.getElementById('channelType').value = channel.type;
        document.getElementById('channelAccount').value = channel.account;
        document.getElementById('channelAuth').value = channel.auth;
        document.getElementById('channelEndpoint').value = channel.endpoint;
        document.getElementById('channelReview').value = channel.review;
        document.getElementById('channelFormat').value = channel.format;
        document.querySelectorAll('input[name="capability"]').forEach(function (input) { input.checked = channel.capabilities.indexOf(input.value) >= 0; });
      }
    }
    openOverlay('channelOverlay');
  }

  function saveChannelFromForm() {
    var name = document.getElementById('channelName').value.trim();
    var account = document.getElementById('channelAccount').value.trim();
    if (!name || !account) {
      notify('请填写平台名称和发布账号');
      return;
    }
    var id = document.getElementById('channelId').value;
    var channels = getChannels();
    var current = channels.find(function (channel) { return channel.id === id; });
    var payload = {
      id: id || ('channel-' + Date.now()),
      name: name,
      short: name.slice(0, 1),
      color: current ? current.color : '#475569',
      type: document.getElementById('channelType').value,
      account: account,
      auth: document.getElementById('channelAuth').value,
      endpoint: document.getElementById('channelEndpoint').value || '等待配置接口地址',
      connected: current ? current.connected : document.getElementById('channelForm').dataset.connectionPassed === 'true',
      enabled: current ? current.enabled : document.getElementById('channelForm').dataset.connectionPassed === 'true',
      capabilities: Array.from(document.querySelectorAll('input[name="capability"]:checked')).map(function (input) { return input.value; }),
      last: current ? current.last : '尚未同步',
      review: document.getElementById('channelReview').value,
      format: document.getElementById('channelFormat').value
    };
    if (current) channels[channels.indexOf(current)] = payload;
    else channels.push(payload);
    saveChannels(channels);
    closeOverlays();
    renderChannels();
    notify(current ? '平台配置已更新' : '平台已添加，请测试连接');
  }

  function testChannel(channelId, button) {
    var channels = getChannels();
    var channel = channels.find(function (item) { return item.id === channelId; });
    if (!channel) return;
    var old = button.textContent;
    button.disabled = true;
    button.textContent = '检测中…';
    setTimeout(function () {
      channel.connected = true;
      channel.enabled = true;
      channel.last = '刚刚';
      saveChannels(channels);
      renderChannels();
      notify(channel.name + ' 连接正常，发布权限可用');
      button.disabled = false;
      button.textContent = old;
    }, 760);
  }

  function testChannelForm(button) {
    var result = document.getElementById('connectionTestResult');
    button.disabled = true;
    button.textContent = '正在验证授权…';
    result.style.display = 'block';
    result.className = 'ai-message';
    result.textContent = '正在校验账号、接口地址和内容发布权限…';
    setTimeout(function () {
      result.className = 'ai-message success';
      result.textContent = '连接成功：账号有效，已获得草稿写入、内容发布和状态查询权限。';
      document.getElementById('channelForm').dataset.connectionPassed = 'true';
      button.disabled = false;
      button.textContent = '重新测试';
    }, 850);
  }

  function toggleChannel(channelId) {
    var channels = getChannels();
    var channel = channels.find(function (item) { return item.id === channelId; });
    if (!channel) return;
    if (!channel.connected && !channel.enabled) {
      notify('请先测试连接并完成授权');
      return;
    }
    channel.enabled = !channel.enabled;
    saveChannels(channels);
    renderChannels();
    notify(channel.name + (channel.enabled ? ' 已加入发布列表' : ' 已暂停分发'));
  }

  function refreshChannels(button) {
    var old = button.textContent;
    var channels = getChannels();
    button.disabled = true;
    button.textContent = '正在检查 ' + channels.length + ' 个平台…';
    setTimeout(function () {
      channels.forEach(function (channel) { if (channel.connected) channel.last = '刚刚'; });
      saveChannels(channels);
      renderChannels();
      button.disabled = false;
      button.textContent = old;
      notify('平台授权和发布权限已全部检查');
    }, 900);
  }

  function initChannelPage() {
    if (page !== 'channels') return;
    renderChannels();
    var search = document.getElementById('channelSearch');
    if (search) search.addEventListener('input', renderChannels);
  }

  function handleAction(action, target) {
    if (action === 'templates') showTemplates();
    else if (action === 'use-template') {
      var selectedTemplate = document.querySelector('#infoOverlay [data-template].selected');
      window.location.href = 'editor.html?type=original&new=1&template=' + encodeURIComponent(selectedTemplate ? selectedTemplate.getAttribute('data-template') : 'guide');
    }
    else if (action === 'import-source' || action === 'replace-source') showImportSource();
    else if (action === 'import-confirm') {
      var importedSource = (document.getElementById('importSourceText') || {}).value || '';
      try { localStorage.setItem('growthEngine.seo.pendingRewriteSource', importedSource); } catch (error) {}
      if (page === 'editor') {
        if (document.getElementById('sourceText')) document.getElementById('sourceText').textContent = importedSource;
        closeOverlays();
        scheduleAutosave();
        notify('原文已更新，AI 将以新内容为事实基础');
      } else {
        window.location.href = 'editor.html?type=rewrite&new=1&source=imported';
      }
    }
    else if (action === 'distribution') showDistributionHistory();
    else if (action === 'duplicate') {
      var row = target.closest('tr');
      if (row) {
        var clone = row.cloneNode(true);
        clone.setAttribute('data-article-status', '草稿');
        var title = clone.querySelector('.article-title-cell strong');
        var badge = clone.querySelector('td:nth-child(4) .badge');
        if (title) title.textContent = title.textContent + '（副本）';
        if (badge) { badge.textContent = '草稿'; badge.className = 'badge amber'; }
        row.parentNode.insertBefore(clone, row.parentNode.firstChild);
      }
      notify('已创建文章副本');
    }
    else if (action === 'preview') showPreview();
    else if (action === 'save') saveEditor(true);
    else if (action === 'publish' || action === 'preview-publish') openPublishDialog();
    else if (action === 'confirm-publish') startPublishing();
    else if (action === 'finish-publish') { closeOverlays(); notify('发布任务已进入记录中心'); }
    else if (action === 'manage-channels') window.location.href = 'channels.html?source=seo';
    else if (action === 'copy-manual-content') copyManualPublishContent(target);
    else if (action === 'remember-manual-media') rememberManualMediaFromInput();
    else if (action === 'save-manual-publish') saveManualPublishLink();
    else if (action === 'remove-manual-publish') removeManualPublishLink();
    else if (action === 'close-manual-publish') closeManualPublishDialog();
    else if (action === 'close-overlay') closeOverlays();
    else if (action === 'insert-link') insertLink();
    else if (action === 'insert-link-confirm') insertLinkConfirm();
    else if (action === 'insert-image') insertImage();
    else if (action === 'insert-image-confirm') insertImageConfirm();
    else if (action === 'ai-generate' || action === 'ai-outline' || action === 'ai-rewrite' || action === 'ai-keywords' || action === 'ai-title') runAiAction(action, target);
    else if (action === 'apply-outline') { closeOverlays(); notify('新大纲已应用，原段落内容已保留'); }
    else if (action === 'apply-title') {
      var selected = document.querySelector('input[name="title-option"]:checked');
      if (selected) document.getElementById('documentTitle').value = selected.value;
      closeOverlays();
      scheduleAutosave();
      notify('文章标题已更新');
    }
    else if (action === 'add-keyword') showAddKeyword();
    else if (action === 'add-keyword-confirm') {
      var keyword = document.getElementById('newKeyword').value.trim();
      var count = document.getElementById('newKeywordCount').value;
      if (keyword) {
        var button = document.createElement('button');
        button.className = 'selected';
        button.setAttribute('data-toggle-pick', '');
        button.setAttribute('data-target', 'seo-content');
        button.innerHTML = escapeHtml(keyword) + ' <b>' + escapeHtml(count) + '</b>';
        document.getElementById('editorKeywords').insertBefore(button, document.querySelector('[data-article-action="add-keyword"]'));
      }
      closeOverlays();
      notify('目标关键词已加入检查规则');
    }
    else if (action === 'add-channel') openChannelDialog();
    else if (action === 'edit-channel') openChannelDialog(target.getAttribute('data-channel-id'));
    else if (action === 'save-channel') saveChannelFromForm();
    else if (action === 'test-connection') testChannelForm(target);
    else if (action === 'test-channel') testChannel(target.getAttribute('data-channel-id'), target);
    else if (action === 'toggle-channel') toggleChannel(target.getAttribute('data-channel-id'));
    else if (action === 'refresh-channels') refreshChannels(target);
  }

  document.addEventListener('click', function (event) {
    var overlay = event.target.classList && event.target.classList.contains('seo-overlay') ? event.target : null;
    var target = event.target.closest('[data-article-action], [data-toggle-pick], [data-command], [data-article-filter], [data-channel-filter], [data-publish-platform], [data-manual-media], [data-template]');
    if (!target && !overlay) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    if (overlay) {
      if (overlay.id === 'manualPublishOverlay') closeManualPublishDialog();
      else closeOverlays();
      return;
    }

    if (target.hasAttribute('data-command')) {
      runEditorCommand(target);
      return;
    }
    if (target.hasAttribute('data-toggle-pick')) {
      target.classList.toggle('selected');
      notify(target.textContent.trim() + (target.classList.contains('selected') ? ' 已启用' : ' 已取消'));
      return;
    }
    if (target.hasAttribute('data-article-filter')) {
      document.querySelectorAll('[data-article-filter]').forEach(function (button) { button.classList.remove('active'); });
      target.classList.add('active');
      filterArticleRows(target.getAttribute('data-article-filter'));
      return;
    }
    if (target.hasAttribute('data-channel-filter')) {
      document.querySelectorAll('[data-channel-filter]').forEach(function (button) { button.classList.remove('active'); });
      target.classList.add('active');
      renderChannels();
      return;
    }
    if (target.hasAttribute('data-publish-platform')) {
      var id = target.getAttribute('data-publish-platform');
      if (target.classList.contains('paused')) { notify('该平台已停用，请先到分发平台启用'); return; }
      if (target.classList.contains('offline')) { notify('该平台当前不可发布'); return; }
      selectedPublishIds = new Set([id]);
      document.querySelectorAll('[data-publish-platform]').forEach(function (item) {
        item.classList.toggle('selected', item.getAttribute('data-publish-platform') === id);
      });
      updatePublishButton();
      return;
    }
    if (target.hasAttribute('data-manual-media')) {
      selectManualMedia(target.getAttribute('data-manual-media'));
      return;
    }
    if (target.hasAttribute('data-template')) {
      document.querySelectorAll('[data-template]').forEach(function (item) { item.classList.remove('selected'); });
      target.classList.add('selected');
      return;
    }
    handleAction(target.getAttribute('data-article-action'), target);
  }, true);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      if (document.getElementById('manualPublishOverlay') && document.getElementById('manualPublishOverlay').classList.contains('open')) closeManualPublishDialog();
      else closeOverlays();
    }
    if ((event.key === 'Enter' || event.key === ' ') && event.target && event.target.hasAttribute('data-publish-platform')) {
      event.preventDefault();
      event.target.click();
    }
  });

  initArticleLists();
  applyRewriteMode();
  initChannelPage();
})();
