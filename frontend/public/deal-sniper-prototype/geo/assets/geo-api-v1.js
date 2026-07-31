/**
 * GEO 内容工作台 API 客户端。
 * 鉴权：优先 sem_token（与 SEM 登录一致），其次 URL ?api_key= 或 localStorage geo_api_key。
 */
(function (global) {
  function qs() {
    return new URLSearchParams(window.location.search);
  }

  function getTenantId() {
    var fromQuery = qs().get('tenant_id');
    if (fromQuery) {
      localStorage.setItem('geo_tenant_id', fromQuery);
      return Number(fromQuery);
    }
    var stored = localStorage.getItem('geo_tenant_id');
    return stored ? Number(stored) : null;
  }

  function getToken() {
    return (
      localStorage.getItem('sem_token') ||
      sessionStorage.getItem('sem_token') ||
      ''
    );
  }

  function getApiKey() {
    return qs().get('api_key') || localStorage.getItem('geo_api_key') || '';
  }

  function setApiKey(key) {
    if (key) localStorage.setItem('geo_api_key', key);
  }

  function ensureAuthOrRedirect() {
    if (getToken() || getApiKey()) return true;
    var redirect = encodeURIComponent(window.location.href);
    window.location.href = '/login?redirect=' + redirect;
    return false;
  }

  function apiOrigin() {
    var fromQuery = qs().get('api_origin');
    if (fromQuery) {
      localStorage.setItem('geo_api_origin', fromQuery.replace(/\/$/, ''));
      return fromQuery.replace(/\/$/, '');
    }
    var override = localStorage.getItem('geo_api_origin');
    if (override) return override.replace(/\/$/, '');
    // Local static/dev pages are not same-origin with geo_main (:8010)
    if (/^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname) && window.location.port !== '8010' && window.location.port !== '8011') {
      // Local static pages talk to geo_main; default 8011 (8010 may be an old stuck process)
      return 'http://127.0.0.1:8011';
    }
    return window.location.origin;
  }

  async function api(path, options) {
    options = options || {};
    if (options.requireAuth !== false && !getToken() && !getApiKey()) {
      // allow explicit local demo without redirect when tenant+key in URL
      if (!qs().get('api_key') && !localStorage.getItem('geo_api_key')) {
        ensureAuthOrRedirect();
      }
    }
    var method = options.method || 'GET';
    var body = options.body;
    var tenantId = options.tenantId != null ? options.tenantId : getTenantId();
    var url = new URL('/api/v1/geo' + path, apiOrigin());
    if (tenantId && method === 'GET') {
      url.searchParams.set('tenant_id', String(tenantId));
    }
    if (options.query) {
      Object.keys(options.query).forEach(function (k) {
        if (options.query[k] != null) url.searchParams.set(k, String(options.query[k]));
      });
    }

    var headers = { Accept: 'application/json' };
    var token = getToken();
    var apiKey = getApiKey();
    var keyFromQuery = qs().get('api_key');
    // Deep-link demo: URL api_key must win over a stale sem_token, otherwise getTask 401s silently for the form
    if (keyFromQuery) {
      headers['X-API-Key'] = keyFromQuery;
    } else if (token) {
      headers.Authorization = 'Bearer ' + token;
    } else if (apiKey) {
      headers['X-API-Key'] = apiKey;
    }

    if (body != null) {
      headers['Content-Type'] = 'application/json';
      if (tenantId && typeof body === 'object' && body.tenant_id == null) {
        body = Object.assign({ tenant_id: tenantId }, body);
      }
    }

    var res = await fetch(url.toString(), {
      method: method,
      headers: headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });

    var text = await res.text();
    var data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      data = { detail: text };
    }
    if (!res.ok) {
      var detail = data && data.detail;
      if (Array.isArray(detail)) {
        detail = detail.map(function (d) { return d.msg || JSON.stringify(d); }).join('; ');
      } else if (detail && typeof detail === 'object') {
        detail = detail.msg || JSON.stringify(detail);
      }
      throw new Error(detail || ('HTTP ' + res.status));
    }
    return data;
  }

  function withTenantQuery(extra) {
    var tenantId = getTenantId();
    return Object.assign({ tenant_id: tenantId }, extra || {});
  }

  global.GeoAPI = {
    getTenantId: getTenantId,
    getToken: getToken,
    getApiKey: getApiKey,
    setApiKey: setApiKey,
    ensureAuthOrRedirect: ensureAuthOrRedirect,
    api: api,
    contentHealth: function () { return api('/content-health'); },
    contentStats: function () { return api('/content-stats'); },
    listPrompts: function () { return api('/prompts'); },
    createPrompt: function (body) { return api('/prompts', { method: 'POST', body: body }); },
    importPrompts: function (items) {
      return api('/prompts/import', { method: 'POST', body: { items: items } });
    },
    importPromptsCsv: function (file) {
      var tenantId = getTenantId();
      var fd = new FormData();
      fd.append('file', file);
      return fetch(apiOrigin() + '/api/v1/geo/prompts/import-csv?tenant_id=' + tenantId, {
        method: 'POST',
        headers: (function () {
          var h = {};
          var token = getToken();
          var apiKey = getApiKey();
          if (token) h.Authorization = 'Bearer ' + token;
          else if (apiKey) h['X-API-Key'] = apiKey;
          return h;
        })(),
        body: fd,
      }).then(function (res) { return res.json().then(function (d) {
        if (!res.ok) throw new Error(d.detail || ('HTTP ' + res.status));
        return d;
      }); });
    },
    listFacts: function (trustLevel) {
      return api('/facts', { query: trustLevel ? { trust_level: trustLevel } : {} });
    },
    createFact: function (body) { return api('/facts', { method: 'POST', body: body }); },
    importFactsCsv: function (file) {
      var tenantId = getTenantId();
      var fd = new FormData();
      fd.append('file', file);
      return fetch(apiOrigin() + '/api/v1/geo/facts/import?tenant_id=' + tenantId, {
        method: 'POST',
        headers: (function () {
          var h = {};
          var token = getToken();
          var apiKey = getApiKey();
          if (token) h.Authorization = 'Bearer ' + token;
          else if (apiKey) h['X-API-Key'] = apiKey;
          return h;
        })(),
        body: fd,
      }).then(function (res) { return res.json().then(function (d) {
        if (!res.ok) throw new Error(d.detail || ('HTTP ' + res.status));
        return d;
      }); });
    },
    verifyFact: function (id) {
      return api('/facts/' + id + '/verify', { method: 'POST', query: withTenantQuery() });
    },
    listTasks: function (query) {
      return api('/content-tasks', { query: query || {} });
    },
    getTask: function (id) {
      return api('/content-tasks/' + id, { query: withTenantQuery() });
    },
    createTask: function (body) {
      return api('/content-tasks', { method: 'POST', body: body });
    },
    bindFacts: function (id, factIds) {
      return api('/content-tasks/' + id + '/facts', {
        method: 'PUT',
        query: withTenantQuery(),
        body: { fact_ids: factIds },
      });
    },
    seedDiagnosisFacts: function (id) {
      return api('/content-tasks/' + id + '/seed-diagnosis-facts', {
        method: 'POST',
        query: withTenantQuery(),
      });
    },
    saveArticle: function (id, body) {
      return api('/content-tasks/' + id + '/article', {
        method: 'PUT',
        query: withTenantQuery(),
        body: body,
      });
    },
    checkTask: function (id, requireChannels) {
      return api('/content-tasks/' + id + '/check', {
        method: 'POST',
        query: Object.assign(withTenantQuery(), { require_channels: !!requireChannels }),
      });
    },
    applyPatch: function (id, code, authorName) {
      return api('/content-tasks/' + id + '/apply-patch', {
        method: 'POST',
        query: withTenantQuery(),
        body: { code: code, author_name: authorName || null },
      });
    },
    patchTask: function (id, body) {
      return api('/content-tasks/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    createTaskFromDiagnosis: function (body) {
      return api('/content-tasks/from-diagnosis', { method: 'POST', body: body });
    },
    generateTask: function (id) {
      return api('/content-tasks/' + id + '/generate', {
        method: 'POST',
        query: withTenantQuery(),
      });
    },
    listChannelProfiles: function () {
      return api('/channel-profiles', { query: withTenantQuery() });
    },
    createVariants: function (id, channels) {
      return api('/content-tasks/' + id + '/variants', {
        method: 'POST',
        query: withTenantQuery(),
        body: { channels: channels || ['website', 'wechat', 'zhihu'] },
      });
    },
    patchVariant: function (id, channel, body) {
      return api('/content-tasks/' + id + '/variants/' + encodeURIComponent(channel), {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    exportVariant: function (id, channel) {
      return api('/content-tasks/' + id + '/export', {
        query: Object.assign(withTenantQuery(), { channel: channel || 'website' }),
      });
    },
    publish: function (id, body) {
      return api('/content-tasks/' + id + '/publications', {
        method: 'POST',
        body: body,
      });
    },
    listAnswerSnapshots: function (promptId, engine) {
      var query = withTenantQuery();
      if (promptId != null) query.prompt_id = promptId;
      if (engine) query.engine = engine;
      return api('/answer-snapshots', { query: query });
    },
    createAnswerSnapshot: function (body) {
      return api('/answer-snapshots', { method: 'POST', body: body });
    },
    patchAnswerSnapshot: function (id, body) {
      return api('/answer-snapshots/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    listTrackingEngines: function (enabledOnly) {
      var query = withTenantQuery();
      if (enabledOnly) query.enabled_only = true;
      return api('/tracking-engines', { query: query });
    },
    putTrackingEngines: function (items) {
      return api('/tracking-engines', {
        method: 'PUT',
        body: { items: items || [] },
      });
    },
    listMediaPlacements: function (status) {
      var query = withTenantQuery();
      if (status) query.status = status;
      return api('/media-placements', { query: query });
    },
    createMediaPlacement: function (body) {
      return api('/media-placements', { method: 'POST', body: body });
    },
    patchMediaPlacement: function (id, body) {
      return api('/media-placements/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
  };
})(window);
