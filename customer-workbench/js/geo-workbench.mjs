import {escapeText as esc} from './customer-display.mjs';
import {createSearchVisibilityPanel} from './search-visibility-panel.mjs';
import {createGeoProjectPanel} from './geo-project-panel.mjs';

export function mountGeoWorkbench({root, host, logout, initialOnsiteTaskId = null, selectSpaceHref = '/customer-workbench/'}) {
  root.classList.add('customer-connected');
  let identity = null, busy = false, message = '', epoch = 0;
  const project = createGeoProjectPanel({host, onNavigate: () => render()});
  // This customer surface stays read-only even when an advisor has edit permissions.
  const visibility = createSearchVisibilityPanel({host, getUser: () => null});
  function render() {
    root.innerHTML = `<header><b>G-SNIPERS</b><span>客户工作台 · GEO</span><small>${identity ? esc(identity.tenant.name + ' / ' + identity.project.name) : '正在核验客户与项目'}</small><a href="${esc(selectSpaceHref)}">选择工作空间</a><button data-action="logout">退出登录</button></header><main class="connected-main"><p role="status">${esc(message)}</p>${identity ? '<div data-geo-workspace></div><div data-search-visibility></div>' : `<section class="page-card"><h2>GEO 项目交付</h2><button data-action="connect" ${busy ? 'disabled' : ''}>重新核验</button><a href="/customer-workbench/?module=geo">重新选择 GEO 项目</a></section>`}</main>`;
    if (identity) {
      project.renderInto(root.querySelector('[data-geo-workspace]'));
      const container = root.querySelector('[data-search-visibility]');
      container.hidden = !['home', 'data'].includes(project.getTab());
      visibility.renderInto(container);
    }
  }
  async function connect() {
    const stamp = ++epoch;
    project.reset(); visibility.reset(); identity = null; busy = true; message = '正在核验…'; render();
    try {
      const result = await host.initialize();
      if (stamp !== epoch) return;
      identity = result.identity;
      if (!identity) throw Error('GEO_IDENTITY_UNAVAILABLE');
      message = ''; render();
      await Promise.allSettled([project.refresh(), visibility.refresh()]);
      if (stamp === epoch && Number.isSafeInteger(initialOnsiteTaskId) && initialOnsiteTaskId > 0)
        await project.showOnsite();
    } catch {
      if (stamp === epoch) { identity = null; message = '暂无数据，请重新核验客户与项目。'; }
    } finally { if (stamp === epoch) { busy = false; render(); } }
  }
  const unsubscribe = host.subscribe(() => {
    epoch++; project.reset(); visibility.reset(); identity = null; busy = false;
    message = '身份或客户范围已变化，旧数据已清除。'; render();
  });
  function click(event) {
    const element = event.target.closest('[data-action]');
    if (!element || element.disabled) return;
    if (element.dataset.action === 'logout') logout();
    if (element.dataset.action === 'connect') void connect();
  }
  root.addEventListener('click', click);
  void connect();
  return {dispose() {
    epoch++; unsubscribe(); project.dispose(); visibility.dispose(); host.dispose();
    root.removeEventListener('click', click); root.replaceChildren();
  }};
}
