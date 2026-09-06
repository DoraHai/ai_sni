import { MODULES, moduleScope, taskInModuleScope, taskScopeReference, planInModuleScope, panelInModuleScope, navigationAccess } from './module-scope.mjs?v=20260907-59';

// Local customer-profile rehearsal. This selection never grants API permissions.
let enabled = [...MODULES];
const names = { sem: '广告投放', seo: '内容与搜索', geo: 'AI 品牌表现' };
const profile = () => moduleScope(enabled);
const partial = () => enabled.length !== 3;
const rawTasks = allTasks;
allTasks = () => rawTasks().filter(task => taskInModuleScope(taskScopeReference(task), enabled));

function selector() {
  return `<label>演示客户已开通 <select id="customerModuleProfile" aria-label="演示客户开通组合">${Array.from({ length: 7 }, (_, i) => {
    const modules = MODULES.filter((_, index) => (i + 1) & (1 << index));
    return `<option value="${modules.join(',')}" ${modules.join(',') === enabled.join(',') ? 'selected' : ''}>${modules.map(module => module.toUpperCase()).join(' + ')}</option>`;
  }).join('')}</select></label>`;
}

function scopedHealth() {
  return enabled.map(module => `<p><strong>${names[module]}</strong> · 演示数据 · 真实连接未接入</p>`).join('')
    + '<p>未开通的模块不参与当前看板；真实访问权限仍由服务器核验。</p>';
}

function suggestions() {
  if (!partial()) return;
  $('#chatSuggestions').innerHTML = profile().questions.map(({ module, text }) => `<button data-profile-question="${module}">${text}</button>`).join('');
  const welcome = document.querySelector('.first-welcome .first-starts button span');
  if (welcome) welcome.textContent = enabled.map(module => names[module]).join('、') + ' ↗';
}

function decorateNavigation() {
  document.querySelectorAll('.page-tabs [data-page]').forEach(button => {
    const access = navigationAccess(button.dataset.page, enabled);
    if (!button.dataset.scopeLabel) button.dataset.scopeLabel = button.textContent.trim();
    if (access.allowed) {
      if (button.dataset.scopeDisabled === 'true') button.textContent = button.dataset.scopeLabel;
      button.disabled = false;
      delete button.dataset.scopeDisabled;
      button.removeAttribute('title');
      button.removeAttribute('aria-label');
      return;
    }
    button.disabled = true;
    button.dataset.scopeDisabled = 'true';
    button.textContent = `${button.dataset.scopeLabel} · ${button.dataset.page === 'acquisition' ? '需 SEM' : '需全模块'}`;
    button.title = access.reason;
    button.setAttribute('aria-label', `${button.dataset.scopeLabel}，${access.reason}`);
  });
}

function scopedView() {
  if (!partial()) {
    panoPage.querySelector('.p-controls')?.insertAdjacentHTML('beforeend', selector());
    return;
  }
  const scope = profile();
  if (!scope.cards.includes(pano.focus)) pano.focus = scope.cards[0];
  const controls = panoPage.querySelector('.p-controls:has(#pStart)')?.innerHTML || '';
  const cards = [...scope.cards, 'execution', 'health'];
  panoPage.innerHTML = `<div class="p-heading"><div><h1>${enabled.map(module => names[module]).join(' · ')}</h1><p>诺德新材料 · 客户模块组合演示 · 未开通模块不计入当前结果</p></div></div><div class="p-controls">${selector()}</div><div class="p-controls">${controls}</div><p class="p-scope">${pScope()} · ${enabled.map(module => module.toUpperCase()).join(' / ')}</p><div class="p-grid">${cards.map(key => `<article class="p-card" data-card="${key}"><header><div><small>${panoCards[key][0]}</small><h2>${panoCards[key][1]}</h2></div><button data-profile-open="${key}">查看明细 ↗</button></header><div class="p-body">${key === 'health' ? scopedHealth() : pCardBody(key)}</div><footer><span>${panoCards[key][2]}</span><button data-profile-discuss="${key}">和助手讨论 →</button></footer></article>`).join('')}</div>`;
  // Keep date inputs; cross-scope comparison/search still belong to the all-module view.
  panoPage.querySelectorAll('[data-pano="search"], [data-pano="compare"]').forEach(button => button.remove());
  pContext();
  suggestions();
}

const originalRender = renderPanorama;
renderPanorama = function(...args) { originalRender(...args); scopedView(); };

const originalOpen = pOpen;
const originalPanelOpen = openPanel;
openPanel = function(key, ...args) {
  if (!panelInModuleScope(key, panoSnapshots.get(key), enabled)) return toast('该详情不属于当前开通模块。');
  return originalPanelOpen(key, ...args);
};
pOpen = function(key, ...args) {
  if (partial() && key === 'health') return showDialog('当前模块数据情况', `<h2>当前数据能说明什么？</h2>${scopedHealth()}`);
  if (partial() && ![...profile().cards, 'execution'].includes(key)) return toast('当前客户未开通对应模块。');
  return originalOpen(key, ...args);
};

