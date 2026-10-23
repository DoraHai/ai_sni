import {createGeoProjectClient} from './geo-project-client.mjs';
import {geoTabs, geoHome, geoResource, geoExecutions, geoStatus} from './geo-project-view.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {geoQuestionFilters} from './geo-project-insights.mjs';
export function createGeoProjectPanel({host, onNavigate = () => {}, canNavigate = () => true}) {
  const client = createGeoProjectClient({transport: host.transport, getContext: host.getContext});
  let node = null,
    epoch = 0,
    disposed = false,
    tab = 'home',
    slots = {},
    week = null,
    requestedWeek = null,
    active = null,
    history = [],
    actionError = null,
    downloading = false;
  const available = (key) => !!slots[key]?.value;
  function tabs() {
    return geoTabs.filter(
      ([key]) =>
        key === tab ||
        ['home', 'onsite', 'data', 'deliveries'].includes(key) ||
        (key === 'work' &&
          (slots.questions?.value?.data.items.length > 0 ||
            slots.content?.value?.data.items.length > 0)) ||
        (key === 'content' && slots.content?.value?.data.items.length > 0) ||
        (['progress', 'plan'].includes(key) && available('executions')) ||
        (key === 'data' &&
          (available('visibility') || slots.questions?.value?.data.items.length > 0)),
    );
  }
  function paint() {
    if (!node) return;
    const slot = active?.slot;
    let body =
      tab === 'home'
        ? geoHome(slots)
        : tab === 'onsite'
          ? `<h2>站内优化</h2><p>仅展示本项目已审核的站内建议与进度。</p>${active?.slot?.value ? geoResource('recommendations', active.slot.value) : `<p>${geoStatus(active?.slot)}</p><button data-geo="retry">重新读取建议</button>`}`
          : tab === 'progress' || tab === 'plan'
            ? slots.executions?.value
              ? geoExecutions(slots.executions.value, tab === 'plan')
              : `<h2>${tab === 'plan' ? '服务计划' : '项目进度'}</h2><p>${geoStatus(slots.executions)}</p><button data-geo="refresh-executions">重新读取</button>`
            : active
              ? slot?.value
                ? geoResource(active.resource, slot.value)
                : `<p role="status">${geoStatus(slot)}</p>${slot?.loading ? '' : '<button data-geo="retry">重新读取</button>'}`
              : '<p>暂未开放</p>';
    if (tab === 'work')
      body =
        '<h2>GEO工作</h2><p>查看项目问题与已交付内容；官网建议见站内优化标签。</p><button data-geo="read" data-resource="questions">项目问题</button><button data-geo="read" data-resource="content">内容任务</button>' +
        body;
    if (active?.resource === 'questions' && active.slot?.value) {
      // Keep the selected filters even when an older backend omits data.filters.
      body = body.replace(/<form data-geo-questions>[\s\S]*?<\/form>/,
        () => geoQuestionFilters(active.slot.value.data, active.params));
    }
    const summary = tab === 'data' && active?.resource !== 'questions'
      ? slots.summary?.value ? geoResource('summary', slots.summary.value)
        : `<h2>品牌表现汇总</h2><p>${geoStatus(slots.summary)}</p><button data-geo="refresh-summary">重新读取汇总</button>`
      : '';
    const citations = tab === 'deliveries'
      ? '<button data-geo="read" data-resource="article-citations">已发布文章引用率</button><button data-geo="read" data-resource="deliveries">发布登记与投递回执</button>' : '';
    const weekForm =
      tab === 'data'
        ? `<form data-geo-week><label>统计周期结束后的周一（北京时间） <input name="week_end" type="date" value="${esc(week || '')}" required></label><button>查看该周</button></form><p>正式指标来自已保存检测结果，历史按当前项目归属重算。</p><button data-geo="read" data-resource="visibility">AI 可见度概览</button><button data-geo="read" data-resource="questions">问题监测</button><button data-geo="read" data-resource="answers">回答证据</button><button data-geo="download" data-format="pdf" ${downloading ? 'disabled' : ''}>下载 PDF 报告</button><button data-geo="download" data-format="xlsx" ${downloading ? 'disabled' : ''}>下载 Excel 报告</button>${downloading ? '<p role="status">正在读取报告…</p>' : ''}`
        : '';
    node.innerHTML = `<nav class="geo-tabs" aria-label="GEO 工作台">${tabs()
      .map(
        ([key, name]) =>
          `<button data-geo="tab" data-tab="${key}" ${key === tab ? 'aria-current="page"' : ''}>${name}</button>`,
      )
      .join(
        '',
      )}<button data-geo="read" data-resource="questions" ${active?.resource === 'questions' ? 'aria-current="page"' : ''}>全部问题</button></nav><section class="page-card geo-workspace">${tab === 'home' ? '<button data-geo="refresh">重新读取概览</button>' : ''}${weekForm}${summary}${citations}${actionError ? `<p role="alert">${geoStatus({error: actionError})}</p>` : ''}${history.length ? '<button data-geo="back">返回上一层</button>' : ''}${body}${slot?.value && slot.loading ? '<p role="status">正在读取下一页…</p>' : ''}${slot?.value && slot.error ? `<p role="status">${geoStatus(slot)}</p><button data-geo="retry">重新读取</button>` : ''}</section>`;
  }
  const weekly = (resource) =>
    ['overview', 'visibility', 'questions', 'answers', 'summary', 'article-citations'].includes(resource.split('/')[0]);
  function clearForError(e) {
    if (['PERMISSION_DENIED', 'AUTH_EXPIRED', 'GEO_CONTEXT_CHANGED', 'GEO_SCOPE_CHANGED'].includes(e.code) || [401, 403, 409].includes(e.status)) {
      epoch++;
      client.invalidate();
      slots = {};
      history = [];
      active = null;
      downloading = false;
      actionError = e.code;
      paint();
      return true;
    }
    return false;
  }
  function paramsFor(resource, params) {
    return {...params, ...(weekly(resource) && week ? {week_end: week} : {})};
  }
  async function readSlot(resource, params = {}, target = null) {
    const stamp = epoch,
      slot = {loading: true, value: null, error: null};
    if (target) target.slot = slot;
    else slots[resource] = slot;
    paint();
    try {
      const value = await client.read(resource, params);
      if (disposed || stamp !== epoch) return;
      slot.value = value;
      if (weekly(resource) && !week) week = value.basis.period.week_end;
    } catch (e) {
      if (disposed || stamp !== epoch) return;
      if (clearForError(e)) return;
      slot.error = e.code || 'GEO_READ_FAILED';
    } finally {
      if (!disposed && stamp === epoch) {
        slot.loading = false;
        paint();
      }
    }
    return slot;
  }
  async function refresh() {
    const stamp = ++epoch;
    client.invalidate();
    slots = {};
    actionError = null;
    active = null;
    history = [];
    week = requestedWeek;
    paint();
    await Promise.allSettled([
      readSlot('overview', week ? {week_end: week} : {}),
      readSlot('executions'),
    ]);
    if (disposed || stamp !== epoch) return;
    await readSlot('visibility', week ? {week_end: week} : {});
    if (disposed || stamp !== epoch) return;
    await Promise.allSettled(
      ['questions', 'content', 'deliveries', 'summary', 'article-citations', 'recommendations'].map((r) => readSlot(r, paramsFor(r, {}))),
    );
    if (disposed || stamp !== epoch) return;
    if (tab !== 'home' && tab !== 'onsite' && tab !== 'plan' && tab !== 'progress')
      await selectTab(tab);
  }
  function reset() {
    epoch++;
    client.invalidate();
    slots = {};
    actionError = null;
    active = null;
    history = [];
    week = null;
    requestedWeek = null;
    downloading = false;
    tab = 'home';
    paint();
  }
  async function open(resource, params = {}, keepTab = false) {
    if (active)
      history.push({tab, resource: active.resource, params: active.params, slot: active.slot});
    const next = resource.startsWith('content')
      ? 'content'
      : ['deliveries', 'article-citations'].includes(resource)
        ? 'deliveries'
        : resource === 'recommendations' ? 'onsite' : 'data';
    if (!keepTab && tab !== next) {
      tab = next;
      onNavigate(tab);
    }
    const target = {resource, params: paramsFor(resource, params), slot: null};
    active = target;
    paint();
    await readSlot(resource, target.params, target);
  }
  async function selectTab(next) {
    if (!geoTabs.some(([key]) => key === next)) return;
    tab = next;
    active = null;
    history = [];
    onNavigate(tab);
    const resource = {
      content: 'content',
      work: 'questions',
      data: 'visibility',
      deliveries: 'deliveries',
      onsite: 'recommendations',
    }[tab];
    if (resource) {
      active = {resource, params: paramsFor(resource, {}), slot: slots[resource] || null};
      paint();
      if (!active.slot?.value) await readSlot(resource, active.params, active);
    } else paint();
  }
  async function more() {
    const target = active,
      p = target?.slot?.value?.data.pagination;
    if (!p?.has_more || target.slot.loading) return;
    const stamp = epoch,
      slot = target.slot;
    slot.loading = true;
    slot.error = null;
    paint();
    try {
      const value = await client.read(target.resource, {...target.params, cursor: p.next_cursor});
      if (disposed || stamp !== epoch || active !== target) return;
      const items = [...slot.value.data.items, ...value.data.items];
      // Items accumulate across pages; pagination describes the last server page.
      // Display uses items.length and total_count, never returned_count as a total.
      slot.value = {...value, data: {...value.data, items}};
    } catch (e) {
      if (disposed || stamp !== epoch || active !== target) return;
      if (e.code === 'GEO_SCOPE_CHANGED') {
        clearForError(e);
        await open(target.resource, {...target.params, cursor: null});
        return;
      }
      if (clearForError(e)) return;
      if (['GEO_SCOPE_CHANGED', 'GEO_CURSOR_INVALID', 'GEO_NOT_OPEN'].includes(e.code)) {
        target.slot = {error: e.code, loading: false, value: null};
        history = [];
        if (e.code !== 'GEO_NOT_OPEN') await readSlot(target.resource, target.params, target);
      } else slot.error = e.code || 'GEO_READ_FAILED';
    } finally {
      if (!disposed && stamp === epoch) {
        slot.loading = false;
        paint();
      }
    }
  }
  async function click(event) {
    const el = event.target.closest('[data-geo]');
    if (!el || el.disabled || !canNavigate()) return;
    actionError = null;
    const action = el.dataset.geo;
    if (action === 'tab') await selectTab(el.dataset.tab);
    if (action === 'read') {
      let params = {};
      try {
        params = JSON.parse(el.dataset.params || '{}');
        if (!params || typeof params !== 'object' || Array.isArray(params))
          throw Error('GEO_ACTION_INVALID');
      } catch {
        actionError = 'GEO_ACTION_INVALID';
        paint();
        return;
      }
      await open(el.dataset.resource, params, tab === 'work');
    }
    if (action === 'back') {
      active = history.pop() || null;
      if (active?.tab && tab !== active.tab) {
        tab = active.tab;
        onNavigate(tab);
      }
      paint();
    }
    if (action === 'refresh') await refresh();
    if (action === 'refresh-executions') await readSlot('executions');
    if (action === 'refresh-summary') await readSlot('summary', paramsFor('summary', {}));
    if (action === 'clear-filters') {
      history = [];
      active = null;
      await open('questions');
    }
    if (action === 'download' && !downloading && ['pdf', 'xlsx'].includes(el.dataset.format)) {
      const stamp = epoch;
      downloading = true;
      paint();
      try {
        const report = await client.read('reports/export.' + el.dataset.format, week ? {week_end: week} : {});
        if (disposed || stamp !== epoch) return;
        const url = URL.createObjectURL(new Blob([report.bytes], {type: report.type}));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = report.filename;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (e) {
        if (!disposed && stamp === epoch && !clearForError(e)) actionError = e.code || 'GEO_READ_FAILED';
      } finally {
        if (!disposed && stamp === epoch) { downloading = false; paint(); }
      }
    }
    if (action === 'retry' && active) await readSlot(active.resource, active.params, active);
    if (action === 'more') await more();
  }
  async function submit(event) {
    const form = event.target;
    if (form.matches('[data-geo-questions]') && form.elements.business_id) {
      event.preventDefault();
      if (!canNavigate()) return;
      const params = Object.fromEntries(['business_id', 'unit_id', 'q'].map((key) => [key, form.elements[key].value.trim()]));
      history = [];
      active = null;
      await open('questions', params);
      return;
    }
    if (!form.matches('[data-geo-week]')) return;
    event.preventDefault();
    if (!canNavigate()) return;
    actionError = null;
    requestedWeek = event.target.elements.week_end.value;
    await refresh();
  }
  return {
    refresh,
    reset,
    showOnsite: () => selectTab('onsite'),
    getTab: () => tab,
    renderInto(element) {
      node = element;
      node.onclick = click;
      node.onsubmit = submit;
      node.onchange = (event) => {
        if (event.target.name !== 'business_id') return;
        const form = event.target.closest('[data-geo-questions]');
        if (!form) return;
        form.elements.unit_id.value = '';
        const options = active?.slot?.value?.data.options?.units || [];
        for (const option of form.elements.unit_id.options) {
          option.hidden = !!option.value && !!event.target.value &&
            !options.some((u) => String(u.id) === option.value && String(u.business_id) === event.target.value);
        }
      };
      paint();
    },
    dispose() {
      disposed = true;
      reset();
      node = null;
    },
  };
}
