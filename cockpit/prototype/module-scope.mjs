// Presentation scope only. Server authorization remains authoritative.
export const MODULES = Object.freeze(['sem', 'seo', 'geo']);

const CARDS = Object.freeze({
  trend: ['sem'], semkeywords: ['sem'], mix: ['sem'], funnel: ['sem'], device: ['sem'],
  organic: ['seo'], content: ['seo'], ranking: ['seo'],
  heatmap: ['geo'], citations: ['geo'], competition: ['geo'],
  journey: ['sem', 'seo', 'geo'],
});
const QUESTIONS = Object.freeze({
  sem: ['广告花费和点击有什么变化？', '哪些平台转化需要核实？'],
  seo: ['哪些内容还需要审核？', '发布之后，页面检查到哪一步？'],
  geo: ['哪些回答提到了品牌？', '这两周的数据可以比较吗？'],
});

export function moduleScope(entitlements) {
  // An absent or unknown entitlement never silently enables all three modules.
  const enabled = MODULES.filter(module => Array.isArray(entitlements) && entitlements.includes(module));
  return {
    enabled,
    unavailable: MODULES.filter(module => !enabled.includes(module)),
    cards: Object.entries(CARDS).filter(([, required]) => required.every(module => enabled.includes(module))).map(([key]) => key),
    comparisonModules: enabled.length >= 2 ? [...enabled] : [],
    showCrossChannel: enabled.length === 3,
    questions: enabled.flatMap(module => QUESTIONS[module].map(text => ({ module, text }))),
    empty: enabled.length === 0,
  };
}

export function scopedMetrics(metrics, entitlements) {
  const { enabled } = moduleScope(entitlements);
  return Object.fromEntries(MODULES.map(module => [module,
    enabled.includes(module)
      ? { state: metrics?.[module] == null ? 'no_data' : Number.isFinite(metrics[module]) ? 'available' : 'invalid', value: Number.isFinite(metrics?.[module]) ? metrics[module] : null }
      : { state: 'not_enabled', value: null },
  ]));
}

export function taskInModuleScope(task, entitlements) {
  const modules = task?.modules ?? (typeof task?.module === 'string' ? [task.module] : null);
  if (task?.module !== undefined && task?.modules !== undefined) {
    if (!Array.isArray(task.modules) || new Set(task.modules).size !== 1 || task.modules[0] !== task.module) return false;
  }
  // Unknown task provenance is not a reason to assign it to an arbitrary module.
  return Array.isArray(modules) && modules.length > 0
    && modules.every(module => MODULES.includes(module) && moduleScope(entitlements).enabled.includes(module));
}

export function taskScopeReference(task) {
  if (task?.module !== undefined || task?.modules !== undefined) return task;
  return { ...task, module: ({ allocation: 'sem', images: 'seo', visibility: 'geo' })[task?.issue] };
}

export function planInModuleScope(type, entitlements) {
  const types = {
    verify: ['sem'], trend: ['sem'], mix: ['sem'], funnel: ['sem'], device: ['sem'],
    content: ['seo'], organic: ['seo'], ranking: ['seo'],
    geo: ['geo'], heatmap: ['geo'], citations: ['geo'], competition: ['geo'],
  };
  // A generic/cross-channel card does not itself identify an executable action.
  if (!Object.hasOwn(types, type)) return false;
  return taskInModuleScope({ modules: types[type] }, entitlements);
}

export function panelInModuleScope(key, snapshot, entitlements) {
  const scope = moduleScope(entitlements);
  if (scope.empty) return false;
  if (scope.enabled.length === MODULES.length) return true;
  if (snapshot) return scope.cards.includes(snapshot.card) || snapshot.card === 'execution';
  const module = /^(sem|seo|geo):\d+$/.exec(key)?.[1];
  if (module) return scope.enabled.includes(module);
  const legacy = { spend: 'sem', organic: 'seo', visibility: 'geo' };
  return Object.hasOwn(legacy, key) && scope.enabled.includes(legacy[key]);
}

export function navigationAccess(page, entitlements) {
  const scope = moduleScope(entitlements);
  const requirements = {
    panorama: [], dashboard: [], tasks: [], quality: [],
    acquisition: ['sem'],
    overview: MODULES, module: null,
  };
  if (!Object.hasOwn(requirements, page) || scope.empty) {
    return { allowed: false, reason: '当前入口不可用。' };
  }
  if (page === 'module') {
    return { allowed: false, reason: '旧模块页已停用，请从全景工作台查看模块数据。' };
  }
  const allowed = requirements[page].every(module => scope.enabled.includes(module));
  if (allowed) return { allowed: true, reason: null };
  if (page === 'acquisition') return { allowed: false, reason: '预算试算需要开通 SEM。' };
  return { allowed: false, reason: '该入口仍包含多个模块，当前组合暂未开放，请使用全景工作台。' };
}

export function scopedCapabilities(capabilities, entitlements, query = '') {
  const enabled = moduleScope(entitlements).enabled;
  const needle = String(query).trim().toLocaleLowerCase('zh-CN');
  return enabled.flatMap(module => {
    const items = Array.isArray(capabilities?.[module]) ? capabilities[module] : [];
    return items.map((name, index) => ({ module, index, name: String(name) }))
      .filter(({ module: key, name }) => !needle
        || key.includes(needle)
        || name.toLocaleLowerCase('zh-CN').includes(needle));
  });
}

export function moduleEntryAccess(module, entitlements) {
  const cards = { sem: 'trend', seo: 'content', geo: 'heatmap' };
  if (!Object.hasOwn(cards, module)) {
    return { allowed: false, card: null, reason: '未知模块入口，未打开任何数据。' };
  }
  if (!moduleScope(entitlements).enabled.includes(module)) {
    return { allowed: false, card: null, reason: '当前客户未开通对应模块。' };
  }
  return { allowed: true, card: cards[module], reason: null };
}
