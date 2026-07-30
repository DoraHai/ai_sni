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
    if (!id) throw new Error('请先设置 tenant_id');
    return id;
  }

  global.GeoWB = {
    el: el,
    statusBadge: statusBadge,
    showError: showError,
    clearError: clearError,
    renderAuthBar: renderAuthBar,
    requireTenant: requireTenant,
  };
})(window);
