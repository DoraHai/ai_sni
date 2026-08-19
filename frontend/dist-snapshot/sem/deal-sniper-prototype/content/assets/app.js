/* 通用交互引擎 —— 让静态原型"全交互"。一份脚本，按约定自动接管全站控件。 */
(function () {
  function cssVar(n, d) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    return v || d;
  }
  var ACCENT = cssVar('--accent', '#2563eb');
  var SOFT = cssVar('--accent-soft', '#eef4ff');

  // 注入运行态样式
  var st = document.createElement('style');
  st.textContent =
    '.chip-on{background:' + SOFT + '!important;color:' + ACCENT + '!important;border-color:' + ACCENT + '!important}' +
    'label.card{cursor:pointer;user-select:none;transition:.12s}' +
    'label.card.is-sel{border-color:' + ACCENT + '!important;box-shadow:0 0 0 2px ' + SOFT + ' inset}' +
    '.opt-on{background:' + SOFT + '!important;color:' + ACCENT + '!important}' +
    '.ge-toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#1e2330;color:#fff;padding:10px 18px;border-radius:10px;font-size:13px;z-index:9999;opacity:0;transition:.22s;box-shadow:0 10px 30px rgba(0,0,0,.25)}' +
    '.info-i{display:inline-flex;width:15px;height:15px;border-radius:50%;border:1px solid var(--muted);color:var(--muted);font-size:10px;align-items:center;justify-content:center;cursor:pointer;font-style:normal;vertical-align:middle}' +
    '.info-i:hover{border-color:' + ACCENT + ';color:' + ACCENT + '}' +
    '.help-link{color:' + ACCENT + ';font-size:12px;cursor:pointer;font-weight:600}' +
    '.modal-mask{position:fixed;inset:0;background:rgba(16,24,40,.45);display:none;align-items:center;justify-content:center;z-index:9998;padding:24px}' +
    '.modal-mask.show{display:flex}' +
    '.modal{background:#fff;border-radius:16px;max-width:760px;width:100%;max-height:88vh;overflow:auto;box-shadow:0 24px 60px rgba(16,24,40,.3)}' +
    '.modal .mhd{padding:18px 22px;border-bottom:1px solid var(--border);display:flex;align-items:center}' +
    '.modal .mhd h3{margin:0;font-size:16px}' +
    '.modal .mbd{padding:22px}' +
    '.modal .x{margin-left:auto;cursor:pointer;color:var(--muted);font-size:20px;line-height:1}' +
    '.flow{display:flex;align-items:stretch;gap:8px}' +
    '.flow .step{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center}' +
    '.flow .step .n{width:22px;height:22px;border-radius:50%;background:' + ACCENT + ';color:#fff;font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;margin-bottom:6px}' +
    '.flow .step b{display:block;font-size:13px;margin-bottom:3px}' +
    '.flow .arrow{display:flex;align-items:center;color:var(--muted);font-size:18px}';
  document.head.appendChild(st);

  // 通用说明弹窗：[data-help="modalId"] 打开 #modalId，点遮罩/×/Esc 关闭
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-help]');
    if (opener) { var m = document.getElementById(opener.getAttribute('data-help')); if (m) m.classList.add('show'); return; }
    if (e.target.classList && e.target.classList.contains('modal-mask')) { e.target.classList.remove('show'); return; }
    var x = e.target.closest('.modal .x');
    if (x) { var mm = x.closest('.modal-mask'); if (mm) mm.classList.remove('show'); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('.modal-mask.show').forEach(function (m) { m.classList.remove('show'); });
  });

  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'ge-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.style.opacity = '1'; });
    setTimeout(function () { t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 250); }, 1500);
  }
  window.geToast = toast;

  document.addEventListener('DOMContentLoaded', function () {

    /* 1) 搜索框 → 实时过滤本页第一个表格 */
    document.querySelectorAll('input.search').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var table = document.querySelector('.content table');
        if (!table) return;
        var q = inp.value.trim().toLowerCase();
        table.querySelectorAll('tbody tr').forEach(function (tr) {
          tr.style.display = (!q || tr.textContent.toLowerCase().indexOf(q) >= 0) ? '' : 'none';
        });
      });
    });

    /* 2) 筛选标签组（卡片头里 ≥2 个 .tag）→ 单选高亮 + 按文本过滤表格行 */
    document.querySelectorAll('.card .hd').forEach(function (hd) {
      var tags = Array.prototype.slice.call(hd.querySelectorAll('.tag'));
      if (tags.length < 2) return;
      var card = hd.closest('.card');
      tags.forEach(function (tag, i) {
        if (i === 0) tag.classList.add('chip-on');
        tag.style.cursor = 'pointer';
        tag.addEventListener('click', function () {
          tags.forEach(function (t) { t.classList.remove('chip-on'); });
          tag.classList.add('chip-on');
          var label = tag.textContent.replace(/[▾]/g, '').trim();
          var rows = card.querySelectorAll('tbody tr');
          var showAll = /^全部/.test(label) || label === '';
          rows.forEach(function (tr) {
            tr.style.display = (showAll || tr.textContent.indexOf(label) >= 0) ? '' : 'none';
          });
        });
      });
    });

    /* 3) 可选卡片（label.card 带 .dot）→ 点击切换选中 + 更新"已选 X / Y" */
    document.querySelectorAll('.card').forEach(function (card) {
      var labels = Array.prototype.slice.call(card.querySelectorAll('label.card'));
      var pickable = labels.filter(function (l) { return l.querySelector('.dot'); });
      if (!pickable.length) return;

      // 初始选中：作者用 border-color 内联标记过的
      pickable.forEach(function (l) {
        if ((l.getAttribute('style') || '').indexOf('border-color:var(--accent)') >= 0 ||
            (l.style && l.style.borderColor && l.style.borderColor !== '')) {
          l.classList.add('is-sel');
        }
      });

      var counter = card.querySelector('.more');
      function refresh() {
        var n = pickable.filter(function (l) { return l.classList.contains('is-sel'); }).length;
        if (counter && /已选/.test(counter.textContent)) {
          counter.textContent = counter.textContent.replace(/已选\s*\d+/, '已选 ' + n);
        }
      }
      refresh();

      pickable.forEach(function (l) {
        var dot = l.querySelector('.dot');
        var defColor = dot ? dot.style.background : '';
        l.addEventListener('click', function (e) {
          e.preventDefault();
          var on = l.classList.toggle('is-sel');
          if (dot) dot.style.background = on ? ACCENT : '#cfd4de';
          refresh();
        });
      });
    });

    /* 4) 选项徽章组（一行里全是 .badge，用于"立即/定时"这类单选）→ 点击切换 */
    document.querySelectorAll('.bd .row').forEach(function (row) {
      var kids = Array.prototype.slice.call(row.children);
      var badges = kids.filter(function (k) { return k.classList && k.classList.contains('badge'); });
      // 整行全是徽章、数量 2~3、且看起来是"蓝+灰"选项组
      if (badges.length < 2 || badges.length !== kids.length) return;
      var looksOption = badges.some(function (b) { return /blue/.test(b.className); }) &&
                        badges.some(function (b) { return /gray/.test(b.className); });
      if (!looksOption) return;
      badges.forEach(function (b) {
        b.style.cursor = 'pointer';
        b.addEventListener('click', function () {
          badges.forEach(function (x) { x.classList.remove('opt-on'); });
          b.classList.add('opt-on');
        });
      });
    });

    /* 5) 按钮反馈：非链接按钮点击给提示（演示态） */
    document.querySelectorAll('button.btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var label = btn.textContent.trim().replace(/^[^一-龥A-Za-z]+/, '');
        toast('原型演示：「' + label + '」已触发');
      });
    });

    /* 6) 操作类标签（加入/采用/接入/授权/补充…）→ 可点击，给反馈或切换状态 */
    var ACTION_WORDS = ['加入', '采用', '接入', '授权', '补充', '纠正', '添加', '处理', '修复', '优化'];
    document.querySelectorAll('span.badge').forEach(function (b) {
      var txt = b.textContent.trim().replace(/^[+＋]\s*/, '');
      var isAction = ACTION_WORDS.some(function (w) { return txt === w || txt === w + ' →' || txt.indexOf(w) === 0; });
      if (!isAction) return;
      b.style.cursor = 'pointer';
      b.addEventListener('click', function (e) {
        e.preventDefault();
        if (/加入/.test(txt) && !/已/.test(b.textContent)) {
          b.dataset.old = b.className;
          b.className = 'badge green';
          b.textContent = '✓ 已加入';
          toast('已加入分发列表');
        } else if (/已加入/.test(b.textContent)) {
          b.className = b.dataset.old || 'badge blue';
          b.textContent = '加入';
        } else {
          toast('原型演示：「' + txt + '」已触发');
        }
      });
    });

    /* 7) 侧边栏分组折叠/展开 */
    document.querySelectorAll('.sidebar .nav-group').forEach(function (g) {
      g.style.cursor = 'pointer';
      g.style.display = 'flex';
      g.style.alignItems = 'center';
      g.style.userSelect = 'none';
      var car = document.createElement('span');
      car.textContent = '⌄';
      car.style.cssText = 'margin-left:auto;font-size:12px;color:#b4b9c4;transition:.15s;';
      g.appendChild(car);
      g.addEventListener('click', function () {
        var collapsed = g.classList.toggle('collapsed');
        car.style.transform = collapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
        var el = g.nextElementSibling;
        while (el && !el.classList.contains('nav-group') && !el.classList.contains('spacer')) {
          el.style.display = collapsed ? 'none' : '';
          el = el.nextElementSibling;
        }
      });
    });
  });
})();
