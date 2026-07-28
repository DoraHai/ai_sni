(function () {
  'use strict';

  if (window.__GE_PROTOTYPE_RUNTIME_V2__) return;
  window.__GE_PROTOTYPE_RUNTIME_V2__ = true;

  var activeMenu = null;
  var activeMask = null;
  var activeDrawer = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function cleanLabel(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function currentPageName() {
    var heading = document.querySelector('.topbar h1, main h1, .content h1');
    return heading ? cleanLabel(heading.textContent) : cleanLabel(document.title);
  }

  function injectStyles() {
    if (document.getElementById('ge2-runtime-style')) return;
    var style = document.createElement('style');
    style.id = 'ge2-runtime-style';
    style.textContent =
      '.ge2-toast-stack{position:fixed;right:22px;bottom:22px;z-index:12020;display:grid;gap:9px;pointer-events:none}' +
      '.ge2-toast{min-width:280px;max-width:380px;display:grid;grid-template-columns:28px 1fr;gap:10px;align-items:center;padding:12px 14px;background:#172033;color:#fff;border:1px solid rgba(255,255,255,.13);border-radius:8px;box-shadow:0 16px 42px rgba(18,25,39,.24);font-size:12.5px;opacity:0;transform:translateY(8px);transition:.2s}' +
      '.ge2-toast.show{opacity:1;transform:translateY(0)}.ge2-toast.success{background:#123c32}.ge2-toast.warn{background:#563917}' +
      '.ge2-toast-icon{width:28px;height:28px;display:grid;place-items:center;border-radius:6px;background:rgba(255,255,255,.12);font-weight:800}' +
      '.ge2-mask{position:fixed;inset:0;z-index:12000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(17,24,39,.48);backdrop-filter:blur(2px);opacity:0;transition:.16s}' +
      '.ge2-mask.show{opacity:1}.ge2-dialog{width:min(620px,calc(100vw - 32px));max-height:min(84vh,760px);display:flex;flex-direction:column;background:#fff;border:1px solid #dfe4ec;border-radius:8px;box-shadow:0 26px 80px rgba(18,25,39,.28);transform:translateY(10px);transition:.18s;overflow:hidden}' +
      '.ge2-mask.show .ge2-dialog{transform:translateY(0)}.ge2-dialog-head{display:flex;align-items:flex-start;gap:16px;padding:18px 20px 16px;border-bottom:1px solid #e7eaf0}' +
      '.ge2-dialog-head h2{margin:0;color:#1e2330;font-size:17px;letter-spacing:0}.ge2-dialog-head p{margin:4px 0 0;color:#7a8393;font-size:11.5px}' +
      '.ge2-close{margin-left:auto;width:30px;height:30px;border:0;background:#f3f5f8;color:#687184;border-radius:6px;font-size:18px;cursor:pointer}' +
      '.ge2-dialog-body{padding:18px 20px;overflow:auto}.ge2-dialog-foot{display:flex;justify-content:flex-end;gap:9px;padding:13px 20px;border-top:1px solid #e7eaf0;background:#fafbfc}' +
      '.ge2-button{min-height:35px;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:8px 14px;border:1px solid #dfe4ec;border-radius:7px;background:#fff;color:#293142;font:inherit;font-size:12.5px;font-weight:650;cursor:pointer}' +
      '.ge2-button:hover{background:#f6f8fb}.ge2-button.primary{border-color:#2563eb;background:#2563eb;color:#fff}.ge2-button.primary:hover{background:#1d4ed8}' +
      '.ge2-button.danger{border-color:#f1c8c8;color:#c73737;background:#fff8f8}.ge2-button[disabled]{opacity:.55;cursor:not-allowed}' +
      '.ge2-context{display:flex;align-items:flex-start;gap:10px;margin-bottom:16px;padding:11px 12px;border-left:3px solid #2563eb;background:#f3f6fc;color:#5f697b;font-size:11.5px;line-height:1.6}' +
      '.ge2-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:13px}.ge2-field{display:grid;gap:6px}.ge2-field.full{grid-column:1/-1}' +
      '.ge2-field label{color:#4f596b;font-size:11.5px;font-weight:650}.ge2-field label em{color:#dc2626;font-style:normal}' +
      '.ge2-field input,.ge2-field textarea,.ge2-field select{width:100%;border:1px solid #dfe4ec;border-radius:7px;background:#fff;padding:9px 10px;color:#1e2330;font:inherit;font-size:12.5px;outline:none}' +
      '.ge2-field textarea{min-height:86px;resize:vertical;line-height:1.55}.ge2-field input:focus,.ge2-field textarea:focus,.ge2-field select:focus{border-color:#2563eb;box-shadow:0 0 0 3px #eff4ff}' +
      '.ge2-field .invalid{border-color:#dc2626}.ge2-checks{display:flex;flex-wrap:wrap;gap:8px}.ge2-checks label{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid #e1e5ec;border-radius:6px;background:#fafbfc;font-size:11.5px;cursor:pointer}' +
      '.ge2-upload{display:grid;place-items:center;min-height:148px;padding:18px;border:1px dashed #bfc8d7;border-radius:8px;background:#f8fafc;text-align:center;cursor:pointer}' +
      '.ge2-upload strong{display:block;color:#293142;font-size:13px}.ge2-upload span{display:block;margin-top:5px;color:#8992a3;font-size:11px}.ge2-upload.has-file{border-color:#16a34a;background:#f1fbf6}' +
      '.ge2-progress{height:7px;overflow:hidden;margin:16px 0;border-radius:3px;background:#edf0f5}.ge2-progress i{display:block;width:0;height:100%;background:#2563eb;transition:width .32s ease}' +
      '.ge2-step-list{display:grid;gap:8px}.ge2-step{display:grid;grid-template-columns:24px 1fr auto;gap:9px;align-items:center;padding:9px 10px;border:1px solid #e8ebf1;border-radius:7px;color:#6f7888;font-size:12px}' +
      '.ge2-step b{width:24px;height:24px;display:grid;place-items:center;border-radius:6px;background:#f0f3f7;color:#7e8797;font-size:10px}.ge2-step.active{border-color:#bfd1fb;background:#f4f7ff;color:#2e3b55}.ge2-step.active b{background:#2563eb;color:#fff}.ge2-step.done b{background:#dcf6e7;color:#15803d}.ge2-step small{color:#9aa2b1}' +
      '.ge2-success{padding:22px 10px;text-align:center}.ge2-success-icon{width:48px;height:48px;display:grid;place-items:center;margin:0 auto 12px;border-radius:50%;background:#e6f7ed;color:#15803d;font-size:23px;font-weight:800}.ge2-success h3{margin:0 0 6px;font-size:16px}.ge2-success p{margin:0;color:#778192;font-size:12px}' +
      '.ge2-menu{position:fixed;z-index:12030;min-width:190px;padding:5px;background:#fff;border:1px solid #dfe4ec;border-radius:8px;box-shadow:0 14px 34px rgba(18,25,39,.16)}' +
      '.ge2-option{width:100%;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:9px 10px;border:0;border-radius:6px;background:transparent;color:#3c4658;font:inherit;font-size:12px;text-align:left;cursor:pointer}.ge2-option:hover{background:#f2f5fa;color:#1d4ed8}.ge2-option.active:after{content:"✓";color:#2563eb;font-weight:800}' +
      '.ge2-drawer-mask{position:fixed;inset:0;z-index:11990;background:rgba(17,24,39,.34);opacity:0;transition:.16s}.ge2-drawer-mask.show{opacity:1}' +
      '.ge2-drawer{position:absolute;top:0;right:0;width:min(440px,92vw);height:100%;display:flex;flex-direction:column;background:#fff;border-left:1px solid #dfe4ec;box-shadow:-18px 0 54px rgba(18,25,39,.17);transform:translateX(100%);transition:.2s}' +
      '.ge2-drawer-mask.show .ge2-drawer{transform:translateX(0)}.ge2-drawer-head{display:flex;align-items:flex-start;gap:12px;padding:19px 20px;border-bottom:1px solid #e7eaf0}.ge2-drawer-head h2{margin:0;font-size:16px}.ge2-drawer-head p{margin:4px 0 0;color:#7a8393;font-size:11.5px}.ge2-drawer-body{flex:1;overflow:auto;padding:16px 20px}.ge2-drawer-foot{display:flex;justify-content:flex-end;gap:8px;padding:13px 20px;border-top:1px solid #e7eaf0}' +
      '.ge2-list{display:grid;gap:9px}.ge2-list-item{display:grid;grid-template-columns:34px 1fr auto;gap:10px;align-items:center;padding:11px;border:1px solid #e5e8ee;border-radius:7px}.ge2-list-mark{width:34px;height:34px;display:grid;place-items:center;border-radius:7px;background:#eef3ff;color:#2563eb;font-size:11px;font-weight:800}.ge2-list-item b{display:block;color:#2b3445;font-size:12.5px}.ge2-list-item span{display:block;margin-top:2px;color:#8992a3;font-size:10.5px}.ge2-list-item em{color:#2563eb;font-size:11px;font-style:normal;font-weight:650}' +
      '.ge2-toggle-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid #edf0f5}.ge2-toggle-row b{display:block;font-size:12px}.ge2-toggle-row span{display:block;color:#8a93a3;font-size:10.5px}.ge2-switch{width:38px;height:22px;border:0;border-radius:11px;background:#cfd5df;padding:2px;cursor:pointer}.ge2-switch i{display:block;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s}.ge2-switch.on{background:#2563eb}.ge2-switch.on i{transform:translateX(16px)}' +
      '@media(max-width:680px){.ge2-mask{padding:12px}.ge2-form-grid{grid-template-columns:1fr}.ge2-field.full{grid-column:auto}.ge2-toast-stack{left:12px;right:12px}.ge2-toast{min-width:0;max-width:none}}';
    document.head.appendChild(style);
  }

  function toast(message, type) {
    var stack = document.querySelector('.ge2-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'ge2-toast-stack';
      document.body.appendChild(stack);
    }
    var item = document.createElement('div');
    item.className = 'ge2-toast ' + (type || 'success');
    item.innerHTML = '<span class="ge2-toast-icon">' + (type === 'warn' ? '!' : '✓') + '</span><span>' + escapeHtml(message) + '</span>';
    stack.appendChild(item);
    requestAnimationFrame(function () { item.classList.add('show'); });
    setTimeout(function () {
      item.classList.remove('show');
      setTimeout(function () { item.remove(); }, 220);
    }, 2400);
  }

  function closeMenu() {
    if (activeMenu) activeMenu.remove();
    activeMenu = null;
  }

  function closeMask() {
    if (!activeMask) return;
    var mask = activeMask;
    activeMask = null;
    mask.classList.remove('show');
    setTimeout(function () { mask.remove(); }, 180);
  }

  function closeDrawer() {
    if (!activeDrawer) return;
    var drawer = activeDrawer;
    activeDrawer = null;
    drawer.classList.remove('show');
    setTimeout(function () { drawer.remove(); }, 180);
  }

  function showDialog(options) {
    closeMask();
    var mask = document.createElement('div');
    mask.className = 'ge2-mask';
    mask.innerHTML =
      '<section class="ge2-dialog" role="dialog" aria-modal="true" aria-label="' + escapeHtml(options.title) + '">' +
        '<header class="ge2-dialog-head"><div><h2>' + escapeHtml(options.title) + '</h2><p>' + escapeHtml(options.subtitle || currentPageName()) + '</p></div><button class="ge2-close" type="button" aria-label="关闭">×</button></header>' +
        '<div class="ge2-dialog-body">' + (options.body || '') + '</div>' +
        '<footer class="ge2-dialog-foot">' +
          (options.secondary === false ? '' : '<button class="ge2-button ge2-secondary" type="button">' + escapeHtml(options.secondary || '取消') + '</button>') +
          (options.primary ? '<button class="ge2-button primary ge2-primary" type="button">' + escapeHtml(options.primary) + '</button>' : '') +
        '</footer>' +
      '</section>';
    document.body.appendChild(mask);
    activeMask = mask;
    requestAnimationFrame(function () { mask.classList.add('show'); });

    var closeButton = mask.querySelector('.ge2-close');
    var secondary = mask.querySelector('.ge2-secondary');
    var primary = mask.querySelector('.ge2-primary');
    closeButton.addEventListener('click', closeMask);
    if (secondary) secondary.addEventListener('click', closeMask);
    mask.addEventListener('click', function (event) { if (event.target === mask) closeMask(); });
    if (primary) {
      primary.addEventListener('click', function () {
        var result = options.onPrimary ? options.onPrimary({ mask: mask, body: mask.querySelector('.ge2-dialog-body'), primary: primary, close: closeMask }) : true;
        if (result !== false) closeMask();
      });
    }
    return { mask: mask, body: mask.querySelector('.ge2-dialog-body'), primary: primary, close: closeMask };
  }

  function field(label, type, placeholder, required, extraClass) {
    var req = required ? ' <em>*</em>' : '';
    var attr = required ? ' data-required="true"' : '';
    var control;
    if (type === 'textarea') {
      control = '<textarea placeholder="' + escapeHtml(placeholder || '') + '"' + attr + '></textarea>';
    } else if (type && type.indexOf('select:') === 0) {
      var options = type.slice(7).split('|').map(function (value) { return '<option>' + escapeHtml(value) + '</option>'; }).join('');
      control = '<select' + attr + '>' + options + '</select>';
    } else {
      control = '<input type="' + escapeHtml(type || 'text') + '" placeholder="' + escapeHtml(placeholder || '') + '"' + attr + '>';
    }
    return '<div class="ge2-field ' + (extraClass || '') + '"><label>' + escapeHtml(label) + req + '</label>' + control + '</div>';
  }

  function entityConfig(label) {
    if (/关键词|监控词|词包/.test(label)) return { name: '关键词', fields: field('关键词', 'text', '例如：智能客服系统价格', true, 'full') + field('业务分组', 'select:核心产品|内容机会|竞品替代|品牌词', '', true) + field('搜索意图', 'select:商业意图|决策意图|信息意图|品牌意图', '', true) + field('目标落地页', 'text', '/product/pricing', false, 'full'), checks: ['百度', 'Google', 'Bing', '360', '搜狗'] };
    if (/提问|Prompt/.test(label)) return { name: '监控提问', fields: field('用户提问', 'textarea', '例如：有哪些适合中小企业的智能客服系统？', true, 'full') + field('业务主题', 'select:智能客服|CRM|表单工具|数据分析', '', true) + field('目标地区', 'select:全国|北京|上海|广东|海外', '', true), checks: ['DeepSeek', '豆包', 'Kimi', '通义千问', '腾讯元宝'] };
    if (/文章/.test(label)) return { name: '文章', fields: field('文章标题', 'text', '输入主题或标题', true, 'full') + field('文章类型', 'select:原创文章|文章改写|行业观点|案例稿', '', true) + field('目标渠道', 'select:官网|行业媒体|知乎|百家号', '', true) + field('目标关键词', 'text', '多个关键词用逗号分隔', false, 'full') + field('写作要求', 'textarea', '补充事实、口吻和引用要求', false, 'full') };
    if (/竞品/.test(label)) return { name: '竞争对手', fields: field('品牌名称', 'text', '例如：竞品 A', true) + field('品牌网站', 'url', 'https://competitor.com', false) + field('竞品级别', 'select:核心竞品|潜在竞品|行业标杆', '', true) + field('关注范围', 'select:全部关键词|核心产品词|品牌对比词', '', true) };
    if (/数据源|账号|引擎|接入/.test(label)) return { name: '数据连接', fields: field('连接类型', 'select:百度推广|Google Ads|百度统计 / GA|搜索资源平台|CRM / 表单|AI 引擎', '', true, 'full') + field('账号名称', 'text', '用于区分多个连接', true) + field('同步范围', 'select:最近 30 天|最近 90 天|全部历史数据', '', true) + field('备注', 'textarea', '可填写负责人或数据口径', false, 'full') };
    if (/落地页/.test(label)) return { name: '落地页', fields: field('页面 URL', 'url', 'https://example.com/landing', true, 'full') + field('转化目标', 'select:表单提交|在线咨询|电话拨打|资料下载', '', true) + field('所属计划', 'text', '选择或填写 SEM 计划', false) };
    if (/意图/.test(label)) return { name: '意图', fields: field('意图名称', 'text', '例如：智能客服系统价格', true, 'full') + field('决策阶段', 'select:认知|比较|决策|复购', '', true) + field('优先级', 'select:高|中|低', '', true) + field('推荐渠道', 'select:SEM|SEO|GEO|多渠道', '', true) };
    if (/目标用户/.test(label)) return { name: '目标用户', fields: field('用户画像名称', 'text', '例如：中小企业市场负责人', true, 'full') + field('行业', 'text', '企业服务 / 制造 / 电商', true) + field('决策角色', 'select:决策者|影响者|使用者', '', true) + field('核心需求', 'textarea', '描述其目标、痛点和采购关注点', true, 'full') };
    if (/待办|任务/.test(label)) return { name: '待办任务', fields: field('任务名称', 'text', '填写需要处理的事项', true, 'full') + field('所属模块', 'select:SEM|SEO|GEO|诊断中心', '', true) + field('负责人', 'text', '选择负责人', true) + field('截止日期', 'date', '', true) };
    if (/信源|媒体/.test(label)) return { name: '信源计划', fields: field('计划名称', 'text', '例如：行业媒体案例稿发布', true, 'full') + field('信源类型', 'select:官网|行业媒体|知乎|百科|技术刊物', '', true) + field('目标 AI', 'select:全部引擎|DeepSeek|豆包|Kimi|通义千问', '', true) + field('计划日期', 'date', '', true) };
    if (/标注/.test(label)) return { name: '结构化标注', fields: field('页面 URL', 'url', 'https://example.com/product', true, 'full') + field('标注类型', 'select:Organization|Product|Article|FAQPage|BreadcrumbList', '', true) + field('负责人', 'text', '选择负责人', false) };
    return { name: '记录', fields: field('名称', 'text', '填写名称', true, 'full') + field('类型', 'select:常规|重点|临时', '', true) + field('说明', 'textarea', '补充详细信息', false, 'full') };
  }

  function validateRequired(root) {
    var valid = true;
    root.querySelectorAll('[data-required="true"]').forEach(function (input) {
      var empty = !String(input.value || '').trim();
      input.classList.toggle('invalid', empty);
      if (empty) valid = false;
    });
    return valid;
  }

  function temporarilyComplete(button, text) {
    var original = button.textContent;
    button.textContent = text || '✓ 已完成';
    button.disabled = true;
    setTimeout(function () { button.textContent = original; button.disabled = false; }, 1600);
  }

  function incrementFirstMetric() {
    var metric = document.querySelector('.card.stat .value, .metric .value, .kpi .value');
    if (!metric) return;
    var raw = cleanLabel(metric.textContent).replace(/,/g, '');
    if (!/^\d+$/.test(raw)) return;
    metric.textContent = (Number(raw) + 1).toLocaleString('zh-CN');
  }

  function openCreate(label, button) {
    var config = entityConfig(label);
    var checks = config.checks ? '<div class="ge2-field full"><label>监控平台 <em>*</em></label><div class="ge2-checks">' + config.checks.map(function (item, index) { return '<label><input type="checkbox" ' + (index < 3 ? 'checked' : '') + '> ' + escapeHtml(item) + '</label>'; }).join('') + '</div></div>' : '';
    var dialog = showDialog({
      title: label.indexOf('新增') >= 0 || label.indexOf('添加') >= 0 || label.indexOf('新建') >= 0 || label.indexOf('接入') >= 0 || label.indexOf('绑定') >= 0 ? label.replace(/^\+\s*/, '') : '新增' + config.name,
      subtitle: currentPageName() + ' · 新建后立即写入当前项目',
      body: '<div class="ge2-context"><b>填写后将同步到当前模块的数据列表；带 * 的项目为必填。</b></div><div class="ge2-form-grid">' + config.fields + checks + '</div>',
      primary: '确认创建',
      onPrimary: function (ctx) {
        if (!validateRequired(ctx.body)) { toast('请先补全必填信息', 'warn'); return false; }
        incrementFirstMetric();
        temporarilyComplete(button, '✓ 已创建');
        toast(config.name + '已创建，并加入当前列表');
        return true;
      }
    });
    var firstInput = dialog.body.querySelector('input, textarea, select');
    if (firstInput) setTimeout(function () { firstInput.focus(); }, 50);
  }

  function openImport(label, button) {
    if (/文章评分/.test(label)) {
      openArticleScoreUpload(label, button);
      return;
    }
    var dialog = showDialog({
      title: label,
      subtitle: currentPageName() + ' · 支持 CSV、XLSX 与历史项目数据',
      body: '<div class="ge2-context"><b>系统会先校验字段并展示冲突项，确认后才写入当前项目。</b></div><div class="ge2-upload" tabindex="0"><strong>选择文件或拖到这里</strong><span>最大 20MB · CSV / XLSX / JSON</span><input type="file" accept=".csv,.xlsx,.xls,.json" hidden></div><div class="ge2-form-grid" style="margin-top:14px">' + field('重复数据', 'select:跳过重复项|覆盖旧数据|保留两个版本', '', true) + field('数据归属', 'select:当前项目|新建项目', '', true) + '</div>',
      primary: '校验并导入',
      onPrimary: function (ctx) {
        var fileName = ctx.body.querySelector('.ge2-upload').dataset.fileName || '示例数据.xlsx';
        ctx.close();
        runProgress('导入 ' + fileName, button, ['读取文件与字段', '校验重复与格式', '写入当前项目', '更新数据视图']);
        return false;
      }
    });
    var upload = dialog.body.querySelector('.ge2-upload');
    var input = upload.querySelector('input');
    upload.addEventListener('click', function () { input.click(); });
    upload.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') input.click(); });
    input.addEventListener('change', function () {
      if (!input.files || !input.files[0]) return;
      upload.dataset.fileName = input.files[0].name;
      upload.classList.add('has-file');
      upload.querySelector('strong').textContent = input.files[0].name;
      upload.querySelector('span').textContent = '文件已选择，点击“校验并导入”继续';
    });
  }

  function openArticleScoreUpload(label, button) {
    var dialog = showDialog({
      title: label,
      subtitle: currentPageName() + ' · 支持文章文件、正文粘贴与历史文章',
      body:
        '<div class="ge2-context"><b>文章评分读取的是正文内容，不要求整理成表格。只有批量导入历史任务时才需要 CSV / XLSX。</b></div>' +
        '<div class="ge2-upload" tabindex="0"><strong>选择文章文件或拖到这里</strong><span>最大 20MB · DOCX / MD / TXT / HTML / PDF</span><input type="file" accept=".doc,.docx,.md,.markdown,.txt,.html,.htm,.pdf" hidden></div>' +
        '<div class="ge2-form-grid" style="margin-top:14px">' +
          field('评分来源', 'select:上传文章文件|粘贴正文|从文章库选择|输入文章 URL', '', true) +
          field('评分目标', 'select:SEO 友好度|AI 友好度|SEO + GEO 综合评分', '', true) +
          '<div class="ge2-field full"><label>可选：直接粘贴正文</label><textarea placeholder="也可以把文章正文粘贴到这里，系统将直接进行评分和优化建议生成。"></textarea></div>' +
        '</div>',
      primary: '开始评分',
      onPrimary: function (ctx) {
        var upload = ctx.body.querySelector('.ge2-upload');
        var pasted = cleanLabel((ctx.body.querySelector('textarea') || {}).value || '');
        var source = upload.dataset.fileName || (pasted ? '粘贴正文' : '示例文章.docx');
        ctx.close();
        runProgress('评分 ' + source, button, ['读取文章正文', '识别标题、结构与关键词', '计算 SEO / GEO 分数', '生成优化建议']);
        return false;
      }
    });
    var upload = dialog.body.querySelector('.ge2-upload');
    var input = upload.querySelector('input');
    upload.addEventListener('click', function () { input.click(); });
    upload.addEventListener('keydown', function (event) { if (event.key === 'Enter' || event.key === ' ') input.click(); });
    input.addEventListener('change', function () {
      if (!input.files || !input.files[0]) return;
      upload.dataset.fileName = input.files[0].name;
      upload.classList.add('has-file');
      upload.querySelector('strong').textContent = input.files[0].name;
      upload.querySelector('span').textContent = '文件已选择，点击“开始评分”继续';
    });
  }

  function openExport(label, button) {
    showDialog({
      title: label,
      subtitle: currentPageName() + ' · 导出将保留当前筛选条件',
      body: '<div class="ge2-context"><b>导出内容仅包含当前项目的演示数据，不会发送到外部服务。</b></div><div class="ge2-form-grid">' + field('文件格式', 'select:Excel (.xlsx)|CSV (.csv)|PDF 报告 (.pdf)', '', true) + field('时间范围', 'select:当前视图|最近 30 天|最近 90 天|全部历史数据', '', true) + '<div class="ge2-field full"><label>包含内容</label><div class="ge2-checks"><label><input type="checkbox" checked> 指标汇总</label><label><input type="checkbox" checked> 明细列表</label><label><input type="checkbox" checked> 趋势图表</label><label><input type="checkbox"> 页面截图</label></div></div></div>',
      primary: '生成并下载',
      onPrimary: function (ctx) {
        var selects = ctx.body.querySelectorAll('select');
        var format = selects[0].value;
        var extension = format.indexOf('CSV') >= 0 ? 'csv' : format.indexOf('PDF') >= 0 ? 'pdf' : 'xlsx';
        var content = 'Growth Sniper Prototype Export\n页面,' + currentPageName() + '\n生成时间,' + new Date().toLocaleString('zh-CN') + '\n说明,静态原型演示数据\n';
        var blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'Growth Sniper-' + currentPageName().replace(/\s+/g, '-') + '.' + extension;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        temporarilyComplete(button, '✓ 已导出');
        toast('导出文件已生成');
        return true;
      }
    });
  }

  function progressSteps(label) {
    if (/诊断/.test(label)) return ['校验项目与数据源', '抓取官网和渠道数据', '识别机会与风险', '生成诊断报告'];
    if (/发布/.test(label)) return ['检查渠道授权', '按平台调整内容', '提交发布任务', '开启存活与引用监测'];
    if (/优化|应用/.test(label)) return ['读取诊断建议', '生成修改方案', '应用页面与内容调整', '复核优化结果'];
    if (/扫描|检测|巡检/.test(label)) return ['连接目标页面与引擎', '执行规则与内容检测', '汇总异常数据', '刷新当前报告'];
    if (/同步|刷新/.test(label)) return ['连接数据源', '拉取最新数据', '校验数据口径', '更新页面指标'];
    if (/生成/.test(label)) return ['读取品牌与关键词资产', '生成内容结构', '补充事实与引用', '完成质量检查'];
    if (/导入/.test(label)) return ['读取文件与字段', '校验重复与格式', '写入当前项目', '刷新列表'];
    return ['确认操作范围', '执行任务', '校验结果', '更新当前页面'];
  }

  function runProgress(label, button, customSteps) {
    var steps = customSteps || progressSteps(label);
    var body = '<div class="ge2-context"><b>任务在原型中模拟执行，完成后会更新当前页面状态。</b></div><div class="ge2-progress"><i></i></div><div class="ge2-step-list">' + steps.map(function (step, index) { return '<div class="ge2-step" data-step="' + index + '"><b>' + (index + 1) + '</b><span>' + escapeHtml(step) + '</span><small>等待</small></div>'; }).join('') + '</div>';
    var dialog = showDialog({ title: label, subtitle: currentPageName() + ' · 正在执行', body: body, primary: null, secondary: '后台运行' });
    var progress = dialog.body.querySelector('.ge2-progress i');
    var stepEls = dialog.body.querySelectorAll('.ge2-step');
    var current = 0;
    function advance() {
      if (!dialog.body.isConnected) return;
      if (current > 0) {
        stepEls[current - 1].classList.remove('active');
        stepEls[current - 1].classList.add('done');
        stepEls[current - 1].querySelector('b').textContent = '✓';
        stepEls[current - 1].querySelector('small').textContent = '完成';
      }
      if (current < steps.length) {
        stepEls[current].classList.add('active');
        stepEls[current].querySelector('small').textContent = '进行中';
        progress.style.width = Math.round((current / steps.length) * 100 + 12) + '%';
        current += 1;
        setTimeout(advance, 420);
      } else {
        progress.style.width = '100%';
        dialog.body.innerHTML = '<div class="ge2-success"><div class="ge2-success-icon">✓</div><h3>任务已完成</h3><p>' + escapeHtml(label) + '的演示结果已写入当前页面。</p></div>';
        var foot = dialog.mask.querySelector('.ge2-dialog-foot');
        foot.innerHTML = '<button class="ge2-button primary" type="button">完成</button>';
        foot.querySelector('button').addEventListener('click', closeMask);
        temporarilyComplete(button, '✓ 已完成');
        toast(label + '已完成');
      }
    }
    setTimeout(advance, 180);
  }

  function dropdownOptions(label) {
    if (/搜索引擎/.test(label)) return ['百度', 'Google', 'Bing', '360', '搜狗'];
    if (/最近|时间|天/.test(label)) return ['最近 7 天', '最近 30 天', '最近 90 天', '本年度'];
    if (/竞品/.test(label)) return ['全部竞品 · 8 个', '核心竞品 · 4 个', '潜在竞品 · 4 个'];
    if (/设备/.test(label)) return ['桌面端', '移动端', '全部设备'];
    if (/行业/.test(label)) return ['企业服务 > SaaS / 增长工具', '制造业 > 工业设备', '零售 > 电商平台', '教育 > 企业培训'];
    return ['全部数据', '仅看重点', '仅看异常'];
  }

  function openDropdown(button, label) {
    closeMenu();
    var menu = document.createElement('div');
    menu.className = 'ge2-menu';
    var options = dropdownOptions(label);
    menu.innerHTML = options.map(function (option, index) { return '<button class="ge2-option ' + (index === 1 ? 'active' : '') + '" type="button">' + escapeHtml(option) + '</button>'; }).join('');
    document.body.appendChild(menu);
    activeMenu = menu;
    var rect = button.getBoundingClientRect();
    var width = 210;
    menu.style.left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width)) + 'px';
    menu.style.top = Math.min(window.innerHeight - menu.offsetHeight - 8, rect.bottom + 6) + 'px';
    menu.querySelectorAll('.ge2-option').forEach(function (option) {
      option.addEventListener('click', function () {
        var value = cleanLabel(option.textContent);
        if (/搜索引擎/.test(label)) button.textContent = '搜索引擎：' + value + ' ▾';
        else if (/竞品/.test(label)) button.textContent = '竞品：' + value.replace(/全部竞品\s*·\s*/, '') + ' ▾';
        else button.textContent = value + (label.indexOf('▾') >= 0 ? ' ▾' : '');
        closeMenu();
        toast('已切换为“' + value + '”');
      });
    });
  }

  function drawerContent(label) {
    if (/历史|记录|日志/.test(label)) {
      return '<div class="ge2-list"><div class="ge2-list-item"><span class="ge2-list-mark">今</span><div><b>自动任务执行完成</b><span>今日 08:38 · 系统任务</span></div><em>成功</em></div><div class="ge2-list-item"><span class="ge2-list-mark">昨</span><div><b>数据源同步完成</b><span>昨日 08:12 · 1,284 条数据</span></div><em>查看</em></div><div class="ge2-list-item"><span class="ge2-list-mark">07</span><div><b>导出报告</b><span>07-12 16:20 · 操作人 DZ</span></div><em>下载</em></div></div>';
    }
    if (/文章库|内容库|渠道库|否词库|更换|切换/.test(label)) {
      return '<div class="ge2-list"><div class="ge2-list-item"><span class="ge2-list-mark">01</span><div><b>智能客服系统选型指南</b><span>原创 · 质量分 86 · 昨日更新</span></div><em>选择</em></div><div class="ge2-list-item"><span class="ge2-list-mark">02</span><div><b>数据分析平台横向对比</b><span>原创 · 质量分 82 · 3 天前</span></div><em>选择</em></div><div class="ge2-list-item"><span class="ge2-list-mark">03</span><div><b>CRM 软件采购常见问题</b><span>文章改写 · 关键词 7 个 · 5 天前</span></div><em>选择</em></div></div>';
    }
    if (/设置|管理/.test(label)) {
      return '<div class="ge2-toggle-row"><div><b>每日自动同步</b><span>每天凌晨抓取并保存快照</span></div><button class="ge2-switch on" type="button"><i></i></button></div><div class="ge2-toggle-row"><div><b>异常变化提醒</b><span>排名、转化或引用发生明显波动时提醒</span></div><button class="ge2-switch on" type="button"><i></i></button></div><div class="ge2-toggle-row"><div><b>周报自动生成</b><span>每周一生成跨渠道经营摘要</span></div><button class="ge2-switch" type="button"><i></i></button></div><div style="margin-top:16px">' + field('默认数据范围', 'select:最近 30 天|最近 90 天|本年度', '', true) + '</div>';
    }
    return '<div class="ge2-list"><div class="ge2-list-item"><span class="ge2-list-mark">01</span><div><b>当前项目概览</b><span>数据已于今日 08:38 更新</span></div><em>查看</em></div><div class="ge2-list-item"><span class="ge2-list-mark">02</span><div><b>待处理事项</b><span>3 项高优先级任务</span></div><em>处理</em></div></div>';
  }

  function openDrawer(label) {
    closeDrawer();
    var mask = document.createElement('div');
    mask.className = 'ge2-drawer-mask';
    mask.innerHTML = '<aside class="ge2-drawer" role="dialog" aria-modal="true" aria-label="' + escapeHtml(label) + '"><header class="ge2-drawer-head"><div><h2>' + escapeHtml(label) + '</h2><p>' + escapeHtml(currentPageName()) + ' · 演示数据</p></div><button class="ge2-close" type="button" aria-label="关闭">×</button></header><div class="ge2-drawer-body">' + drawerContent(label) + '</div><footer class="ge2-drawer-foot"><button class="ge2-button" type="button">关闭</button><button class="ge2-button primary" type="button">保存设置</button></footer></aside>';
    document.body.appendChild(mask);
    activeDrawer = mask;
    requestAnimationFrame(function () { mask.classList.add('show'); });
    mask.querySelector('.ge2-close').addEventListener('click', closeDrawer);
    mask.querySelector('.ge2-drawer-foot .ge2-button').addEventListener('click', closeDrawer);
    mask.querySelector('.ge2-drawer-foot .primary').addEventListener('click', function () { closeDrawer(); toast(label + '已保存'); });
    mask.addEventListener('click', function (event) { if (event.target === mask) closeDrawer(); });
    mask.querySelectorAll('.ge2-switch').forEach(function (toggle) { toggle.addEventListener('click', function () { toggle.classList.toggle('on'); }); });
    mask.querySelectorAll('.ge2-list-item').forEach(function (item) { item.addEventListener('click', function () { toast(cleanLabel(item.querySelector('b').textContent) + '已选中'); }); });
  }

  function savePage(button) {
    var values = [];
    document.querySelectorAll('.main input:not(.search), .main textarea, .main select').forEach(function (input) {
      values.push({ tag: input.tagName, type: input.type || '', value: input.value, checked: input.checked });
    });
    try { localStorage.setItem('ge2-form:' + location.pathname, JSON.stringify(values)); } catch (error) {}
    temporarilyComplete(button, '✓ 已保存');
    toast('当前页面信息已保存');
  }

  function restorePageForm() {
    var raw;
    try { raw = localStorage.getItem('ge2-form:' + location.pathname); } catch (error) { return; }
    if (!raw) return;
    var values;
    try { values = JSON.parse(raw); } catch (error) { return; }
    var inputs = document.querySelectorAll('.main input:not(.search), .main textarea, .main select');
    inputs.forEach(function (input, index) {
      if (!values[index]) return;
      input.value = values[index].value;
      if (values[index].type === 'checkbox' || values[index].type === 'radio') input.checked = values[index].checked;
    });
  }

  function copyPage(button) {
    var source = document.querySelector('pre, code, textarea');
    var text = source ? (source.value || source.textContent) : currentPageName() + '\nGrowth Sniper 静态原型演示内容';
    function done() { temporarilyComplete(button, '✓ 已复制'); toast('内容已复制到剪贴板'); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        var area = document.createElement('textarea'); area.value = text; document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove(); done();
      });
    } else {
      var area = document.createElement('textarea'); area.value = text; document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove(); done();
    }
  }

  function openABTest(button) {
    showDialog({
      title: '新建 A/B 实验',
      subtitle: currentPageName() + ' · 比较两个落地页版本',
      body: '<div class="ge2-context"><b>流量将按比例随机分配，达到最小样本量后给出胜出版本。</b></div><div class="ge2-form-grid">' + field('实验名称', 'text', '例如：价格页表单版本对比', true, 'full') + field('版本 A', 'url', 'https://example.com/a', true) + field('版本 B', 'url', 'https://example.com/b', true) + field('流量分配', 'select:50% / 50%|70% / 30%|30% / 70%', '', true) + field('核心指标', 'select:表单转化率|咨询点击率|有效线索率', '', true) + '</div>',
      primary: '启动实验',
      onPrimary: function (ctx) { if (!validateRequired(ctx.body)) { toast('请补全实验配置', 'warn'); return false; } temporarilyComplete(button, '实验运行中'); toast('A/B 实验已启动'); return true; }
    });
  }

  function showGenericAction(label, button) {
    showDialog({
      title: label,
      subtitle: currentPageName() + ' · 操作确认',
      body: '<div class="ge2-context"><b>这是可交互原型。确认后会更新当前页面的演示状态，并写入操作记录。</b></div><div class="ge2-form-grid">' + field('处理方式', 'select:立即执行|加入待办|交给负责人', '', true) + field('负责人', 'select:DZ|市场运营|SEO 负责人|GEO 负责人', '', true) + field('备注', 'textarea', '选填，记录本次处理说明', false, 'full') + '</div>',
      primary: '确认执行',
      onPrimary: function () { temporarilyComplete(button, '✓ 已执行'); toast(label + '已执行'); return true; }
    });
  }

  function handleSkip() {
    var target = document.getElementById('dashboard');
    var switchButton = document.querySelector('[data-target="dashboard"]');
    if (target && switchButton) { switchButton.click(); toast('已跳过接入，进入完整驾驶舱'); return; }
    toast('已跳过，可稍后在数据源页面继续');
  }

  function handleButton(button) {
    closeMenu();
    var label = cleanLabel(button.textContent);
    if (!label) return;
    if (/跳过/.test(label)) { handleSkip(); return; }
    if (/最近\s*\d+\s*天|▾$|搜索引擎：|竞品：/.test(label)) { openDropdown(button, label); return; }
    if (/保存|存草稿/.test(label)) { savePage(button); return; }
    if (/复制/.test(label)) { copyPage(button); return; }
    if (/导出|下载/.test(label)) { openExport(label, button); return; }
    if (/导入|上传/.test(label)) { openImport(label, button); return; }
    if (/A\/B/.test(label)) { openABTest(button); return; }
    if (/刷新|同步|诊断|扫描|检测|巡检|生成|优化|应用|发布/.test(label)) { runProgress(label, button); return; }
    if (/^\+|新增|添加|新建|接入|绑定/.test(label)) { openCreate(label, button); return; }
    if (/设置|管理|历史|文章库|内容库|渠道库|否词库|处理记录|更换|切换/.test(label)) { openDrawer(label); return; }
    showGenericAction(label, button);
  }

  function shouldHandleButton(button) {
    if (!button || button.closest('.ge2-mask,.ge2-drawer-mask,.ge2-menu')) return false;
    if (button.disabled || (button.hasAttribute('onclick') && !button.classList.contains('scanbtn')) || button.hasAttribute('data-help') || button.hasAttribute('data-target')) return false;
    if (button.classList.contains('platform-tab') || button.classList.contains('ge2-button') || button.classList.contains('ge2-option') || button.classList.contains('ge2-switch')) return false;
    return true;
  }

  function enhanceFields() {
    document.querySelectorAll('.inpwrap input[maxlength], .inpwrap textarea[maxlength]').forEach(function (input) {
      var counter = input.parentElement.querySelector('.counter');
      if (!counter) return;
      function update() { counter.textContent = input.value.length + '/' + input.maxLength; }
      input.addEventListener('input', update);
      update();
    });

    document.querySelectorAll('.logo-up').forEach(function (logo) {
      if (logo.dataset.ge2Ready) return;
      logo.dataset.ge2Ready = 'true';
      logo.addEventListener('click', function () {
        var input = document.createElement('input');
        input.type = 'file'; input.accept = 'image/*';
        input.addEventListener('change', function () { if (input.files && input.files[0]) toast('已选择图片：' + input.files[0].name); });
        input.click();
      });
    });

    document.querySelectorAll('.select').forEach(function (selectLike) {
      if (selectLike.dataset.ge2Ready) return;
      selectLike.dataset.ge2Ready = 'true';
      selectLike.addEventListener('click', function () { openDropdown(selectLike, '行业 ▾'); });
    });
  }

  function versionInternalLinks() {
    document.querySelectorAll('a[href]').forEach(function (anchor) {
      var href = anchor.getAttribute('href');
      if (!href || href.charAt(0) === '#' || /^(https?:|mailto:|javascript:)/i.test(href) || !/\.html(?:[?#]|$)/i.test(href)) return;
      var parts = href.split('#');
      var base = parts[0];
      var hash = parts[1] ? '#' + parts[1] : '';
      if (/([?&])rev=/.test(base)) base = base.replace(/([?&])rev=[^&#]*/g, '$1rev=content-v9');
      else base += (base.indexOf('?') >= 0 ? '&' : '?') + 'rev=content-v9';
      anchor.setAttribute('href', base + hash);
    });
  }

  function boot() {
    injectStyles();
    versionInternalLinks();
    restorePageForm();
    enhanceFields();

    document.addEventListener('click', function (event) {
      var button = event.target.closest('button');
      if (!shouldHandleButton(button)) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      handleButton(button);
    }, true);

    document.addEventListener('click', function (event) {
      if (activeMenu && !event.target.closest('.ge2-menu')) closeMenu();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      closeMenu(); closeMask(); closeDrawer();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
