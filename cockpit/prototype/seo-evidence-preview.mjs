// Independent synthetic scenarios using the reviewed SEO display contract.
import { seoWorkbenchDisplay } from './seo-workbench-display.mjs?v=20260907-52';

const cases = {
  unlinked: { label: '发布了，检查待确认', state: 'published', mapping: 'unmapped', explanation: '发布记录已经成功，但尚未找到明确关联的检查页面。下一步先核对发布地址和页面归属，再看检查结果。' },
  checked: { label: '检查了，效果待看', state: 'published', mapping: 'matched', explanation: '已找到对应页面，也有检查记录；这只能说明检查运行过。整页是否通过、文章带来多少点击，仍需各自的依据。' },
  failed: { label: '发布失败，先处理', state: 'failed', mapping: 'not_linked', explanation: '这条发布记录仍然失败。一次尝试成功或存在网址，都不能把最终发布状态改成成功。先查看失败原因，再安排处理。' },
};

function display(key) {
  const item = cases[key];
  return seoWorkbenchDisplay({
    publications: [{ id: 901, state: item.state, platform_code: '示例平台', page_url: 'https://example.invalid/article', latest_attempt: { id: 902, status: 'success' } }],
    publication_summary: { record_count: 1, successful_count: item.state === 'published' ? 1 : 0, failed_count: item.state === 'failed' ? 1 : 0 },
    page_evidence: { mapping_state: item.mapping, page_id: item.mapping === 'matched' ? 903 : null, check_state: 'assessed', passed: null, http_status: 200 },
    search_performance: { state: 'unavailable', article_clicks: null },
  });
}

function open(key = 'unlinked') {
  if (!Object.hasOwn(cases, key)) return;
  const view = display(key);
  showDialog('SEO / 发布与效果演示', `<div class="seo-depth"><small>独立合成场景 · 非客户实测</small><h2>发布、检查、效果，分开看清</h2><div class="seo-actions">${Object.entries(cases).map(([id,item]) => `<button data-seo-contract="${id}" aria-pressed="${id === key}">${item.label}</button>`).join('')}</div><div class="seo-search-kpis"><div><b>${view.publication.successfulCount}/1</b><span>发布成功 / 发布记录</span></div><div><b>${view.pageCheck.state === 'assessed' ? '1' : '—'}</b><span>已关联页面的检查记录</span></div><div><b>${view.searchPerformance.valueText}</b><span>本篇搜索点击</span></div></div><div class="seo-checks"><div><span>发布记录</span><b>${esc(view.publication.items[0].label)}</b></div><div><span>页面检查</span><b>${esc(view.pageCheck.label)}</b></div><div><span>整页通过结论</span><b>${esc(view.pageCheck.outcomeLabel)}</b></div></div><p>${cases[key].explanation}</p><div class="seo-actions"><button data-seo-contract-talk="${key}">和助手讨论这一步</button><button data-seo-contract-close>回到看板</button></div></div>`);
}

const originalBody = pCardBody;
pCardBody = function(key, scope) {
  return originalBody(key, scope) + (key === 'content' ? '<button class="seo-entry" data-seo-contract="unlinked">发布以后，怎样看进展？ ↗</button>' : '');
};
window.addEventListener('click', event => {
  const button = event.target.closest('[data-seo-contract], [data-seo-contract-talk], [data-seo-contract-close]');
  if (!button) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (button.hasAttribute('data-seo-contract-close')) return closeDialog();
  if (button.hasAttribute('data-seo-contract-talk')) {
    const key = button.dataset.seoContractTalk;
    if (!Object.hasOwn(cases, key)) return;
    closeDialog();
    showChat();
    addMessage('user', `SEO 独立演示：${cases[key].label}，下一步怎么看？`);
    addMessage('assistant', `<p><strong>独立合成场景 · ${cases[key].label}</strong></p><p>${cases[key].explanation}</p><p>单篇点击暂未接入，不把未知写成零，也不从站点点击分摊。</p><button class="seo-entry" data-seo-contract="${key}">返回这个演示状态 ↗</button>`);
  } else open(button.dataset.seoContract);
}, true);
renderPanorama();
