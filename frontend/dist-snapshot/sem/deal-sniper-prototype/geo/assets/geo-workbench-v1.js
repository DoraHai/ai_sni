/**
 * Shared helpers for GEO content pages.
 */
(function (global) {
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === 'className') node.className = attrs[k];
      else if (k === 'text') node.textContent = attrs[k];
      else if (k === 'html') node.innerHTML = attrs[k];
      else if (k.indexOf('on') === 0) node.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  function statusBadge(status) {
    var map = {
      draft: 'warn',
      facts_bound: '',
      generating: '',
      editing: '',
      needs_fix: 'warn',
      ready: 'good',
      exported: 'good',
      published: 'good',
      failed: 'bad',
    };
    return '<span class="wb-badge ' + (map[status] || '') + '">' + (status || '-') + '</span>';
  }

  function showError(box, err) {
    if (!box) return;
    if (err && err.silent) return;
    box.style.display = 'block';
    box.textContent = (err && err.message) ? err.message : String(err || '未知错误');
  }

  function clearError(box) {
    if (!box) return;
    box.style.display = 'none';
    box.textContent = '';
  }

  function renderAuthBar(root) {
    if (!root || !global.GeoAPI) return;
    root.innerHTML = '';
    if (GeoAPI.getToken()) {
      var existingTenant = GeoAPI.getTenantId();
      root.appendChild(el('span', {
        className: 'wb-muted',
        text: existingTenant ? '正在读取客户列表…' : '正在识别当前客户…',
      }));
      GeoAPI.resolveTenantContext().then(function (context) {
        var tenants = context.tenants || [];
        if (!context.tenantId) throw new Error('当前账号没有可用客户，请联系管理员分配');
        if (!existingTenant || Number(existingTenant) !== Number(context.tenantId)) {
          var target = new URL(window.location.href);
          target.searchParams.set('tenant_id', String(context.tenantId));
          window.location.replace(target.toString());
          return;
        }
        root.innerHTML = '';
        root.appendChild(el('span', { className: 'wb-muted', text: '当前客户' }));
        var select = el('select', { className: 'wb-select', 'aria-label': '当前客户' });
        tenants.forEach(function (item) {
          var option = el('option', { value: String(item.id), text: item.name || ('客户 ' + item.id) });
          if (Number(item.id) === Number(context.tenantId)) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener('change', function () {
          GeoAPI.setTenantId(select.value);
          var target = new URL(window.location.href);
          target.searchParams.set('tenant_id', select.value);
          window.location.href = target.toString();
        });
        root.appendChild(select);
        root.appendChild(el('span', { className: 'wb-muted', text: '已登录，数据按客户隔离' }));
      }).catch(function (error) {
        root.innerHTML = '';
        root.appendChild(el('span', { className: 'wb-error', text: error.message || '无法识别当前客户' }));
      });
      return;
    }
    var tenant = el('input', {
      className: 'wb-input',
      placeholder: 'tenant_id',
      value: GeoAPI.getTenantId() || '',
    });
    var key = el('input', {
      className: 'wb-input',
      placeholder: 'API Key（无登录时）',
      value: GeoAPI.getApiKey() || '',
    });
    var save = el('button', {
      className: 'wb-btn primary',
      text: '保存上下文',
      onClick: function () {
        if (tenant.value) {
          localStorage.setItem('geo_tenant_id', tenant.value);
          var u = new URL(window.location.href);
          u.searchParams.set('tenant_id', tenant.value);
          window.location.href = u.toString();
        }
        if (key.value) GeoAPI.setApiKey(key.value);
      },
    });
    var tip = el('span', {
      className: 'wb-muted',
      text: GeoAPI.getToken()
        ? '已检测到登录 token'
        : (GeoAPI.getApiKey() ? '使用 API Key' : '请登录 SEM 或填写 API Key'),
    });
    root.appendChild(tenant);
    root.appendChild(key);
    root.appendChild(save);
    root.appendChild(tip);
  }

  function requireTenant() {
    var id = GeoAPI.getTenantId();
    if (!id && GeoAPI.isResolvingTenant()) {
      var pending = new Error('正在识别当前客户');
      pending.silent = true;
      throw pending;
    }
    if (!id) throw new Error('当前账号没有可用客户，请重新登录或联系管理员');
    return id;
  }

  function renderPipeline(root, step) {
    if (!root) return;
    var steps = [
      ['opportunity', '提问缺口'],
      ['evidence', '证据注入'],
      ['draft', '生成编辑'],
      ['adapt', '渠道适配'],
      ['publish', '发布回填'],
    ];
    var idx = steps.findIndex(function (s) { return s[0] === step; });
    root.innerHTML = steps.map(function (s, i) {
      var cls = 'pipe-step';
      if (s[0] === step) cls += ' active';
      else if (idx >= 0 && i < idx) cls += ' done';
      return '<div class="' + cls + '">' + s[1] + '</div>';
    }).join('<span class="pipe-arrow">→</span>');
  }

  function pipelineLabel(step) {
    var map = {
      opportunity: '提问缺口',
      evidence: '证据注入',
      draft: '生成编辑',
      adapt: '渠道适配',
      publish: '发布回填',
    };
    return map[step] || step || '-';
  }

  var EMPTY_SVG =
    '<svg class="wb-empty-box" viewBox="0 0 240 240" aria-hidden="true">' +
    '<defs>' +
    '<linearGradient id="wbEmptyG1" x1="0" x2="1" y1="0" y2="1">' +
    '<stop offset="0" stop-color="#ffffff"/>' +
    '<stop offset="1" stop-color="#d9dde7"/>' +
    '</linearGradient>' +
    '<linearGradient id="wbEmptyG2" x1="0" x2="1" y1="0" y2="1">' +
    '<stop offset="0" stop-color="#eef1f7"/>' +
    '<stop offset="1" stop-color="#cfd5e1"/>' +
    '</linearGradient>' +
    '</defs>' +
    '<ellipse cx="122" cy="195" rx="86" ry="13" fill="#e9edf4"/>' +
    '<path d="M74 100h92v92H74z" fill="url(#wbEmptyG1)"/>' +
    '<path d="M74 100l28-42h92l-28 42z" fill="#f8fafc"/>' +
    '<path d="M166 100l28-42 34 52-30 42z" fill="url(#wbEmptyG2)"/>' +
    '<path d="M74 100l-31 44h31z" fill="#d9dee8"/>' +
    '<path d="M166 100l31 44h-31z" fill="#cfd5e1"/>' +
    '<path d="M102 58l64 42h-92z" fill="#eef1f7"/>' +
    '<path d="M142 69l48 22 10 24-47-22z" fill="#d9dee8"/>' +
    '<path d="M74 100h92v92H74z" fill="none" stroke="#e2e6ee"/>' +
    '</svg>';

  function renderEmpty(root, title, opts) {
    if (!root) return;
    opts = opts || {};
    var cls = 'wb-empty' + (opts.inline ? ' wb-empty-inline' : '');
    var html = opts.showIcon === false ? '' : EMPTY_SVG;
    html += '<div class="wb-empty-title">' + (title || '暂无数据') + '</div>';
    root.className = cls;
    root.innerHTML = html;
  }

  function renderComingSoon(root, featureName) {
    var name = featureName || '该模块';
    renderEmpty(root, '「' + name + '」开发中，接入真实功能后开放');
  }

  function withDemoQuery(href) {
    var u = new URL(href, window.location.href);
    var tenant = (global.GeoAPI && GeoAPI.getTenantId && GeoAPI.getTenantId()) ||
      new URLSearchParams(window.location.search).get('tenant_id') ||
      localStorage.getItem('geo_tenant_id');
    var key = (global.GeoAPI && GeoAPI.getApiKey && GeoAPI.getApiKey()) ||
      new URLSearchParams(window.location.search).get('api_key') ||
      localStorage.getItem('geo_api_key');
    var origin = localStorage.getItem('geo_api_origin') ||
      new URLSearchParams(window.location.search).get('api_origin');
    if (tenant && !u.searchParams.get('tenant_id')) u.searchParams.set('tenant_id', String(tenant));
    if (key && !u.searchParams.get('api_key')) u.searchParams.set('api_key', key);
    if (origin && !u.searchParams.get('api_origin')) u.searchParams.set('api_origin', origin);
    return u.pathname.split('/').pop() + u.search;
  }

  function formatImportResult(result) {
    var ok = result.ok_count != null ? result.ok_count : result.count;
    var lines = ['导入成功 ' + (ok || 0) + ' 条'];
    var errors = result.errors || [];
    if (errors.length) {
      lines.push('失败 ' + errors.length + ' 条：');
      errors.slice(0, 20).forEach(function (e) {
        lines.push('· 第 ' + (e.line || '?') + ' 行：' + (e.error || JSON.stringify(e)));
      });
      if (errors.length > 20) lines.push('· …其余 ' + (errors.length - 20) + ' 条略');
    }
    return lines.join('\n');
  }

  function showImportResult(box, result) {
    if (!box) return;
    var errors = result.errors || [];
    box.style.display = 'block';
    box.style.whiteSpace = 'pre-wrap';
    box.className = errors.length ? 'wb-error' : 'wb-ok-box';
    box.textContent = formatImportResult(result);
  }

  global.GeoWB = {
    el: el,
    statusBadge: statusBadge,
    showError: showError,
    clearError: clearError,
    renderAuthBar: renderAuthBar,
    requireTenant: requireTenant,
    renderPipeline: renderPipeline,
    pipelineLabel: pipelineLabel,
    renderEmpty: renderEmpty,
    renderComingSoon: renderComingSoon,
    withDemoQuery: withDemoQuery,
    formatImportResult: formatImportResult,
    showImportResult: showImportResult,
  };
})(window);
