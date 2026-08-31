(function () {
  'use strict';

  var page = document.body.getAttribute('data-geo-page') || '';
  var params = new URLSearchParams(window.location.search);
  var CHANNEL_STORAGE = 'growthEngine.seo.channels.v1';
  var MANUAL_PUBLISH_STORAGE = 'growthEngine.manualPublishes.v1';
  var MANUAL_MEDIA_STORAGE = 'growthEngine.manualMediaPlatforms.v1';
  var IMPORT_DRAFT_STORAGE = 'growthEngine.geo.importDraft.v1';
  var isImportedArticle = params.get('import') === '1';
  var pendingImportDraft = null;
  var selectedPlatforms = new Set();
  var activeManualPlatformId = '';
  var autosaveTimer = null;

  var fallbackChannels = [
    { id: 'website', name: '官网 CMS', account: 'example.com / 官网博客', connected: true, enabled: true, review: '内容负责人审核' },
    { id: 'wechat', name: '微信公众号', account: 'SearchPilot 研究院', connected: true, enabled: true, review: '品牌负责人审核' },
    { id: 'baijia', name: '百家号', account: 'SearchPilot 官方', connected: true, enabled: true, review: '平台审核' },
    { id: 'tieba', name: '百度贴吧', account: 'SearchPilot 品牌吧', connected: true, enabled: true, review: '运营审核' },
    { id: 'toutiao', name: '今日头条', account: '尚未授权', connected: false, enabled: false, review: '平台审核' },
    { id: 'lofter', name: '网易 LOFTER', account: 'SearchPilot 官方', connected: true, enabled: true, review: '运营审核' },
    { id: 'zhihu', name: '知乎', account: 'SearchPilot 科技', connected: true, enabled: true, review: '运营审核' },
    { id: 'sohu', name: '搜狐号', account: '智能搜索增长平台', connected: true, enabled: true, review: '允许自动发布' },
    { id: 'penguin', name: '企鹅号', account: 'SearchPilot 科技', connected: true, enabled: true, review: '平台审核' },
    { id: 'netease', name: '网易号', account: 'SearchPilot 增长研究', connected: true, enabled: true, review: '平台审核' },
    { id: 'media-network', name: '新闻媒体平台', account: '媒体资源库 · 18 家', connected: false, enabled: false, review: '媒体编辑审核' },
    { id: 'backlink-network', name: '外链平台', account: '外链资源池 · 42 个站点', connected: true, enabled: true, review: '内容负责人审核' }
  ];

  var defaultManualMediaPlatforms = [
    '腾讯新闻', '网易新闻', '搜狐新闻', '新浪新闻', '新浪财经', '凤凰网', '中国网', '中华网',
    '央广网', '中国经济网', '东方财富', '财经网', '36氪', '钛媒体', '亿欧网', '雷锋网',
    'DoNews', '砍柴网', '站长之家', '中国机器人网'
  ];

  var suitability = {
    website: '品牌事实底座',
    wechat: '品牌自有信源',
    baijia: '搜索与 AI 抓取',
    tieba: '社区讨论覆盖',
    toutiao: '高互动内容',
    lofter: '长尾内容覆盖',
    zhihu: '推荐 / 对比提问',
    sohu: '全网内容覆盖',
    penguin: '腾讯内容生态',
    netease: '门户内容覆盖',
    'media-network': '第三方权威背书',
    'backlink-network': 'SEO 外链资产'
  };

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
      saved = JSON.parse(localStorage.getItem(CHANNEL_STORAGE));
    } catch (error) {}
    if (!Array.isArray(saved) || !saved.length) return fallbackChannels.map(function (channel) { return Object.assign({}, channel); });

    var fallbackById = {};
    fallbackChannels.forEach(function (channel) { fallbackById[channel.id] = channel; });
    var savedById = {};
    saved.forEach(function (channel) { if (channel && channel.id) savedById[channel.id] = channel; });
    var merged = fallbackChannels.map(function (channel) {
      var existing = savedById[channel.id];
      if (!existing) return Object.assign({}, channel);
      var result = Object.assign({}, channel, existing);
      if (channel.id === 'toutiao' && existing.name === '头条号') result.name = channel.name;
      if (channel.id === 'zhihu' && existing.name === '知乎机构号') result.name = channel.name;
      return result;
    });
    saved.forEach(function (channel) { if (channel && channel.id && !fallbackById[channel.id]) merged.push(channel); });
    return merged;
  }

  function manualPublishKey(channelId) {
    return 'geo:' + (params.get('id') || 'draft') + ':' + channelId;
  }

  function getManualPublishes() {
    try {
      var records = JSON.parse(localStorage.getItem(MANUAL_PUBLISH_STORAGE));
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
    try {
      saved = JSON.parse(localStorage.getItem(MANUAL_MEDIA_STORAGE));
    } catch (error) {}
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
    try { saved = JSON.parse(localStorage.getItem(MANUAL_MEDIA_STORAGE)); } catch (error) {}
    if (!Array.isArray(saved)) saved = [];
    if (!saved.includes(value)) saved.unshift(value);
    try { localStorage.setItem(MANUAL_MEDIA_STORAGE, JSON.stringify(saved.slice(0, 30))); } catch (error) {}
  }

  function renderManualMediaOptions() {
    var list = document.getElementById('geoManualMediaOptions');
    if (!list) return;
    list.innerHTML = getManualMediaPlatforms().map(function (name) {
      return '<option value="' + escapeHtml(name) + '"></option>';
    }).join('');
  }

  function saveManualPublish(channel, url, mediaPlatform) {
    var records = getManualPublishes();
    records[manualPublishKey(channel.id)] = {
      module: 'GEO',
      articleId: params.get('id') || 'draft',
      channelId: channel.id,
      channelName: channel.name,
      mediaPlatform: mediaPlatform || channel.name,
      url: url,
      publishedAt: new Date().toISOString()
    };
    try { localStorage.setItem(MANUAL_PUBLISH_STORAGE, JSON.stringify(records)); } catch (error) {}
  }

  function removeManualPublish(channelId) {
    var records = getManualPublishes();
    delete records[manualPublishKey(channelId)];
    try { localStorage.setItem(MANUAL_PUBLISH_STORAGE, JSON.stringify(records)); } catch (error) {}
  }

  function notify(message) {
    if (window.geToast) {
      window.geToast(message);
      var live = document.querySelector('.ge-toast:last-of-type');
      if (live) live.style.zIndex = '22000';
      return;
    }
    var toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText = 'position:fixed;left:50%;bottom:26px;z-index:22000;transform:translateX(-50%);padding:10px 16px;border-radius:7px;background:#202a33;color:#fff;font-size:12px;box-shadow:0 10px 28px rgba(0,0,0,.22)';
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 1800);
  }

  function openOverlay(id) {
    var overlay = document.getElementById(id);
    if (overlay) overlay.classList.add('open');
  }

  function closeOverlays() {
    document.querySelectorAll('.geo-overlay.open').forEach(function (overlay) { overlay.classList.remove('open'); });
  }

  function ensureInfoOverlay() {
    var overlay = document.getElementById('geoInfoOverlay');
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'geo-overlay';
    overlay.id = 'geoInfoOverlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="geo-dialog"><div class="geo-dialog-head"><div><h2 id="geoInfoTitle"></h2><p id="geoInfoSub"></p></div>' +
      '<button class="geo-dialog-close" data-geo-action="close-overlay" data-target="geo-content" aria-label="关闭">×</button></div>' +
      '<div class="geo-dialog-body" id="geoInfoBody"></div><div class="geo-dialog-foot" id="geoInfoFoot"></div></div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function showInfo(config) {
    var overlay = ensureInfoOverlay();
    var dialog = overlay.querySelector('.geo-dialog');
    if (dialog) dialog.className = 'geo-dialog' + (config.dialogClass ? ' ' + config.dialogClass : '');
    overlay.querySelector('#geoInfoTitle').textContent = config.title || '';
    overlay.querySelector('#geoInfoSub').textContent = config.sub || '';
    overlay.querySelector('#geoInfoBody').innerHTML = config.body || '';
    overlay.querySelector('#geoInfoFoot').innerHTML = config.foot || '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">关闭</button>';
    openOverlay('geoInfoOverlay');
  }

  function currentFilter() {
    var active = document.querySelector('[data-geo-filter].active');
    return active ? active.getAttribute('data-geo-filter') : '全部';
  }

  function filterRows() {
    var label = currentFilter();
    var query = ((document.getElementById('geoArticleSearch') || {}).value || '').trim().toLowerCase();
    document.querySelectorAll('.geo-list-table tbody tr').forEach(function (row) {
      var statusMatch = label === '全部' || row.getAttribute('data-geo-status') === label;
      var searchMatch = !query || row.textContent.toLowerCase().indexOf(query) >= 0;
      row.style.display = statusMatch && searchMatch ? '' : 'none';
    });
  }

  function initListPage() {
    var search = document.getElementById('geoArticleSearch');
    if (search) search.addEventListener('input', filterRows);
  }

  function editorStorageKey() {
    return 'growthEngine.geo.editor.' + (params.get('id') || 'new');
  }

  function updateWordCount() {
    var editor = document.getElementById('geoArticleEditor');
    var counter = document.getElementById('geoWordCount');
    if (!editor || !counter) return;
    counter.textContent = editor.textContent.replace(/\s/g, '').length.toLocaleString('zh-CN') + ' 字';
  }

  function saveEditor(showFeedback) {
    var title = document.getElementById('geoDocumentTitle');
    var editor = document.getElementById('geoArticleEditor');
    var state = document.getElementById('geoSaveState');
    if (!title || !editor) return;
    try {
      localStorage.setItem(editorStorageKey(), JSON.stringify({ title: title.value, body: editor.innerHTML, savedAt: Date.now() }));
    } catch (error) {}
    if (state) state.textContent = '刚刚已保存';
    if (showFeedback) notify('GEO 文章已保存为新版本');
  }

  function scheduleAutosave() {
    var state = document.getElementById('geoSaveState');
    if (state) state.textContent = '编辑中…';
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(function () { saveEditor(false); }, 700);
    updateWordCount();
  }

  function initEditor() {
    if (page !== 'editor') return;
    var incomingIntent = (params.get('intent') || '').replace(/^#\d+\s*/, '').trim();
    var incomingTitle = (params.get('title') || '').trim();
    if (params.get('new')) {
      var titleInput = document.getElementById('geoDocumentTitle');
      var questionInput = document.getElementById('geoCoreQuestion');
      if (titleInput && (incomingTitle || incomingIntent)) titleInput.value = incomingTitle || incomingIntent;
      if (questionInput && incomingIntent) {
        var hasIncomingQuestion = Array.prototype.some.call(questionInput.options, function (option) { return option.value === incomingIntent; });
        if (!hasIncomingQuestion) questionInput.add(new Option(incomingIntent, incomingIntent));
        questionInput.value = incomingIntent;
      }
    }
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(editorStorageKey())); } catch (error) {}
    if (saved && !params.get('new') && !isImportedArticle) {
      document.getElementById('geoDocumentTitle').value = saved.title;
      document.getElementById('geoArticleEditor').innerHTML = saved.body;
      document.getElementById('geoEditorSub').textContent += ' · 已恢复上次草稿';
    }
    ['geoDocumentTitle', 'geoArticleEditor'].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.addEventListener('input', scheduleAutosave);
    });
    ['geoCoreQuestion', 'geoBriefRequirement', 'geoRecommendProduct'].forEach(function (id) {
      var field = document.getElementById(id);
      if (field) field.addEventListener(id === 'geoCoreQuestion' ? 'change' : 'input', syncBriefSummary);
    });
    updateRecommendationRecognition();
    if (isImportedArticle) {
      var imported = null;
      try { imported = JSON.parse(localStorage.getItem(IMPORT_DRAFT_STORAGE)); } catch (error) {}
      var importedGeneration = document.getElementById('geoGenerationStage');
      var importedEditing = document.getElementById('geoEditingStage');
      if (imported && imported.title) document.getElementById('geoDocumentTitle').value = imported.title;
      if (imported && imported.bodyHtml) document.getElementById('geoArticleEditor').innerHTML = imported.bodyHtml;
      if (imported && imported.question && document.getElementById('geoCoreQuestion')) {
        var importedQuestionSelect = document.getElementById('geoCoreQuestion');
        var hasImportedQuestion = Array.prototype.some.call(importedQuestionSelect.options, function (option) { return option.value === imported.question; });
        if (!hasImportedQuestion) importedQuestionSelect.add(new Option(imported.question, imported.question));
        importedQuestionSelect.value = imported.question;
      }
      if (importedGeneration) importedGeneration.hidden = true;
      if (importedEditing) importedEditing.hidden = false;
      setDraftTabsEnabled(true);
      setImportedVersion(imported || {});
      activateEditorTab('score');
    }
    else if (params.get('id') && !params.get('new')) {
      var generation = document.getElementById('geoGenerationStage');
      var editing = document.getElementById('geoEditingStage');
      if (generation) generation.hidden = true;
      if (editing) editing.hidden = false;
      setDraftTabsEnabled(true);
      revealRegenerateAction();
      promoteOptimizedVersion('当前为 V2 · GEO 优化版，可继续编辑或恢复历史版本。');
      activateEditorTab('score');
    }
    updateWordCount();
    if (params.get('action') === 'polish') {
      var assistantMessage = document.getElementById('geoAssistantMessage');
      if (assistantMessage) assistantMessage.textContent = '已进入 AI 润色模式：建议先补第三方证据，再优化核心结论块。';
      var assistantPrompt = document.getElementById('geoAssistantPrompt');
      if (assistantPrompt) assistantPrompt.focus();
    }
    if (params.get('action') === 'factcheck') setTimeout(showFactCheck, 260);
    if (params.get('publish') === '1') setTimeout(openPublish, 260);
  }

  function activateEditorTab(name) {
    var button = document.querySelector('[data-geo-tab="' + name + '"]');
    if (!button) return;
    if (button.getAttribute('aria-disabled') === 'true') {
      notify('生成母稿后即可进行 GEO 评分');
      return;
    }
    switchEditorTab(button);
    if (name === 'brief') {
      var panel = document.querySelector('.geo-brief-panel');
      if (panel) {
        panel.classList.remove('geo-panel-focus');
        void panel.offsetWidth;
        panel.classList.add('geo-panel-focus');
      }
    }
  }

  function setDraftTabsEnabled(enabled) {
    ['score', 'suggestions'].forEach(function (name) {
      var button = document.querySelector('[data-geo-tab="' + name + '"]');
      if (!button) return;
      button.classList.toggle('is-disabled', !enabled);
      if (enabled) {
        button.removeAttribute('aria-disabled');
        button.removeAttribute('title');
      } else {
        button.setAttribute('aria-disabled', 'true');
        button.setAttribute('title', '生成母稿后即可进行 GEO 评分');
      }
    });
  }

  function revealRegenerateAction() {
    var button = document.getElementById('geoRegenerateButton');
    var note = document.getElementById('geoRegenerateNote');
    if (button) button.hidden = false;
    if (note) note.hidden = false;
  }

  function syncBriefSummary() {
    var question = document.getElementById('geoCoreQuestion');
    var requirement = document.getElementById('geoBriefRequirement');
    var questionSummary = document.getElementById('geoSummaryQuestion');
    var requirementSummary = document.getElementById('geoSummaryRequirement');
    if (question && questionSummary) questionSummary.textContent = question.value.trim() || '待选择目标 AI 提问';
    if (requirement && requirementSummary) requirementSummary.textContent = requirement.value.trim() || '无额外创作要求，系统将依据品牌信息与可信资料自动判断。';
    updateRecommendationRecognition();
  }

  function updateRecommendationRecognition() {
    var input = document.getElementById('geoRecommendProduct');
    var summary = document.getElementById('geoSummaryRecommend');
    if (!input || !summary) return;
    var value = input.value.trim();
    var selectedGoal = document.querySelector('[data-geo-goal].selected');
    var goal = selectedGoal ? selectedGoal.getAttribute('data-geo-goal') : 'brand';
    if (!value) {
      if (goal === 'citation') {
        summary.textContent = '未指定（以内容可信度和可引用性优先）';
      } else if (goal === 'brand') {
        summary.textContent = '根据当前品牌信息自动判断';
      } else {
        summary.textContent = '未指定';
      }
      return;
    }
    summary.textContent = value;
  }

  function handleReadyAction(action) {
    if (action === 'knowledge' || action === 'sources') {
      activateEditorTab('sources');
      if (action === 'sources') {
        document.querySelectorAll('[data-geo-trusted-source]').forEach(function (item) {
          item.classList.add('geo-source-focus');
          setTimeout(function () { item.classList.remove('geo-source-focus'); }, 1600);
        });
      }
      notify(action === 'sources' ? '已展示本篇使用的 3 个可信来源' : '已打开本篇匹配的知识库资料');
      return;
    }
    if (action === 'brand') {
      showInfo({
        title: '本篇调用的品牌资料',
        sub: '来自「品牌信息」，生成时自动应用',
        body: '<div class="geo-context-preview"><span class="geo-product-logo">3M</span><div><b>3M · 工业粘接解决方案</b><p>品牌定位：工业材料与粘接技术品牌<br>业务类型：B2B · 中国市场<br>本篇应用：品牌名称、技术定位、合规表达边界</p></div></div>',
        foot: '<a class="btn" href="brand.html">查看完整品牌资料</a><button class="btn primary" data-geo-action="close-overlay" data-target="geo-content">知道了</button>'
      });
      return;
    }
    if (action === 'product') {
      showInfo({
        title: '匹配到 2 条产品相关资料',
        sub: '从知识库与可信资料中自动识别',
        body: '<div class="geo-context-preview"><div><b>3M VHB 产品说明</b><p>知识库 · 产品手册 · 用于正文</p><b>机器人外壳粘接解决方案</b><p>知识库 · 技术资料 · 用于正文<br><small>生成时会优先依据资料原文，不会扩写无来源参数。</small></p></div></div>',
        foot: '<button class="btn" data-geo-switch-tab="sources">查看产品资料来源</button><button class="btn primary" data-geo-action="close-overlay" data-target="geo-content">知道了</button>'
      });
      return;
    }
    if (action === 'questions') {
      showInfo({
        title: '预计覆盖的 5 个 GEO 问题',
        sub: '来自 GEO 提问监控与目标 AI 提问扩展',
        body: '<ol class="geo-question-preview"><li>机器人外壳粘接胶怎么选？</li><li>3M VHB 胶带适合哪些机器人外壳材料？</li><li>胶粘方案与螺丝、卡扣相比有什么优势？</li><li>机器人外壳粘接如何兼顾密封和防震？</li><li>机器人外壳粘接量产前需要验证什么？</li></ol>',
        foot: '<button class="btn primary" data-geo-action="close-overlay" data-target="geo-content">知道了</button>'
      });
    }
  }

  function setVersion(version, optimized) {
    var label = document.getElementById('geoCurrentVersionLabel');
    var meta = document.getElementById('geoVersionMeta');
    var footer = document.getElementById('geoVersion');
    var summary = document.getElementById('geoFlowSummary');
    if (label) label.textContent = optimized ? '当前版本：V' + version + ' · GEO 优化版' : (isImportedArticle ? 'V' + version + ' · 原始稿' : '母稿 V' + version);
    if (meta) meta.textContent = optimized ? '评分 93 · 基于 V1 优化' : (isImportedArticle ? '手动导入 · 已关联目标问题 · 已完成首次 GEO 检测' : 'AI 初稿 · 约 2,036 字 · 覆盖 5 个目标问题 · 引用 3 个可信来源');
    if (footer) footer.textContent = '版本 V' + version;
    if (summary) summary.textContent = optimized ? 'V2 · GEO优化版 · 评分93 · 待发布' : 'V1 · AI母稿 · 待 GEO 评分';
    document.querySelectorAll('[data-geo-version]').forEach(function (button) {
      button.classList.toggle('selected', button.getAttribute('data-geo-version') === String(version));
    });
    var create = document.getElementById('geoFlowCreate');
    var brief = document.getElementById('geoFlowBrief');
    var draft = document.getElementById('geoFlowDraft');
    var optimize = document.getElementById('geoFlowOptimize');
    document.querySelectorAll('.geo-post-draft').forEach(function (node) { node.hidden = false; });
    if (create) create.className = 'geo-flow-state done';
    if (brief) { brief.textContent = '✓ 确定创作要求'; brief.className = 'geo-flow-state done'; }
    if (draft) draft.textContent = optimized ? (isImportedArticle ? '✓ V1 原始稿' : '✓ 母稿 V1') : (isImportedArticle ? 'V' + version + ' 原始稿' : '母稿 V' + version);
    if (draft) draft.classList.toggle('done', optimized);
    if (draft) draft.classList.toggle('active', !optimized);
    if (optimize) optimize.classList.toggle('active', optimized);
  }

  function setImportedVersion(imported) {
    setVersion(1, false);
    var create = document.getElementById('geoFlowCreate');
    var brief = document.getElementById('geoFlowBrief');
    var summary = document.getElementById('geoFlowSummary');
    if (create) create.textContent = '✓ 导入文章';
    if (brief) brief.textContent = '✓ 关联目标问题';
    if (summary) summary.textContent = 'V1 · 原始稿 · 首次 GEO 评分 72 · 待优化';
    updateScore(72, 58);
    var ring = document.querySelector('.geo-score-ring');
    var ringCaption = document.querySelector('.geo-score-ring span');
    var meter = document.querySelector('.geo-score-meter span');
    var scoreLabel = document.getElementById('geoScoreLabel');
    if (ring) ring.style.setProperty('--score', '72%');
    if (ringCaption) ringCaption.textContent = '分 · 待优化';
    if (meter) meter.style.width = '72%';
    if (scoreLabel) scoreLabel.textContent = '待优化';
    var scoreCopy = document.querySelector('.geo-score-copy');
    if (scoreCopy) {
      var scoreTitle = scoreCopy.querySelector('b');
      var scoreHint = scoreCopy.querySelector('small');
      if (scoreTitle) scoreTitle.textContent = '已完成首次 GEO 检测';
      if (scoreHint) scoreHint.textContent = '发现 5 项可能影响 AI 引用、可信度和品牌推荐的问题。';
    }
    var versionButton = document.querySelector('[data-geo-version="1"]');
    if (versionButton) versionButton.innerHTML = 'V1 <small>72分</small>';
    var sourceCount = document.getElementById('sourceCount');
    if (sourceCount) sourceCount.textContent = '信源 0 个';
    var trustedHighlight = document.querySelector('.geo-score-highlights div:nth-child(3) b');
    if (trustedHighlight) trustedHighlight.textContent = '0';
    var versionMeta = document.getElementById('geoVersionMeta');
    var wordCount = imported.bodyText ? imported.bodyText.replace(/\s/g, '').length : 0;
    if (versionMeta) versionMeta.textContent = '手动导入 · ' + wordCount.toLocaleString('zh-CN') + ' 字 · 已关联 1 个目标问题 · 待 GEO 优化';
    var message = document.getElementById('geoAssistantMessage');
    if (message) message.textContent = '首次检测发现：首段答案不够明确、2 项观点缺少来源，并缺少便于 AI 摘取的对比与 FAQ 结构。';
  }

  function generateDraft(button) {
    var generation = document.getElementById('geoGenerationStage');
    var editing = document.getElementById('geoEditingStage');
    if (!generation || !editing) return;
    var ready = document.getElementById('geoGenerationReady');
    var progress = document.getElementById('geoGenerationProgress');
    var title = document.getElementById('geoGenerationTitle');
    var subtitle = document.getElementById('geoGenerationSubtitle');
    var percent = document.getElementById('geoProgressPercent');
    var bar = document.getElementById('geoDraftProgressBar');
    var steps = Array.prototype.slice.call(document.querySelectorAll('.geo-generation-steps li'));
    button.disabled = true;
    if (ready) ready.hidden = true;
    if (progress) progress.hidden = false;
    if (title) title.textContent = '正在生成母稿……';
    if (subtitle) subtitle.textContent = 'AI 正在依据创作要求、知识库与可信来源组织文章。';
    var values = [18, 38, 58, 82, 100];
    var index = 0;
    function advance() {
      steps.forEach(function (step, stepIndex) {
        step.classList.toggle('done', stepIndex < index);
        step.classList.toggle('active', stepIndex === index);
      });
      if (percent) percent.textContent = values[index] + '%';
      if (bar) bar.style.width = values[index] + '%';
      index += 1;
      if (index < steps.length) {
        setTimeout(advance, 360);
        return;
      }
      setTimeout(function () {
        steps.forEach(function (step) { step.classList.remove('active'); step.classList.add('done'); });
        if (title) title.textContent = '母稿 V1 已生成';
        if (subtitle) subtitle.textContent = '已完成初步 GEO 检查，即将进入文章编辑状态。';
        setTimeout(function () {
          generation.hidden = true;
          editing.hidden = false;
          setDraftTabsEnabled(true);
          revealRegenerateAction();
          setVersion(1, false);
          activateEditorTab('score');
          updateWordCount();
          notify('母稿 V1 已生成，并完成首次 GEO 评分');
        }, 520);
      }, 360);
    }
    advance();
  }

  function promoteOptimizedVersion(message) {
    setVersion(2, true);
    updateScore(93, 91);
    var ring = document.querySelector('.geo-score-ring');
    var ringCaption = document.querySelector('.geo-score-ring span');
    var meter = document.querySelector('.geo-score-meter span');
    var delta = document.getElementById('geoScoreDelta');
    if (ring) ring.style.setProperty('--score', '93%');
    if (ringCaption) ringCaption.textContent = '分 · 优秀';
    if (meter) meter.style.width = '93%';
    if (delta) delta.hidden = false;
    var scoreLabel = document.getElementById('geoScoreLabel');
    if (scoreLabel) scoreLabel.textContent = '优秀';
    var scoreCopy = document.querySelector('.geo-score-copy');
    if (scoreCopy) {
      var scoreTitle = scoreCopy.querySelector('b');
      var scoreHint = scoreCopy.querySelector('small');
      if (scoreTitle) scoreTitle.textContent = '已达到推荐发布标准';
      if (scoreHint) scoreHint.textContent = '3 项关键问题已优化，AI 引用与品牌推荐能力明显提升。';
    }
    [['extract', 89], ['evidence', 91], ['brand', 94]].forEach(function (item) {
      var row = document.querySelector('[data-geo-open-suggestion="' + item[0] + '"]');
      if (!row) return;
      row.classList.remove('issue');
      var bar = row.querySelector('i em');
      var value = row.querySelector('b');
      var issueCount = row.querySelector('small');
      if (bar) { bar.style.width = item[1] + '%'; bar.style.background = '#5e91ee'; }
      if (value) value.textContent = String(item[1]);
      if (issueCount) issueCount.remove();
    });
    var assistantMessage = document.getElementById('geoAssistantMessage');
    if (assistantMessage) {
      assistantMessage.className = 'geo-ai-message success';
      assistantMessage.textContent = message || '优化已完成：已创建 V2，GEO 评分由 85 提升至 93。';
    }
  }

  function runCommand(button) {
    var editor = document.getElementById('geoArticleEditor');
    if (!editor) return;
    editor.focus();
    var command = button.getAttribute('data-geo-command');
    var value = button.getAttribute('data-value') || null;
    try {
      if (command === 'formatBlock' && value) document.execCommand('formatBlock', false, value);
      else document.execCommand(command, false, value);
    } catch (error) {}
    scheduleAutosave();
  }

  var savedRange = null;

  function rememberSelection() {
    var selection = window.getSelection();
    if (selection && selection.rangeCount) savedRange = selection.getRangeAt(0).cloneRange();
  }

  function restoreSelection() {
    var editor = document.getElementById('geoArticleEditor');
    if (!editor || !savedRange) return;
    editor.focus();
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(savedRange);
  }

  function insertLink() {
    rememberSelection();
    var selected = savedRange ? String(savedRange.toString() || '').trim() : '';
    showInfo({
      title: '插入链接',
      sub: '为选中文字添加来源或跳转地址',
      body: '<label class="geo-field-label" style="margin:0 0 10px;">链接地址<input class="geo-input" id="geoLinkUrl" placeholder="https://"></label><label class="geo-field-label">显示文字<input class="geo-input" id="geoLinkText" value="' + escapeHtml(selected) + '" placeholder="不填则使用选中文字"></label>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="insert-link-confirm" data-target="geo-content">插入链接</button>'
    });
  }

  function insertLinkConfirm() {
    var urlInput = document.getElementById('geoLinkUrl');
    var textInput = document.getElementById('geoLinkText');
    var url = urlInput ? String(urlInput.value || '').trim() : '';
    var text = textInput ? String(textInput.value || '').trim() : '';
    if (!url) {
      notify('请填写链接地址');
      return;
    }
    restoreSelection();
    if (text) {
      try { document.execCommand('insertHTML', false, '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + escapeHtml(text) + '</a>'); } catch (error) {}
    } else {
      try { document.execCommand('createLink', false, url); } catch (error) {}
    }
    closeOverlays();
    scheduleAutosave();
    notify('链接已插入');
  }

  function htmlToMarkdown(html) {
    var node = document.createElement('div');
    node.innerHTML = html || '';
    function walk(el) {
      if (el.nodeType === 3) return el.nodeValue;
      if (el.nodeType !== 1) return '';
      var name = el.tagName.toLowerCase();
      var inner = Array.prototype.map.call(el.childNodes, walk).join('');
      if (name === 'h1') return '# ' + inner + '\n\n';
      if (name === 'h2') return '## ' + inner + '\n\n';
      if (name === 'h3') return '### ' + inner + '\n\n';
      if (name === 'p') return inner + '\n\n';
      if (name === 'br') return '\n';
      if (name === 'strong' || name === 'b') return '**' + inner + '**';
      if (name === 'em' || name === 'i') return '*' + inner + '*';
      if (name === 'u') return inner;
      if (name === 'li') return '- ' + inner + '\n';
      if (name === 'ul' || name === 'ol') return inner + '\n';
      if (name === 'blockquote') return '> ' + inner + '\n\n';
      if (name === 'a') return '[' + inner + '](' + (el.getAttribute('href') || '') + ')';
      return inner;
    }
    return walk(node).replace(/\n{3,}/g, '\n\n').trim();
  }

  function markdownToHtml(text) {
    return String(text || '').split(/\n{2,}/).map(function (block) {
      var line = block.trim();
      if (!line) return '';
      if (line.indexOf('### ') === 0) return '<h3>' + escapeHtml(line.slice(4)) + '</h3>';
      if (line.indexOf('## ') === 0) return '<h2>' + escapeHtml(line.slice(3)) + '</h2>';
      if (line.indexOf('# ') === 0) return '<h1>' + escapeHtml(line.slice(2)) + '</h1>';
      if (line.indexOf('> ') === 0) return '<blockquote>' + escapeHtml(line.replace(/^> /gm, '')) + '</blockquote>';
      line = escapeHtml(line).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>');
      return '<p>' + line.replace(/\n/g, '<br>') + '</p>';
    }).join('');
  }

  function toggleMarkdown(button) {
    var editor = document.getElementById('geoArticleEditor');
    var markdown = document.getElementById('geoMarkdownEditor');
    if (!editor || !markdown) return;
    var showing = !markdown.hidden;
    if (showing) {
      editor.innerHTML = markdownToHtml(markdown.value);
      markdown.hidden = true;
      editor.style.display = '';
      if (button) button.classList.remove('active');
      scheduleAutosave();
      notify('已切回富文本');
    } else {
      markdown.value = htmlToMarkdown(editor.innerHTML);
      editor.style.display = 'none';
      markdown.hidden = false;
      markdown.focus();
      if (button) button.classList.add('active');
      notify('已切换为 Markdown');
    }
  }

  function applyBlockType(select) {
    var editor = document.getElementById('geoArticleEditor');
    var value = select && select.value;
    if (!editor || !value) return;
    editor.focus();
    try { document.execCommand('formatBlock', false, value); } catch (error) {}
    select.value = '';
    scheduleAutosave();
  }

  function updateScore(citation, trust) {
    var citationNode = document.getElementById('citationScore');
    var trustNode = document.getElementById('trustScore');
    if (citationNode && citation != null) citationNode.textContent = String(Math.round(Number(citation)));
    if (trustNode && trust != null) trustNode.textContent = trust;
  }

  function runAi(action, button) {
    var editor = document.getElementById('geoArticleEditor');
    var message = document.getElementById('geoAssistantMessage');
    if (!editor) return;
    function setMessage(text, success) {
      if (message) {
        message.className = success ? 'geo-ai-message success' : 'geo-ai-message';
        message.textContent = text;
      } else {
        notify(text);
      }
    }
    var oldText = button.textContent;
    button.disabled = true;
    button.textContent = 'AI 处理中…';
    setMessage('正在对照目标提问、品牌事实与信源材料分析正文…');

    setTimeout(function () {
      if (action === 'ai-polish') {
        var firstParagraph = editor.querySelector('p');
        if (firstParagraph) firstParagraph.innerHTML = '判断机器人外壳粘接方案是否适合量产，关键不只在初粘强度，而在四项可验证能力：材料兼容性、长期密封性、抗震缓冲能力，以及装配后外观一致性。';
        editor.insertAdjacentHTML('beforeend', '<div class="geo-quote-block">核心结论：机器人外壳粘接应优先验证实际壳体材料、曲面结构和使用环境；脱离样件测试的胶粘剂参数对量产决策参考有限。</div>');
        setMessage('已润色首段并新增可直接摘取的核心结论，AI 友好度提升至 86。', true);
        updateScore(86, 86);
      } else if (action === 'ai-definition') {
        var definition = editor.querySelector('.geo-definition');
        if (definition) definition.innerHTML = '<b>一句话定义：</b>机器人外壳粘接方案，是围绕壳体材质、密封防护、抗震缓冲和外观完整性选择胶带、结构胶或底涂组合的装配工艺方案。';
        setMessage('定义已改为“类别 + 作用 + 核心组成”结构，更便于 AI 摘取。', true);
        updateScore(82, null);
      } else if (action === 'ai-evidence') {
        editor.insertAdjacentHTML('beforeend', '<h2>补充证据：样件粘接验证记录</h2><p>在量产前验证阶段，建议使用真实机器人外壳样件完成剥离强度、冷热循环、跌落冲击和外观缝隙检查。该类测试记录可作为选型依据，避免只根据胶带型号参数判断适配性。<sup class="geo-citation">[3]</sup></p><p>[3] 机器人外壳粘接样件验证记录，2026-06，演示材料。</p>');
        var sourceCheck = document.getElementById('sourceCheck');
        var evidenceCheck = document.getElementById('evidenceCheck');
        if (sourceCheck) { sourceCheck.textContent = '3 个'; sourceCheck.className = 'geo-ok'; }
        if (evidenceCheck) { evidenceCheck.textContent = '已补充'; evidenceCheck.className = 'geo-ok'; }
        var sourceCount = document.getElementById('sourceCount');
        if (sourceCount) sourceCount.textContent = '信源 3 个';
        setMessage('已补充一组项目证据及完整来源说明，事实可信度提升至 91。', true);
        updateScore(88, 91);
      } else if (action === 'ai-structure') {
        editor.insertAdjacentHTML('beforeend', '<div class="geo-quote-block">给工程团队的简明建议：先用真实外壳材料做样件测试，再比较胶粘剂成本和施工效率；这样比单看产品参数更容易识别量产风险。</div><h2>补充 FAQ</h2><h3>机器人外壳粘接一定要用结构胶吗？</h3><p>不一定。平面或轻曲面外壳可优先评估 VHB 胶带，承力结构、复杂曲面或特殊材料则需要结合结构胶、底涂和样件测试确认。</p>');
        setMessage('已新增结论块与 FAQ，正文现在包含 5 个可独立摘取的信息单元。', true);
        updateScore(89, null);
      } else if (action === 'ai-factcheck') {
        showFactCheck();
        setMessage('已核验 11 项事实：9 项通过，2 项需要补充第三方来源。', true);
        updateScore(null, 89);
      } else if (action === 'ai-engines') {
        showEngineMatrix();
        setMessage('已生成 5 个 AI 引擎的内容适配建议。', true);
      } else if (action === 'ai-title') {
        showTitleOptions();
        setMessage('已生成 5 个强调定义、决策和可信度的标题版本。', true);
      } else if (action === 'ai-brand-reason') {
        editor.insertAdjacentHTML('beforeend', '<div class="geo-quote-block"><b>为什么推荐 3M VHB：</b>更适合重视无孔外观、连续密封和装配效率的平面或轻曲面外壳；若属于高承力结构或低表面能材料，仍应通过样件测试确认胶带与底涂组合。</div>');
        setMessage('已补充适用场景、方案优势与选择边界。', true);
        updateScore(90, null);
      } else if (action === 'ai-optimize-all') {
        var first = editor.querySelector('p');
        if (first) first.innerHTML = '机器人外壳粘接胶应根据壳体材质、受力方式、密封等级和装配节拍综合选择。对于重视无孔外观、连续密封与安装效率的平面或轻曲面外壳，可优先评估 3M VHB 胶带；高承力结构或特殊材料仍需样件验证。';
        editor.insertAdjacentHTML('beforeend', '<h2>如何判断 3M VHB 是否适合机器人外壳？</h2><p>推荐理由主要包括：减少钻孔带来的外观与应力问题、兼顾密封与减震、简化装配步骤。实际选型需结合材料表面能、曲率、载荷与工作环境，并以产品技术资料及样件测试为依据。<sup class="geo-citation">[3]</sup></p>');
        setMessage('3 项建议已全部应用，正在重新评分…', true);
        updateScore(93, 91);
      }
      button.disabled = false;
      button.textContent = oldText;
      scheduleAutosave();
      if (['ai-polish', 'ai-definition', 'ai-evidence', 'ai-structure', 'ai-brand-reason', 'ai-optimize-all'].indexOf(action) >= 0) {
        promoteOptimizedVersion(action === 'ai-optimize-all' ? '已完成 3 项优化，并创建 V2 · GEO 优化版。评分 85 → 93 ↑8' : '此处已优化，并创建 V2 · GEO 优化版。');
      }
    }, 760);
  }

  function showFactCheck() {
    showInfo({
      title: 'AI 事实核验结果',
      sub: '对照品牌事实卡、客户案例和公开信源逐项检查',
      body: '<table><thead><tr><th>事实陈述</th><th>核验来源</th><th>结果</th><th>建议</th></tr></thead><tbody>' +
        '<tr><td>VHB 胶带适合多数平面外壳拼接</td><td>3M 产品资料</td><td><span class="badge green">一致</span></td><td>保留</td></tr>' +
        '<tr><td>硅胶仿真外壳需验证底涂兼容性</td><td>应用工程记录</td><td><span class="badge green">有证据</span></td><td>补测试条件</td></tr>' +
        '<tr><td>所有机器人外壳都可直接使用同一胶带</td><td>暂无通用依据</td><td><span class="badge amber">来源不足</span></td><td>改为场景化表达</td></tr>' +
        '<tr><td>密封和抗震会影响长期稳定性</td><td>样件验证记录</td><td><span class="badge green">一致</span></td><td>补更新时间</td></tr>' +
        '</tbody></table>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">暂不处理</button><button class="btn primary" data-geo-action="apply-factcheck" data-target="geo-content">应用核验建议</button>'
    });
  }

  function showEngineMatrix() {
    showInfo({
      title: 'AI 引擎适配建议',
      sub: '根据当前监测到的引用偏好生成',
      body: '<table class="geo-engine-matrix"><thead><tr><th>AI 引擎</th><th>当前适配度</th><th>更容易引用的结构</th><th>建议动作</th></tr></thead><tbody>' +
        '<tr><td class="kw">DeepSeek</td><td><span class="badge green">88</span></td><td>明确结论、技术细节</td><td>保留五维验证框架</td></tr>' +
        '<tr><td class="kw">Kimi</td><td><span class="badge amber">76</span></td><td>公开报告、长文信源</td><td>补第三方报告引用</td></tr>' +
        '<tr><td class="kw">豆包</td><td><span class="badge amber">72</span></td><td>问答、百科与互动内容</td><td>拆出 3 个 FAQ</td></tr>' +
        '<tr><td class="kw">通义</td><td><span class="badge green">84</span></td><td>官网事实与结构化信息</td><td>官网首发并加事实卡</td></tr>' +
        '<tr><td class="kw">腾讯元宝</td><td><span class="badge amber">70</span></td><td>公众号与公开资料</td><td>生成公众号适配版</td></tr>' +
        '</tbody></table>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">关闭</button><button class="btn primary" data-geo-action="apply-engines" data-target="geo-content">应用全部建议</button>'
    });
  }

  function showTitleOptions() {
    var titles = [
      '机器人外壳粘接胶怎么选？3M系列方案详解',
      '3M VHB胶带适合机器人外壳粘接吗？应用场景与选型方法',
      '机器人外壳拼接方案：从材料兼容到密封防护',
      '机器人外壳粘接要验证什么？工程选型的 5 个要点',
      '从塑料壳体到硅胶仿真外壳：3M粘接方案对比'
    ];
    showInfo({
      title: 'AI 标题建议',
      sub: '强调清晰定义与信息增益，不使用关键词堆叠',
      body: titles.map(function (title, index) { return '<label class="geo-option-line" style="padding:10px;border-bottom:1px solid #eceff1;"><input type="radio" name="geo-title-option" value="' + escapeHtml(title) + '"' + (index === 0 ? ' checked' : '') + '> <span>' + escapeHtml(title) + '</span></label>'; }).join(''),
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="apply-title" data-target="geo-content">使用所选标题</button>'
    });
  }

  function knowledgeFacts() {
    return window.GEOFacts && typeof window.GEOFacts.list === 'function' ? window.GEOFacts.list() : [];
  }

  function factOptionLabel(fact) {
    var text = String(fact.statement || '');
    return (fact.type ? fact.type + ' · ' : '') + (text.length > 28 ? text.slice(0, 28) + '…' : text);
  }

  function fillEvidenceFromFact(fact) {
    var type = document.getElementById('evidenceType');
    var name = document.getElementById('evidenceName');
    var source = document.getElementById('evidenceProof');
    var statement = document.getElementById('evidenceFact');
    if (!fact) {
      if (type) type.value = '';
      if (name) name.value = '';
      if (source) source.value = '';
      if (statement) statement.value = '';
      return;
    }
    if (type) type.value = fact.type || '';
    if (name) name.value = (fact.biz ? fact.biz + ' / ' : '') + (fact.type || '知识库事实');
    if (source) source.value = fact.source || '';
    if (statement) statement.value = fact.statement || '';
  }

  function syncEvidenceOrigin() {
    var origin = document.getElementById('evidenceOrigin');
    if (!origin) return;
    var isSystem = origin.value === 'system';
    var pickWrap = document.getElementById('evidencePickWrap');
    var proofWrap = document.getElementById('evidenceProofWrap');
    var joinWrap = document.getElementById('evidenceJoinWrap');
    if (pickWrap) pickWrap.style.display = isSystem ? 'grid' : 'none';
    if (proofWrap) proofWrap.style.display = isSystem ? 'none' : 'grid';
    if (joinWrap) joinWrap.style.display = isSystem ? 'none' : 'flex';
    if (isSystem) {
      var pick = document.getElementById('evidenceFactPick');
      var fact = pick ? (window.GEOFacts && window.GEOFacts.find(pick.value)) : knowledgeFacts()[0];
      fillEvidenceFromFact(fact);
    } else {
      fillEvidenceFromFact(null);
    }
  }

  function showAddEvidence() {
    var facts = knowledgeFacts();
    var options = facts.map(function (fact, index) {
      return '<option value="' + escapeHtml(fact.id) + '"' + (index === 0 ? ' selected' : '') + '>' + escapeHtml(factOptionLabel(fact)) + '</option>';
    }).join('');
    showInfo({
      title: '添加可信材料',
      sub: '可从系统知识库带入，或新增一条事实材料',
      body: '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<label class="geo-field-label" style="grid-column:1/-1;margin:0;">材料来源<select class="geo-input" id="evidenceOrigin" style="margin-top:5px;"><option value="system">系统知识库</option><option value="new">新增知识库</option></select></label>' +
        '<label class="geo-field-label" id="evidencePickWrap" style="grid-column:1/-1;margin:0;">选择知识库事实<select class="geo-input" id="evidenceFactPick" style="margin-top:5px;">' + (options || '<option value="">暂无知识库事实</option>') + '</select></label>' +
        '<label class="geo-field-label" style="margin:0;">材料类型<select class="geo-input" id="evidenceType" style="margin-top:5px;"><option value="">请选择</option><option>产品规格</option><option>案例数据</option><option>能力资质</option><option>解决方案</option><option>误解澄清</option></select></label>' +
        '<label class="geo-field-label" style="margin:0;">材料名称<input class="geo-input" id="evidenceName" placeholder="例如：智能客服价格口径" style="margin-top:5px;"></label>' +
        '<label class="geo-field-label" id="evidenceProofWrap" style="grid-column:1/-1;margin:0;display:none;">证据来源<input class="geo-input" id="evidenceProof" placeholder="官网 URL 或文档名" style="margin-top:5px;"></label>' +
        '<label class="geo-field-label" style="grid-column:1/-1;margin:0;">可引用事实<textarea class="geo-prompt-input" id="evidenceFact" placeholder="写成一句可被 AI 直接引用的事实陈述" style="min-height:72px;margin-top:5px;"></textarea></label>' +
        '<label class="geo-field-label" id="evidenceJoinWrap" style="grid-column:1/-1;margin:0;display:none;flex-direction:row;align-items:center;gap:8px;"><input type="checkbox" id="evidenceJoinKb" checked> 加入知识库</label>' +
        '</div>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="add-evidence-confirm" data-target="geo-content">加入可信材料</button>'
    });
    syncEvidenceOrigin();
  }

  function showInsertSource() {
    showInfo({
      title: '插入事实来源',
      sub: '正文将插入来源编号，参考材料区同步追加完整信息',
      body: '<label class="geo-field-label" style="margin:0 0 10px;">来源名称<input class="geo-input" id="newSourceName" value="3M 机器人外壳粘接应用资料"></label><label class="geo-field-label">发布日期<input class="geo-input" id="newSourceDate" type="date" value="2026-06-18"></label><label class="geo-field-label">来源地址<input class="geo-input" id="newSourceUrl" value="https://example.com/research/robot-shell-bonding"></label>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="insert-source-confirm" data-target="geo-content">插入来源</button>'
    });
  }

  function insertComparisonTable() {
    var editor = document.getElementById('geoArticleEditor');
    if (!editor) return;
    editor.insertAdjacentHTML('beforeend', '<h2>外壳粘接验证表</h2><table style="width:100%;border-collapse:collapse;margin:12px 0;"><thead><tr><th style="border:1px solid #dce2e7;padding:8px;">验证维度</th><th style="border:1px solid #dce2e7;padding:8px;">验证方法</th><th style="border:1px solid #dce2e7;padding:8px;">通过标准</th></tr></thead><tbody><tr><td style="border:1px solid #dce2e7;padding:8px;">材料兼容</td><td style="border:1px solid #dce2e7;padding:8px;">真实壳体样件试贴</td><td style="border:1px solid #dce2e7;padding:8px;">无脱胶、无明显白化</td></tr><tr><td style="border:1px solid #dce2e7;padding:8px;">密封防护</td><td style="border:1px solid #dce2e7;padding:8px;">冷热循环与粉尘测试</td><td style="border:1px solid #dce2e7;padding:8px;">缝隙稳定且防护达标</td></tr></tbody></table>');
    scheduleAutosave();
    notify('对比表已插入正文');
  }

  function quoteSelection() {
    var editor = document.getElementById('geoArticleEditor');
    if (!editor) return;
    var selection = window.getSelection();
    var text = selection && selection.toString().trim();
    if (!text) {
      editor.insertAdjacentHTML('beforeend', '<div class="geo-quote-block">在这里输入可被 AI 独立引用的明确结论。</div>');
    } else {
      try { document.execCommand('insertHTML', false, '<div class="geo-quote-block">' + escapeHtml(text) + '</div>'); } catch (error) {}
    }
    scheduleAutosave();
    notify('已转换为可摘取结论块');
  }

  function showPreview() {
    var paper = document.getElementById('geoPreviewPaper');
    var title = document.getElementById('geoDocumentTitle');
    var editor = document.getElementById('geoArticleEditor');
    if (!paper || !title || !editor) return;
    paper.innerHTML = '<h1>' + escapeHtml(title.value) + '</h1><p style="color:#7a838f;font-size:11px;">作者：SearchPilot 内容研究组 · 更新于 2026-07-14 · 已核验信源 3 个</p>' + editor.innerHTML;
    openOverlay('geoPreviewOverlay');
  }

  function renderPublishPlatforms(preserveSelection) {
    var container = document.getElementById('geoPublishPlatforms');
    if (!container) return;
    var channels = getChannels().filter(function (channel) { return channel.connected; });
    if (preserveSelection) {
      selectedPlatforms = new Set(channels.filter(function (channel) {
        return channel.enabled && selectedPlatforms.has(channel.id);
      }).map(function (channel) { return channel.id; }));
    } else {
      selectedPlatforms = new Set(channels.filter(function (channel) {
        return channel.enabled && ['website', 'zhihu', 'wechat'].indexOf(channel.id) >= 0;
      }).map(function (channel) { return channel.id; }));
    }
    if (!channels.length) {
      container.innerHTML = '<div class="geo-publish-empty">当前没有已对接平台。请先到共享分发平台完成授权，或改用「手动发布」回填网址。</div>';
      updatePublishButton();
      return;
    }
    container.innerHTML = channels.map(function (channel) {
      var paused = !channel.enabled;
      var selected = selectedPlatforms.has(channel.id);
      var modeClass = paused ? ' offline paused' : '';
      var detail = paused ? '平台已停用，请先到平台管理中启用' : (suitability[channel.id] || '补充内容覆盖');
      return '<div class="geo-publish-platform' + (selected ? ' selected' : '') + modeClass + '" data-geo-platform="' + escapeHtml(channel.id) + '" role="button" tabindex="0"><i></i><strong>' + escapeHtml(channel.name) + '</strong><small>' + escapeHtml(channel.account || '待配置账号') + '</small><em>' + escapeHtml(detail) + '</em></div>';
    }).join('');
    updatePublishButton();
  }

  function updatePublishButton() {
    var button = document.getElementById('geoConfirmPublish');
    if (!button) return;
    button.textContent = '发布到 ' + selectedPlatforms.size + ' 个信源';
    button.disabled = selectedPlatforms.size === 0;
  }

  function openPublish() {
    closeOverlays();
    var selection = document.getElementById('geoPublishSelection');
    var progress = document.getElementById('geoPublishProgress');
    var button = document.getElementById('geoConfirmPublish');
    if (selection) selection.style.display = '';
    if (progress) progress.classList.remove('active');
    if (button) { button.dataset.geoAction = 'confirm-publish'; button.disabled = false; }
    renderPublishPlatforms();
    openOverlay('geoPublishOverlay');
  }

  function closeManualPublish() {
    var overlay = document.getElementById('geoManualPublishOverlay');
    if (overlay) overlay.classList.remove('open');
    activeManualPlatformId = '';
  }

  function renderManualChannelSelect(selectedId) {
    var select = document.getElementById('geoManualChannelSelect');
    if (!select) return;
    var channels = getChannels();
    select.innerHTML = channels.map(function (channel) {
      return '<option value="' + escapeHtml(channel.id) + '"' + (channel.id === selectedId ? ' selected' : '') + '>' +
        escapeHtml(channel.name) + (channel.connected ? '' : ' · 未对接') + '</option>';
    }).join('');
    select.onchange = function () { openManualPublish(select.value); };
  }

  function openManualPublish(channelId) {
    var channels = getChannels();
    var channel = channels.find(function (item) { return item.id === channelId; }) ||
      channels.find(function (item) { return !item.connected; }) ||
      channels[0];
    if (!channel) return;
    activeManualPlatformId = channel.id;
    renderManualChannelSelect(channel.id);
    var record = getManualPublish(channel.id);
    var title = document.getElementById('geoManualPublishTitle');
    var platform = document.getElementById('geoManualPublishPlatform');
    var account = document.getElementById('geoManualPublishAccount');
    var mediaInput = document.getElementById('geoManualMediaPlatform');
    var input = document.getElementById('geoManualPublishUrl');
    var saved = document.getElementById('geoManualPublishSaved');
    var removeButton = document.getElementById('geoRemoveManualPublish');
    if (title) title.textContent = '手动发布 · ' + channel.name;
    if (platform) platform.textContent = channel.name;
    if (account) account.textContent = channel.account || '未配置发布账号';
    var mediaField = document.getElementById('geoManualMediaField');
    if (mediaField) mediaField.style.display = channel.id === 'media-network' ? '' : 'none';
    renderManualMediaOptions();
    if (mediaInput) {
      mediaInput.value = record && record.mediaPlatform
        ? record.mediaPlatform
        : (channel.id === 'media-network' ? '' : channel.name);
    }
    if (input) input.value = record ? record.url : '';
    if (saved) {
      saved.style.display = record ? 'block' : 'none';
      saved.textContent = record ? '已回填过发布链接，可在这里更新。' : '';
    }
    if (removeButton) removeButton.style.display = record ? '' : 'none';
    openOverlay('geoManualPublishOverlay');
    setTimeout(function () { if (input && record) input.select(); }, 60);
  }

  function geoArticlePlainText() {
    var title = document.getElementById('geoDocumentTitle');
    var editor = document.getElementById('geoArticleEditor');
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

  function copyManualContent(button) {
    var text = geoArticlePlainText();
    if (!text) { notify('当前文章还没有可复制的内容'); return; }
    var oldText = button ? button.textContent : '';
    var complete = function () {
      if (button) {
        button.textContent = '已复制';
        setTimeout(function () { button.textContent = oldText || '复制文章内容'; }, 1200);
      }
      notify('文章内容已复制，请前往对应平台发布');
    };
    fallbackCopy(text);
    complete();
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(function () {});
  }

  function saveManualPublishLink() {
    var channel = getChannels().find(function (item) { return item.id === activeManualPlatformId; });
    var mediaInput = document.getElementById('geoManualMediaPlatform');
    var mediaPlatform = mediaInput ? mediaInput.value.trim() : '';
    var input = document.getElementById('geoManualPublishUrl');
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
    closeManualPublish();
    renderPublishPlatforms(true);
    notify((mediaPlatform || channel.name) + ' 的发布链接已回填');
  }

  function removeManualPublishLink() {
    var channel = getChannels().find(function (item) { return item.id === activeManualPlatformId; });
    if (!channel) return;
    removeManualPublish(channel.id);
    closeManualPublish();
    renderPublishPlatforms(true);
    notify(channel.name + ' 的回填记录已移除');
  }

  function startPublishing() {
    if (!selectedPlatforms.size) return;
    var channels = getChannels().filter(function (channel) {
      return channel.connected && channel.enabled && selectedPlatforms.has(channel.id);
    });
    if (!channels.length) {
      notify('请先选择已对接的发布信源');
      return;
    }
    document.getElementById('geoPublishSelection').style.display = 'none';
    document.getElementById('geoPublishProgress').classList.add('active');
    var rows = document.getElementById('geoProgressRows');
    var button = document.getElementById('geoConfirmPublish');
    rows.innerHTML = channels.map(function (channel) { return '<div class="geo-progress-row" data-geo-progress="' + escapeHtml(channel.id) + '"><strong>' + escapeHtml(channel.name) + '</strong><div class="bar"><span style="width:8%;background:#0d8d82"></span></div><span>适配中</span></div>'; }).join('');
    button.disabled = true;
    button.textContent = '正在发布…';
    channels.forEach(function (channel, index) {
      setTimeout(function () {
        var row = rows.querySelector('[data-geo-progress="' + channel.id + '"]');
        if (!row) return;
        row.querySelector('.bar span').style.width = '58%';
        row.querySelector('span:last-of-type').textContent = '提交中';
      }, 420 + index * 180);
      setTimeout(function () {
        var row = rows.querySelector('[data-geo-progress="' + channel.id + '"]');
        if (!row) return;
        row.querySelector('.bar span').style.width = '100%';
        row.querySelector('.bar span').style.background = '#16a34a';
        row.querySelector('span:last-of-type').textContent = channel.id === 'website' ? '已发布' : '待审核';
      }, 1080 + index * 250);
    });
    setTimeout(function () {
      button.disabled = false;
      button.textContent = '完成';
      button.dataset.geoAction = 'finish-publish';
      saveEditor(false);
      notify('GEO 文章已提交到 ' + channels.length + ' 个信源');
    }, 1600 + channels.length * 250);
  }

  function showDistribution() {
    showInfo({
      title: '分发与引用回流',
      sub: '发布状态与 AI 引用结果统一回到 GEO 文章',
      body: '<table><thead><tr><th>信源</th><th>发布状态</th><th>AI 引用</th><th>最近发现</th></tr></thead><tbody><tr><td class="kw">官网博客</td><td><span class="badge green">已发布</span></td><td>DeepSeek 9 次 · 通义 6 次</td><td>今天 08:00</td></tr><tr><td class="kw">知乎机构号</td><td><span class="badge green">已发布</span></td><td>豆包 4 次 · Kimi 3 次</td><td>昨天 08:00</td></tr><tr><td class="kw">微信公众号</td><td><span class="badge green">已发布</span></td><td>腾讯元宝 7 次</td><td>07-12 08:00</td></tr></tbody></table>',
      foot: '<a class="btn" href="media.html">查看信源策略</a><button class="btn primary" data-geo-action="close-overlay" data-target="geo-content">完成</button>'
    });
  }

  function initImportPage() {
    if (page !== 'import') return;
    var body = document.getElementById('geoImportBody');
    var count = document.getElementById('geoImportWordCount');
    if (body && count) {
      body.addEventListener('input', function () {
        count.textContent = body.textContent.replace(/\s/g, '').length.toLocaleString('zh-CN') + ' 字';
      });
    }
    document.querySelectorAll('input[name="geo-import-question"]').forEach(function (input) {
      input.addEventListener('change', function () {
        document.querySelectorAll('.geo-question-option').forEach(function (option) {
          var radio = option.querySelector('input');
          option.classList.toggle('selected', !!(radio && radio.checked));
        });
      });
    });
  }

  function selectImportMethod(target) {
    var method = target.getAttribute('data-method') || 'paste';
    document.querySelectorAll('.geo-import-methods button').forEach(function (button) {
      button.classList.toggle('active', button === target);
    });
    document.querySelectorAll('[data-import-panel]').forEach(function (panel) {
      panel.classList.toggle('active', panel.getAttribute('data-import-panel') === method);
    });
    var analyze = document.getElementById('geoAnalyzeImportButton');
    if (analyze) analyze.hidden = method !== 'paste';
  }

  function analyzeImportedArticle() {
    var titleInput = document.getElementById('geoImportTitle');
    var body = document.getElementById('geoImportBody');
    var bodyText = body ? body.textContent.trim() : '';
    if (!bodyText) {
      notify('请先粘贴需要进行 GEO 优化的文章内容');
      if (body) body.focus();
      return;
    }
    var detectedTitle = bodyText.split(/\n+/)[0].replace(/^#+\s*/, '').trim();
    if (detectedTitle.length > 42) detectedTitle = detectedTitle.slice(0, 42) + '…';
    var title = titleInput && titleInput.value.trim() ? titleInput.value.trim() : detectedTitle;
    if (titleInput && !titleInput.value.trim()) titleInput.value = title;
    pendingImportDraft = {
      title: title || '未命名导入文章',
      bodyText: bodyText,
      bodyHtml: body ? body.innerHTML : '<p>' + escapeHtml(bodyText) + '</p>',
      source: 'manual'
    };
    var importStage = document.getElementById('geoImportStage');
    var questionStage = document.getElementById('geoQuestionMatchStage');
    if (importStage) importStage.hidden = true;
    if (questionStage) questionStage.hidden = false;
    var flowOne = document.getElementById('geoImportFlowOne');
    var flowTwo = document.getElementById('geoImportFlowTwo');
    if (flowOne) { flowOne.classList.remove('active'); flowOne.classList.add('done'); flowOne.innerHTML = '✓&nbsp; 导入文章'; }
    if (flowTwo) flowTwo.classList.add('active');
    var titlePreview = document.getElementById('geoImportedTitlePreview');
    var metaPreview = document.getElementById('geoImportedMetaPreview');
    if (titlePreview) titlePreview.textContent = pendingImportDraft.title;
    if (metaPreview) metaPreview.textContent = bodyText.replace(/\s/g, '').length.toLocaleString('zh-CN') + ' 字 · 手动导入';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function backToImport() {
    var importStage = document.getElementById('geoImportStage');
    var questionStage = document.getElementById('geoQuestionMatchStage');
    if (importStage) importStage.hidden = false;
    if (questionStage) questionStage.hidden = true;
    var flowOne = document.getElementById('geoImportFlowOne');
    var flowTwo = document.getElementById('geoImportFlowTwo');
    if (flowOne) { flowOne.className = 'active'; flowOne.innerHTML = '1&nbsp; 导入文章'; }
    if (flowTwo) flowTwo.classList.remove('active');
  }

  function enterImportedArticleEditor() {
    if (!pendingImportDraft) {
      notify('请先完成文章内容识别');
      return;
    }
    var manual = document.getElementById('geoManualImportQuestion');
    var selected = document.querySelector('input[name="geo-import-question"]:checked');
    var question = manual && !manual.hidden && manual.value.trim() ? manual.value.trim() : (selected ? selected.value : '');
    if (!question) {
      notify('请选择或输入目标问题');
      return;
    }
    pendingImportDraft.question = question;
    pendingImportDraft.createdAt = Date.now();
    try { localStorage.setItem(IMPORT_DRAFT_STORAGE, JSON.stringify(pendingImportDraft)); } catch (error) {}
    window.location.href = 'editor.html?import=1&id=import-' + pendingImportDraft.createdAt;
  }

  function openCreateArticleDialog() {
    showInfo({
      title: '创建 GEO 文章',
      sub: '选择文章起点，后续均可进行 GEO 检查、AI 优化与发布。',
      dialogClass: 'geo-create-choice-dialog',
      body: '<div class="geo-create-choice-grid">' +
        '<article class="geo-create-choice-card ai"><div class="geo-create-choice-icon">✦</div><h3>AI 生成新文章</h3><p>从目标问题开始，结合品牌资料、知识库和可信来源，AI 自动生成适合 GEO 的文章母稿。</p><div class="geo-create-choice-tags"><span>目标问题</span><span>可信资料</span><span>AI生成</span></div><small>适用于：目前没有文章，希望系统从 0 创作。</small><button data-geo-action="create-new-article" data-target="geo-content">从零开始 <i>→</i></button></article>' +
        '<article class="geo-create-choice-card import"><div class="geo-create-choice-icon">▤</div><h3>优化已有文章</h3><p>已经有文章或母稿？导入现有内容，进行 GEO 评分、内容补强、信源补充和 AI 优化。</p><div class="geo-create-choice-tags"><span>已有内容</span><span>GEO评分</span><span>AI优化</span></div><small>适用于：客户已有文章、运营母稿或官网内容。</small><button data-geo-action="import-existing-article" data-target="geo-content">导入文章 <i>→</i></button></article>' +
      '</div>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button>'
    });
  }

  function handleAction(action, target) {
    if (action === 'open-create-article') openCreateArticleDialog();
    else if (action === 'create-new-article') {
      var nextNew = new URLSearchParams();
      nextNew.set('new', '1');
      if (params.get('fact')) nextNew.set('fact', params.get('fact'));
      window.location.href = 'editor.html?' + nextNew.toString();
    }
    else if (action === 'import-existing-article') window.location.href = 'import.html';
    else if (action === 'select-import-method') selectImportMethod(target);
    else if (action === 'future-import-feature') notify('该导入方式正在建设中，当前请使用「粘贴文章」');
    else if (action === 'analyze-imported-article') analyzeImportedArticle();
    else if (action === 'back-to-import') backToImport();
    else if (action === 'toggle-manual-question') {
      var manualQuestion = document.getElementById('geoManualImportQuestion');
      if (manualQuestion) { manualQuestion.hidden = false; manualQuestion.focus(); }
    }
    else if (action === 'enter-import-editor') enterImportedArticleEditor();
    else if (action === 'generate-draft') generateDraft(target);
    else if (action === 'regenerate-draft') {
      showInfo({
        title: '重新生成母稿',
        sub: '系统将保留当前内容和评分记录',
        body: '<div style="padding:14px;border:1px solid #f0d5ab;border-radius:8px;background:#fff9ef;color:#745529;font-size:12px;line-height:1.7;">重新生成将创建新的文章版本，不会覆盖当前版本。新版本仍会使用当前创作要求和已匹配参考资料。</div>',
        foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="confirm-regenerate" data-target="geo-content">确认并生成新版本</button>'
      });
    }
    else if (action === 'confirm-regenerate') {
      closeOverlays();
      setVersion(2, false);
      notify('已创建新的母稿版本 V2，原 V1 已保留');
    }
    else if (action === 'version-history') {
      showInfo({
        title: '文章版本',
        sub: 'AI 生成和优化均会创建新版本',
        body: '<div class="geo-history-list"><button class="selected"><b>V2 · GEO 优化版</b><span>评分 93</span><small>刚刚 · 当前版本</small></button><button><b>' + (isImportedArticle ? 'V1 · 原始稿' : 'V1 · AI 母稿') + '</b><span>评分 ' + (isImportedArticle ? '72' : '85') + '</span><small>10 分钟前 · 可恢复</small></button></div>',
        foot: '<button class="btn primary" data-geo-action="close-overlay" data-target="geo-content">完成</button>'
      });
    }
    else if (action === 'distribution') showDistribution();
    else if (action === 'preview') showPreview();
    else if (action === 'save') saveEditor(true);
    else if (action === 'publish' || action === 'preview-publish') openPublish();
    else if (action === 'manual-publish') openManualPublish();
    else if (action === 'confirm-publish') startPublishing();
    else if (action === 'finish-publish') { closeOverlays(); notify('发布任务已进入引用追踪'); }
    else if (action === 'copy-manual-content') copyManualContent(target);
    else if (action === 'save-manual-publish') saveManualPublishLink();
    else if (action === 'remove-manual-publish') removeManualPublishLink();
    else if (action === 'close-manual-publish') closeManualPublish();
    else if (action === 'close-overlay') closeOverlays();
    else if (action === 'quote-selection') quoteSelection();
    else if (action === 'insert-source') showInsertSource();
    else if (action === 'insert-source-confirm') {
      var editor = document.getElementById('geoArticleEditor');
      var name = document.getElementById('newSourceName').value;
      var date = document.getElementById('newSourceDate').value;
      editor.insertAdjacentHTML('beforeend', '<p><sup class="geo-citation">[3]</sup> ' + escapeHtml(name) + '，' + escapeHtml(date) + '。</p>');
      document.getElementById('sourceCount').textContent = '信源 3 个';
      closeOverlays();
      scheduleAutosave();
      notify('事实来源已插入');
    }
    else if (action === 'insert-table') insertComparisonTable();
    else if (action === 'toggle-markdown') toggleMarkdown(target);
    else if (action === 'insert-link') insertLink();
    else if (action === 'insert-link-confirm') insertLinkConfirm();
    else if (action === 'add-evidence') showAddEvidence();
    else if (action === 'add-evidence-confirm') {
      var origin = document.getElementById('evidenceOrigin');
      var nameNode = document.getElementById('evidenceName');
      var typeNode = document.getElementById('evidenceType');
      var factNode = document.getElementById('evidenceFact');
      var proofNode = document.getElementById('evidenceProof');
      var joinNode = document.getElementById('evidenceJoinKb');
      var name = nameNode ? nameNode.value.trim() : '';
      var statement = factNode ? factNode.value.trim() : '';
      var isNew = origin && origin.value === 'new';
      if (isNew && !statement) {
        notify('请填写可引用事实');
        return;
      }
      if (name || statement) {
        var button = document.createElement('button');
        button.className = 'selected';
        button.setAttribute('data-geo-toggle', '');
        button.setAttribute('data-target', 'geo-content');
        button.innerHTML = escapeHtml(name || statement.slice(0, 18)) + ' <b>1</b>';
        var picks = document.getElementById('evidencePicks');
        var addBtn = document.querySelector('#evidencePicks [data-geo-action="add-evidence"]');
        if (picks && addBtn) picks.insertBefore(button, addBtn);
        else if (picks) picks.appendChild(button);
      }
      if (isNew && joinNode && joinNode.checked && statement && window.GEOFacts && window.GEOFacts.addCustom) {
        var now = new Date();
        var reviewed = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        window.GEOFacts.addCustom({
          id: 'custom-' + Date.now(),
          custom: true,
          statement: statement,
          type: typeNode && typeNode.value ? typeNode.value : '产品规格',
          biz: '品牌',
          source: proofNode ? proofNode.value.trim() : '',
          trust: '仅内部',
          reviewed: reviewed,
          intents: [],
          articles: []
        });
        notify('已加入可信材料，并写入知识库');
      } else {
        notify('可信材料已加入 AI 上下文');
      }
      closeOverlays();
    }
    else if (/^ai-/.test(action)) runAi(action, target);
    else if (action === 'apply-factcheck') {
      closeOverlays();
      updateScore(null, 92);
      var assistantMessage = document.getElementById('geoAssistantMessage');
      if (assistantMessage) assistantMessage.textContent = '核验建议已应用：弱化无来源断言，并补充材料更新时间。';
      notify('事实核验建议已应用');
    }
    else if (action === 'apply-engines') {
      closeOverlays();
      var editor = document.getElementById('geoArticleEditor');
      editor.insertAdjacentHTML('beforeend', '<h2>给不同角色的快速结论</h2><p><b>结构工程师：</b>优先验证壳体材质、曲面结构和粘接面积。<br><b>工艺工程师：</b>重点检查贴合效率、返修难度和量产一致性。<br><b>采购负责人：</b>同时评估单机用量、损耗和长期供货稳定性。</p>');
      updateScore(91, null);
      scheduleAutosave();
      notify('引擎适配建议已应用');
    }
    else if (action === 'apply-title') {
      var selected = document.querySelector('input[name="geo-title-option"]:checked');
      if (selected) document.getElementById('geoDocumentTitle').value = selected.value;
      closeOverlays();
      scheduleAutosave();
      notify('文章标题已更新');
    }
  }

  function switchEditorTab(target) {
    var tab = target.getAttribute('data-geo-tab');
    document.querySelectorAll('[data-geo-tab]').forEach(function (button) {
      button.classList.toggle('active', button === target);
    });
    document.querySelectorAll('[data-geo-panel]').forEach(function (panel) {
      panel.classList.toggle('active', panel.getAttribute('data-geo-panel') === tab);
    });
  }

  document.addEventListener('click', function (event) {
    var overlay = event.target.classList && event.target.classList.contains('geo-overlay') ? event.target : null;
    var target = event.target.closest('[data-geo-tab], [data-geo-action], [data-geo-command], [data-geo-toggle], [data-geo-filter], [data-geo-platform], [data-geo-switch-tab], [data-geo-goal], [data-geo-version], [data-geo-open-suggestion], [data-geo-ready-action]');
    if (!target && !overlay) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (overlay) {
      if (overlay.id === 'geoManualPublishOverlay') closeManualPublish();
      else closeOverlays();
      return;
    }
    if (target.hasAttribute('data-geo-tab')) { activateEditorTab(target.getAttribute('data-geo-tab')); return; }
    if (target.hasAttribute('data-geo-switch-tab')) {
      activateEditorTab(target.getAttribute('data-geo-switch-tab'));
      if (target.closest('.geo-overlay')) closeOverlays();
      return;
    }
    if (target.hasAttribute('data-geo-ready-action')) { handleReadyAction(target.getAttribute('data-geo-ready-action')); return; }
    if (target.hasAttribute('data-geo-goal')) {
      document.querySelectorAll('[data-geo-goal]').forEach(function (button) { button.classList.remove('selected'); });
      target.classList.add('selected');
      var summary = document.getElementById('geoSummaryGoal');
      if (summary) summary.textContent = (target.querySelector('span') || target).textContent.trim();
      updateRecommendationRecognition();
      return;
    }
    if (target.hasAttribute('data-geo-version')) {
      var version = target.getAttribute('data-geo-version');
      if (version === '3') { notify('V3 尚未创建'); return; }
      setVersion(version, version === '2');
      notify('已切换到 V' + version + (version === '1' ? ' · AI 母稿' : ' · GEO 优化版'));
      return;
    }
    if (target.hasAttribute('data-geo-open-suggestion')) {
      activateEditorTab('suggestions');
      var issue = document.querySelector('[data-suggestion-id="' + target.getAttribute('data-geo-open-suggestion') + '"]');
      if (issue) { issue.scrollIntoView({ behavior: 'smooth', block: 'center' }); issue.classList.add('geo-issue-focus'); setTimeout(function () { issue.classList.remove('geo-issue-focus'); }, 1200); }
      return;
    }
    if (target.hasAttribute('data-geo-command')) { runCommand(target); return; }
    if (target.hasAttribute('data-geo-toggle')) {
      target.classList.toggle('selected');
      notify(target.textContent.trim() + (target.classList.contains('selected') ? ' 已启用' : ' 已取消'));
      return;
    }
    if (target.hasAttribute('data-geo-filter')) {
      document.querySelectorAll('[data-geo-filter]').forEach(function (button) { button.classList.remove('active'); });
      target.classList.add('active');
      filterRows();
      return;
    }
    if (target.hasAttribute('data-geo-platform')) {
      var id = target.getAttribute('data-geo-platform');
      if (target.classList.contains('manual')) { openManualPublish(id); return; }
      if (target.classList.contains('paused')) { notify('该平台已停用，请先到共享分发平台启用'); return; }
      if (target.classList.contains('offline')) { notify('该平台当前不可发布'); return; }
      if (selectedPlatforms.has(id)) selectedPlatforms.delete(id); else selectedPlatforms.add(id);
      target.classList.toggle('selected', selectedPlatforms.has(id));
      updatePublishButton();
      return;
    }
    handleAction(target.getAttribute('data-geo-action'), target);
  }, true);

  document.addEventListener('change', function (event) {
    if (!event.target) return;
    if (event.target.id === 'evidenceOrigin') syncEvidenceOrigin();
    if (event.target.id === 'evidenceFactPick') {
      var picked = window.GEOFacts && window.GEOFacts.find(event.target.value);
      fillEvidenceFromFact(picked);
    }
    if (event.target.id === 'geoBlockType') applyBlockType(event.target);
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      if (document.getElementById('geoManualPublishOverlay') && document.getElementById('geoManualPublishOverlay').classList.contains('open')) closeManualPublish();
      else closeOverlays();
    }
    if ((event.key === 'Enter' || event.key === ' ') && event.target && event.target.hasAttribute('data-geo-platform')) {
      event.preventDefault();
      event.target.click();
    }
  });

  initListPage();
  initImportPage();
  initEditor();
})();
