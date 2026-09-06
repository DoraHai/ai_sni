// Independent synthetic SEM evidence scenarios. Display helper copied unchanged from main 70018543b9e08edf411c0ac0263ff1a38f925502.
import { semMetric, semPhoneClicks } from './sem-cockpit-display.mjs?v=20260907-63';

const scenarios = Object.freeze({
  missing: {
    label: '少 1 天报告', metric: '投放花费', account: '示例搜索账户 01', dates: '2026.08.31 — 09.06', updated: '2026.09.07 09:20 · 上海时间',
    coverage: '7 天中已有 6 天报告，09.03 缺失', value: 42110, unit: 'CNY', missing_dates: ['2026-09-03'],
    explanation: '这笔金额只合计了已经收到的 6 天报告。缺少的一天可能还有花费，所以不能把它当作完整 7 天总数。',
    evidence: [['应有报告', '7 天'], ['已有报告', '6 天'], ['缺少日期', '2026.09.03'], ['计算方式', '只合计已有报告']],
  },
  zero: {
    label: '已观测为 0', metric: '报表转化', account: '示例搜索账户 02', dates: '2026.09.01 — 09.07', updated: '2026.09.07 10:05 · 上海时间',
    coverage: '所选 7 天未发现缺报；上游完整性仍待确认', value: 0, unit: 'count', missing_dates: [],
    explanation: '这里的 0 来自所选日期已有的报告，表示这些报告记录的转化为 0。它与没有报告不同，也不等于已经确认没有有效商机。',
    evidence: [['应有报告', '7 天'], ['已有报告', '7 天'], ['缺少日期', '无'], ['业务含义', '报表记录为 0，商机仍需另行核实']],
  },
  phone: {
    label: '电话点击部分有依据', metric: '电话按钮点击', account: '示例搜索账户 03', dates: '2026.09.01 — 09.07', updated: '2026.09.07 10:30 · 上海时间',
    coverage: '7 条记录中 5 条有点击依据，2 条缺少依据',
    phone: { status: 'partial', value: null, known_subtotal: 3, stored_rows: 7, known_rows: 5, unknown_rows: 2 },
    explanation: '目前只能确认有依据记录中的 3 次按钮点击。另有 2 条记录缺少依据，因此 3 次只是已知小计；按钮点击也不代表电话拨通或形成有效咨询。',
    evidence: [['报告记录', '7 条'], ['有点击依据', '5 条'], ['缺少依据', '2 条'], ['已知小计', '3 次电话按钮点击']],
  },
});

export const semEvidenceSourceRevision = '70018543b9e08edf411c0ac0263ff1a38f925502';

export function semEvidenceView(key = 'missing') {
  const safeKey = Object.hasOwn(scenarios, key) ? key : 'missing';
  const scenario = scenarios[safeKey];
  const result = scenario.phone
    ? semPhoneClicks(scenario.phone)
    : semMetric(scenario.value, scenario.unit, { status: 'observed', missing_dates: scenario.missing_dates });
  return { key: safeKey, ...scenario, result };
}

function preview(key = 'missing', evidence = false) {
  const view = semEvidenceView(key);
  const proof = evidence ? `<section><h3>这项数字的依据</h3><dl class="seo-facts">${view.evidence.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join('')}<dt>数据来源</dt><dd>本地合成记录 · 未连接客户账户</dd></dl><p>${esc(view.result.note)}</p><div class="seo-actions"><button data-sem-evidence-state="${view.key}">返回当前场景</button></div></section>` : '';
  showDialog('SEM / 报告覆盖演示', `<div class="seo-depth"><small>独立演示 · 不计入客户总览</small><h2>先看报告是否完整，再看数字</h2><div class="geo-engine-switch" aria-label="切换 SEM 数据状态">${Object.entries(scenarios).map(([id, item]) => `<button data-sem-evidence-state="${id}" aria-pressed="${id === view.key}">${item.label}</button>`).join('')}</div><div class="seo-stages"><div><b>${esc(view.result.text)}</b><span>${esc(view.metric)}</span></div><div><b>${view.result.state === 'partial' ? '部分覆盖' : '已有报告'}</b><span>当前覆盖状态</span></div></div><dl class="seo-facts"><dt>统计日期</dt><dd>${esc(view.dates)}</dd><dt>示例账户</dt><dd>${esc(view.account)}</dd><dt>报告覆盖</dt><dd>${esc(view.coverage)}</dd><dt>更新时间</dt><dd>${esc(view.updated)}</dd><dt>与总览关系</dt><dd>独立合成场景，不改变客户总览</dd></dl><p>${esc(view.explanation)}</p>${proof}<div class="seo-actions"><button data-sem-evidence-proof="${view.key}">查看数字依据</button><button data-sem-evidence-discuss="${view.key}">解释当前场景</button><button data-sem-evidence-close>回到看板</button></div></div>`);
}

function discuss(key) {
  const view = semEvidenceView(key);
  closeDialog();
  showChat();
  addMessage('user', `SEM 数据状态演示：${view.label}，为什么不能直接当成完整结果？`);
  addMessage('assistant', `<p><strong>独立演示 · ${esc(view.label)}</strong></p><p>${esc(view.explanation)}</p><p>统计日期：${esc(view.dates)}；示例账户：${esc(view.account)}；${esc(view.coverage)}。这段解释不改变客户总览，也没有读取或执行真实业务。</p><button class="seo-entry" data-sem-evidence-state="${view.key}">返回当前场景 ↗</button>`);
}

if (typeof window !== 'undefined') {
  const originalBody = pCardBody;
  pCardBody = function(key, scope) {
    return originalBody(key, scope) + (key === 'trend' ? '<button class="seo-entry" data-sem-evidence-state="missing">报告不完整时，数字怎么看？ ↗</button>' : '');
  };
  window.addEventListener('click', event => {
    const button = event.target.closest('[data-sem-evidence-state], [data-sem-evidence-proof], [data-sem-evidence-discuss], [data-sem-evidence-close]');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (button.hasAttribute('data-sem-evidence-close')) closeDialog();
    else if (button.hasAttribute('data-sem-evidence-proof')) preview(button.dataset.semEvidenceProof, true);
    else if (button.hasAttribute('data-sem-evidence-discuss')) discuss(button.dataset.semEvidenceDiscuss);
    else preview(button.dataset.semEvidenceState);
  }, true);
  renderPanorama();
}