const originalTalk = pTalk;
pTalk = function(key = 'overview', question = '', ...args) {
  if (!partial()) return originalTalk(key, question, ...args);
  if (question) addMessage('user', question);
  showChat();
  const stats = pStats();
  const summary = {
    sem: `投放花费 ${money(stats.cost)}，点击 ${stats.clicks}，平台记录转化 ${stats.conv} 次；是否有效还需核实。`,
    seo: `内容 ${pRows('content').length} 篇，搜索点击 ${pOrganic(stats.organic)}；发布、页面检查和搜索表现分别确认。`,
    geo: `模拟回答 ${stats.a.length} 条，提到品牌 ${stats.mentions} 条；不计入正式可见度。`,
  };
  addMessage('assistant', `<p><strong>当前开通：${enabled.map(module => names[module]).join('、')}</strong> · ${pScope()}</p>${enabled.map(module => `<p>${summary[module]}</p>`).join('')}<p>请选择下方问题或看板记录继续查看。这里是范围联动演示，没有调用真实 AI 或执行业务操作。</p>`);
  suggestions();
};

const originalReply = reply;
reply = function(question) { return partial() ? pTalk('overview', question) : originalReply(question); };
const originalSuggestions = pSuggestions;
pSuggestions = function(...args) { originalSuggestions(...args); suggestions(); };

const originalNavigate = navigate;
navigate = function(page, ...args) {
  const access = navigationAccess(page, enabled);
  if (!access.allowed) return toast(access.reason);
  return originalNavigate(page, ...args);
};
const originalQuality = renderQuality;
renderQuality = function() {
  if (!partial()) return originalQuality();
  $('#page-quality').innerHTML = `<div class="page-heading"><h1>当前模块的数据情况</h1></div>${scopedHealth()}`;
};

const originalTask = showTask;
showTask = function(id) {
  if (!allTasks().some(task => task.id === id)) return toast('该待办不属于当前开通模块。');
  return originalTask(id);
};
const originalPlan = pPlan;
pPlan = function(type = 'verify', ...args) {
  if (!planInModuleScope(type, enabled)) return toast('请从已开通模块选择一项具体行动。');
  return originalPlan(type, ...args);
};

window.addEventListener('change', event => {
  if (event.target.id !== 'customerModuleProfile') return;
  const next = moduleScope(event.target.value.split(',')).enabled;
  if (!next.length) return;
  const oldMessages = [...$('#chatStream').children].filter(node => !node.hasAttribute('data-profile-history') && !node.querySelector('.first-welcome'));
  if (oldMessages.length) {
    const archive = document.createElement('details');
    archive.dataset.profileHistory = enabled.join(',');
    const summary = document.createElement('summary');
    summary.textContent = `历史对话（${enabled.map(module => module.toUpperCase()).join(' + ')} · 非当前查看范围）`;
    archive.append(summary, ...oldMessages);
    $('#chatStream').append(archive);
  }
  enabled = next;
  // History is retained, but actions created under another profile cannot be reused.
  document.querySelectorAll('#chatStream button:not([data-first-start])').forEach(button => {
    if (partial() && !button.disabled) {
      button.disabled = true;
      button.dataset.profileDisabled = 'true';
      button.title = '开通组合已变化，请从当前看板重新查看';
    } else if (!partial() && button.dataset.profileDisabled === 'true') {
      button.disabled = false;
      delete button.dataset.profileDisabled;
      button.removeAttribute('title');
    }
  });
  decision.active = null;
  decision.allCharts = true;
  pano.compare = null;
  pano.history = [];
  closeDialog();
  // Discard all old windows: even a still-enabled module can contain old mixed-scope content.
  panels.forEach(panel => panel.el.remove());
  panels.clear();
  focusedPanel = null;
  dock();
  renderPanorama();
  renderTasks();
  decorateNavigation();
  pSuggestions();
  if (!partial()) {
    const welcome = document.querySelector('.first-welcome .first-starts button span');
    if (welcome) welcome.textContent = '广告、内容、AI 回答 ↗';
  }
  toast('已切换演示客户模块组合；历史对话保留。');
}, true);

window.addEventListener('click', event => {
  const brand = event.target.closest('a.brand');
  if (brand && partial()) {
    event.preventDefault();
    event.stopImmediatePropagation();
    navigate('panorama');
    return;
  }
  const restore = event.target.closest('[data-restore]');
  if (restore) {
    const panel = panels.get(restore.dataset.restore);
    if (!panel || !panelInModuleScope(panel.key, panoSnapshots.get(panel.key), enabled)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      toast('开通组合已变化，请从当前看板重新打开详情。');
      return;
    }
  }
  const button = event.target.closest('[data-profile-open], [data-profile-discuss], [data-profile-question]');
  if (!button) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (button.dataset.profileOpen) pOpen(button.dataset.profileOpen);
  else pTalk(button.dataset.profileDiscuss || 'overview', button.textContent);
}, true);
renderPanorama();
decorateNavigation();
