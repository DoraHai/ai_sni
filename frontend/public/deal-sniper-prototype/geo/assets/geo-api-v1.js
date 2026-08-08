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
    briefCatalog: function () { return api('/content-brief-catalog'); },
    contentStats: function () { return api('/content-stats'); },
    visibilityPeriodDiff: function (windows) {
      var query = withTenantQuery();
      query.before_from = windows.before_from;
      query.before_to = windows.before_to;
      query.after_from = windows.after_from;
      query.after_to = windows.after_to;
      return api('/visibility-period-diff', { query: query });
    },
    listPrompts: function (query) {
      return api('/prompts', { query: query || {} });
    },
    createPrompt: function (body) { return api('/prompts', { method: 'POST', body: body }); },
    expandPromptCandidates: function (body) {
      return api('/prompts/expand-candidates', { method: 'POST', body: body || {} });
    },
    promotePromptCandidates: function (items) {
      return api('/prompts/promote-candidates', {
        method: 'POST',
        body: { items: items || [] },
      });
    },
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
      var ids = (factIds || [])
        .map(function (x) {
          if (x && typeof x === 'object') return Number(x.id != null ? x.id : x.fact_id);
          return Number(x);
        })
        .filter(function (n) { return Number.isFinite(n) && n > 0; });
      return api('/content-tasks/' + id + '/facts', {
        method: 'PUT',
        query: withTenantQuery(),
        body: { fact_ids: ids },
      }).then(function (boundTask) {
        // Always re-GET so chips/count never stick on a partial payload
        if (boundTask && Array.isArray(boundTask.facts) && boundTask.facts.length) {
          return boundTask;
        }
        return api('/content-tasks/' + id, { query: withTenantQuery() });
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
    lintTask: function (id) {
      return api('/content-tasks/' + id + '/lint', {
        method: 'POST',
        query: withTenantQuery(),
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
    suggestBrief: function (id, body) {
      return api('/content-tasks/' + id + '/suggest-brief', {
        method: 'POST',
        query: withTenantQuery(),
        body: body || {},
      });
    },
    retrieveFacts: function (id, body) {
      return api('/content-tasks/' + id + '/retrieve-facts', {
        method: 'POST',
        query: withTenantQuery(),
        body: body || {},
      });
    },
    applyRetrievedFacts: function (id, factIds) {
      var ids = (factIds || [])
        .map(function (x) {
          if (x && typeof x === 'object') return Number(x.id != null ? x.id : x.fact_id);
          return Number(x);
        })
        .filter(function (n) { return Number.isFinite(n) && n > 0; });
      return api('/content-tasks/' + id + '/retrieve-facts/apply', {
        method: 'POST',
        query: withTenantQuery(),
        body: { fact_ids: ids },
      }).then(function (boundTask) {
        if (boundTask && Array.isArray(boundTask.facts) && boundTask.facts.length) {
          return boundTask;
        }
        return api('/content-tasks/' + id, { query: withTenantQuery() });
      });
    },
    aiReviewTask: function (id, body) {
      return api('/content-tasks/' + id + '/ai-review', {
        method: 'POST',
        query: withTenantQuery(),
        body: body || { persist: true },
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
    listPublishingChannelOptions: function () {
      return api('/publishing-channel-options', { query: withTenantQuery() });
    },
    submitReview: function (id, note) {
      return api('/content-tasks/' + id + '/submit-review', {
        method: 'POST',
        query: withTenantQuery(),
        body: { note: note || null },
      });
    },
    decideReview: function (id, decision, note) {
      return api('/content-tasks/' + id + '/review', {
        method: 'POST',
        query: withTenantQuery(),
        body: { decision: decision, note: note || null },
      });
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
    pushVariantWebhook: function (id, body) {
      return api('/content-tasks/' + id + '/push', {
        method: 'POST',
        body: body || {},
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
    probeAnswerSnapshot: function (promptId, engine) {
      var body = { prompt_id: promptId };
      if (engine) body.engine = engine;
      return api('/answer-snapshots/probe', {
        method: 'POST',
        body: body,
      });
    },
    probeAnswerSnapshotBatch: function (promptId, engines) {
      var body = { prompt_id: promptId };
      if (engines && engines.length) body.engines = engines;
      return api('/answer-snapshots/probe-batch', {
        method: 'POST',
        body: body,
      });
    },
    extractAnswerSnapshotUrls: function (rawText) {
      return api('/answer-snapshots/extract-urls', {
        method: 'POST',
        body: { raw_text: rawText || '' },
      });
    },
    suggestAnswerSnapshotFields: function (rawText, promptId) {
      var body = { raw_text: rawText || '', use_llm: true };
      if (promptId) body.prompt_id = promptId;
      return api('/answer-snapshots/suggest-fields', {
        method: 'POST',
        body: body,
      });
    },
    patchAnswerSnapshot: function (id, body) {
      return api('/answer-snapshots/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    competitorInsights: function () {
      return api('/competitor-insights', { query: withTenantQuery() });
    },
    evaluationInsights: function () {
      return api('/evaluation-insights', { query: withTenantQuery() });
    },
    citationInsights: function () {
      return api('/citation-insights', { query: withTenantQuery() });
    },
    getAiSettings: function () {
      return api('/ai-settings', { query: withTenantQuery() });
    },
    putAiSettings: function (body) {
      return api('/ai-settings', { method: 'PUT', body: body || {} });
    },
    testAiSettings: function () {
      return api('/ai-settings/test', {
        method: 'POST',
        query: withTenantQuery(),
        body: {},
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
    channelBlueprint: function (group) {
      var query = withTenantQuery();
      if (group) query.group = group;
      return api('/channel-blueprint', { query: query });
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
    listPublishingChannels: function (enabledOnly) {
      var query = withTenantQuery();
      if (enabledOnly) query.enabled_only = true;
      return api('/publishing-channels', { query: query });
    },
    createPublishingChannel: function (body) {
      return api('/publishing-channels', { method: 'POST', body: body });
    },
    patchPublishingChannel: function (id, body) {
      return api('/publishing-channels/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    listChannelAccounts: function (channelId) {
      var query = withTenantQuery();
      if (channelId) query.channel_id = channelId;
      return api('/channel-accounts', { query: query });
    },
    createChannelAccount: function (body) {
      return api('/channel-accounts', { method: 'POST', body: body });
    },
    patchChannelAccount: function (id, body) {
      return api('/channel-accounts/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    listTickets: function (query) {
      return api('/action-tickets', { query: withTenantQuery(query) });
    },
    createTicket: function (body) {
      return api('/action-tickets', {
        method: 'POST',
        query: withTenantQuery(),
        body: body,
      });
    },
    patchTicket: function (id, body) {
      return api('/action-tickets/' + id, {
        method: 'PATCH',
        query: withTenantQuery(),
        body: body,
      });
    },
    verifyTicket: function (id, recrawl) {
      return api('/action-tickets/' + id + '/verify', {
        method: 'POST',
        query: Object.assign(withTenantQuery(), { recrawl: recrawl !== false }),
      });
    },
    materializeTickets: function (auditId, replaceOpen) {
      return api('/audits/' + auditId + '/tickets', {
        method: 'POST',
        query: Object.assign(withTenantQuery(), { replace_open: !!replaceOpen }),
      });
    },
    verifyAuditTickets: function (auditId, recrawl) {
      return api('/audits/' + auditId + '/verify', {
        method: 'POST',
        query: Object.assign(withTenantQuery(), { recrawl: recrawl !== false }),
      });
    },
    latestAudit: function () {
      return api('/audits/latest', { query: withTenantQuery() });
    },
  };
})(window);
