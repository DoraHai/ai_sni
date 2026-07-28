(function () {
  'use strict';

  var page = document.body.getAttribute('data-geo-page') || '';
  var params = new URLSearchParams(window.location.search);
  var CHANNEL_STORAGE = 'growthEngine.seo.channels.v1';
  var MANUAL_PUBLISH_STORAGE = 'growthEngine.manualPublishes.v1';
  var MANUAL_MEDIA_STORAGE = 'growthEngine.manualMediaPlatforms.v1';
  var selectedPlatforms = new Set();
  var activeManualPlatformId = '';
  var autosaveTimer = null;

  var fallbackChannels = [
    { id: 'website', name: '官网 CMS', account: 'example.com / 官网博客', connected: true, enabled: true, review: '内容负责人审核' },
    { id: 'wechat', name: '微信公众号', account: 'Growth Sniper 研究院', connected: true, enabled: true, review: '品牌负责人审核' },
    { id: 'baijia', name: '百家号', account: 'Growth Sniper 官方', connected: true, enabled: true, review: '平台审核' },
    { id: 'tieba', name: '百度贴吧', account: 'Growth Sniper 品牌吧', connected: true, enabled: true, review: '运营审核' },
    { id: 'toutiao', name: '今日头条', account: '尚未授权', connected: false, enabled: false, review: '平台审核' },
    { id: 'lofter', name: '网易 LOFTER', account: 'Growth Sniper 官方', connected: true, enabled: true, review: '运营审核' },
    { id: 'zhihu', name: '知乎', account: 'Growth Sniper 科技', connected: true, enabled: true, review: '运营审核' },
    { id: 'sohu', name: '搜狐号', account: 'Growth Sniper', connected: true, enabled: true, review: '允许自动发布' },
    { id: 'penguin', name: '企鹅号', account: 'Growth Sniper 科技', connected: true, enabled: true, review: '平台审核' },
    { id: 'netease', name: '网易号', account: 'Growth Sniper 增长研究', connected: true, enabled: true, review: '平台审核' },
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
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(editorStorageKey())); } catch (error) {}
    if (saved && !params.get('new')) {
      document.getElementById('geoDocumentTitle').value = saved.title;
      document.getElementById('geoArticleEditor').innerHTML = saved.body;
      document.getElementById('geoEditorSub').textContent += ' · 已恢复上次草稿';
    }
    ['geoDocumentTitle', 'geoArticleEditor'].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.addEventListener('input', scheduleAutosave);
    });
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

  function runCommand(button) {
    var editor = document.getElementById('geoArticleEditor');
    if (!editor) return;
    editor.focus();
    try { document.execCommand(button.getAttribute('data-geo-command'), false, button.getAttribute('data-value') || null); } catch (error) {}
    scheduleAutosave();
  }

  function updateScore(citation, trust) {
    var citationNode = document.getElementById('citationScore');
    var trustNode = document.getElementById('trustScore');
    if (citationNode && citation != null) citationNode.textContent = Number(citation).toFixed(2);
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
      }
      button.disabled = false;
      button.textContent = oldText;
      scheduleAutosave();
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

  function showAddEvidence() {
    showInfo({
      title: '添加可信材料',
      sub: '材料会进入事实核验与 AI 润色上下文',
      body: '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;"><label class="geo-field-label" style="margin:0;">材料类型<input class="geo-input" id="evidenceType" value="应用案例" style="margin-top:5px;"></label><label class="geo-field-label" style="margin:0;">材料名称<input class="geo-input" id="evidenceName" value="机器人外壳样件粘接测试" style="margin-top:5px;"></label><label class="geo-field-label" style="grid-column:1/-1;margin:0;">来源 / 链接<input class="geo-input" id="evidenceSource" value="内部知识库 · 已获匿名引用授权" style="margin-top:5px;"></label><label class="geo-field-label" style="grid-column:1/-1;margin:0;">可引用事实<textarea class="geo-prompt-input" id="evidenceFact" style="min-height:72px;margin-top:5px;">客户使用真实机器人外壳材料完成试贴，并记录了剥离强度、冷热循环和外观缝隙表现。</textarea></label></div>',
      foot: '<button class="btn" data-geo-action="close-overlay" data-target="geo-content">取消</button><button class="btn primary" data-geo-action="add-evidence-confirm" data-target="geo-content">加入可信材料</button>'
    });
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
    paper.innerHTML = '<h1>' + escapeHtml(title.value) + '</h1><p style="color:#7a838f;font-size:11px;">作者：Growth Sniper 内容研究组 · 更新于 2026-07-14 · 已核验信源 3 个</p>' + editor.innerHTML;
    openOverlay('geoPreviewOverlay');
  }

  function renderPublishPlatforms(preserveSelection) {
    var container = document.getElementById('geoPublishPlatforms');
    if (!container) return;
    var channels = getChannels();
    if (preserveSelection) {
      selectedPlatforms = new Set(channels.filter(function (channel) {
        return channel.connected && channel.enabled && selectedPlatforms.has(channel.id);
      }).map(function (channel) { return channel.id; }));
    } else {
      selectedPlatforms = new Set(channels.filter(function (channel) { return channel.connected && channel.enabled && ['website', 'zhihu', 'wechat'].indexOf(channel.id) >= 0; }).map(function (channel) { return channel.id; }));
    }
    container.innerHTML = channels.map(function (channel) {
      var manual = !channel.connected;
      var paused = channel.connected && !channel.enabled;
      var selected = selectedPlatforms.has(channel.id);
      var manualRecord = manual ? getManualPublish(channel.id) : null;
      var modeClass = manual ? ' manual' + (manualRecord ? ' manual-recorded' : '') : (paused ? ' offline paused' : '');
      var modeBadge = manual ? '<span class="geo-publish-mode-badge">' + (manualRecord ? '已回填链接' : '手动发布') + '</span>' : '';
      var accountLabel = manualRecord && manualRecord.mediaPlatform ? manualRecord.mediaPlatform : (channel.account || '待配置账号');
      var detail = manual
        ? (manualRecord ? '已保存公开网址，点击可查看或修改' : '未对接：人工发布后回填网址')
        : (paused ? '平台已停用，请先到平台管理中启用' : suitability[channel.id] || '补充内容覆盖');
      return '<div class="geo-publish-platform' + (selected ? ' selected' : '') + modeClass + '" data-geo-platform="' + escapeHtml(channel.id) + '" role="button" tabindex="0"><i></i><strong>' + escapeHtml(channel.name) + '</strong>' + modeBadge + '<small>' + escapeHtml(accountLabel) + '</small><em>' + escapeHtml(detail) + '</em></div>';
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

  function openManualPublish(channelId) {
    var channel = getChannels().find(function (item) { return item.id === channelId; });
    if (!channel) return;
    activeManualPlatformId = channel.id;
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
    var channels = getChannels().filter(function (channel) { return selectedPlatforms.has(channel.id); });
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
        row.querySelector('span:last-child').textContent = '提交中';
      }, 420 + index * 180);
      setTimeout(function () {
        var row = rows.querySelector('[data-geo-progress="' + channel.id + '"]');
        if (!row) return;
        row.querySelector('.bar span').style.width = '100%';
        row.querySelector('.bar span').style.background = '#16a34a';
        row.querySelector('span:last-child').textContent = channel.id === 'website' ? '已发布' : '待审核';
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

  function handleAction(action, target) {
    if (action === 'distribution') showDistribution();
    else if (action === 'preview') showPreview();
    else if (action === 'save') saveEditor(true);
    else if (action === 'publish' || action === 'preview-publish') openPublish();
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
    else if (action === 'add-evidence') showAddEvidence();
    else if (action === 'add-evidence-confirm') {
      var name = document.getElementById('evidenceName').value.trim();
      if (name) {
        var button = document.createElement('button');
        button.className = 'selected';
        button.setAttribute('data-geo-toggle', '');
        button.setAttribute('data-target', 'geo-content');
        button.innerHTML = escapeHtml(name) + ' <b>1</b>';
        document.getElementById('evidencePicks').insertBefore(button, document.querySelector('[data-geo-action="add-evidence"]'));
      }
      closeOverlays();
      notify('可信材料已加入 AI 上下文');
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
    var target = event.target.closest('[data-geo-tab], [data-geo-action], [data-geo-command], [data-geo-toggle], [data-geo-filter], [data-geo-platform]');
    if (!target && !overlay) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (overlay) {
      if (overlay.id === 'geoManualPublishOverlay') closeManualPublish();
      else closeOverlays();
      return;
    }
    if (target.hasAttribute('data-geo-tab')) { switchEditorTab(target); return; }
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
  initEditor();
})();
