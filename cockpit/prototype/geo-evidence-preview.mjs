// Offline prototype consumer of reviewed #394 (00a6e9a) GEO display helpers. No API calls.
import { officialMetricDisplay, progressDisplay, answerSourceDisplay } from './geo-workbench-display.mjs?v=20260907-52';

const scenarios = {
  insufficient: { label: '样本不足', value: null, comparable: false, reasons: ['current_week_insufficient'] },
  zero: { label: '真实零值', value: 0, comparable: true, reasons: [] },
  incomparable: { label: '前后不可比', value: 25, comparable: false, reasons: ['cohort_changed'] },
};

function preview(key = 'insufficient') {
  key = Object.hasOwn(scenarios, key) ? key : 'insufficient';
  const scenario = scenarios[key];
  const model = officialMetricDisplay({ metric_key: 'geo.visibility.ai_mention_rate_7d', value: scenario.value, unit: 'percent', trend_7d: key === 'incomparable' ? { direction: 'up', change_pct: 50 } : null }, {
    comparison: { comparable: scenario.comparable, reason_codes: scenario.reasons },
    current: { reasons: scenario.reasons },
    metric_status: [{ metric_key: 'geo.visibility.ai_mention_rate_7d', reason_codes: scenario.reasons }],
  });
  const progress = progressDisplay({ stored_status: 'running', stale: true }, '回答检查');
  showDialog('GEO / 数据状态演示', `<div class="geo-depth"><small>独立合成场景 · 不替换看板数据，不代表客户实测</small><h2>有数据、没数据，一眼分清</h2><div class="geo-engine-switch" aria-label="切换数据状态">${Object.entries(scenarios).map(([id, item]) => `<button data-geo-evidence-state="${id}" aria-pressed="${id === key}">${item.label}</button>`).join('')}</div><div class="seo-stages"><div><b>${model.valueText}${model.value === null ? '' : esc(model.unitLabel || '')}</b><span>品牌提及率 · 合成示例</span></div><div><b>${model.trend.state === 'incomparable' ? '不可比' : '未提供'}</b><span>与前一周比较</span></div></div><p>${key === 'zero' ? '0 是已有有效数据得出的结果；它与尚无足够样本不同。' : key === 'incomparable' ? '两周的比较条件发生变化，保留本周数值，但不展示增长或下降。' : '有效样本不足，正式指标保留为空；不补成 0，也不从模拟回答计算。'}</p><h3>每条回答都带来源</h3><div class="geo-engine-switch">${['real', 'simulated', 'manual', 'unknown'].map(kind => `<span>${answerSourceDisplay({ source: { kind } }).label}</span>`).join(' · ')}</div><p>来源标签与是否计入正式指标分别判断。真实回答也需满足服务端的检查条件。</p><h3>任务很久没更新怎么办？</h3><p><strong>${progress.label}</strong> · ${progress.hint}</p><p>等待时间长不等于执行失败，状态由后台确认。</p><div class="seo-actions"><button data-geo-evidence-discuss="${key}">这个状态意味着什么？</button><button data-geo-evidence-next="${key}">接下来怎么做？</button><button data-geo-evidence-close>回到看板</button></div></div>`);
}

function discuss(key, next = false) {
  if (!Object.hasOwn(scenarios, key)) return;
  const scenario = scenarios[key];
  const explanations = {
    insufficient: '目前示例中的有效回答不足，所以暂不显示正式数值。这不能说明品牌没有被提及，更不能据此判断推广没有效果。',
    zero: '这个示例已经有符合条件的数据，统计结果为 0。它与没有数据不同；但单个指标为 0 也不能直接证明没有客户咨询。',
    incomparable: '本周示例数值为 25%，但两周的问题或引擎组合发生变化，所以不显示增长率。可以查看本周结果，暂不判断效果上升或下降。',
  };
  const steps = {
    insufficient: ['查看哪些回答未计入，以及对应原因。', '确认问题和引擎范围，安排获取合格的真实回答。', '等完整统计周结束，再查看正式指标。'],
    zero: ['点开符合条件的回答，核对品牌提及与引用原文。', '查看问题是否覆盖客户关心的内容，再核对相关官网页面。', '将可能原因作为待验证假设，改进后按相同条件再次检查。'],
    incomparable: ['对照两周的问题、引擎、供应商、模型和采样次数。', '明确哪些条件改变，不把差异解释为效果变化。', '固定条件收集下一完整周数据，再判断是否可以比较。'],
  };
  closeDialog();
  showChat();
  addMessage('user', `GEO 状态演示 · ${scenario.label}：${next ? '接下来怎么做？' : '这个状态意味着什么？'}`);
  addMessage('assistant', `<p><strong>独立合成场景 · ${scenario.label}</strong></p><p>以下只解释当前选中的演示状态，不是客户实测结论，也不改变看板范围。</p><p>${explanations[key]}</p>${next ? `<h3>建议按这三步核对</h3><ol>${steps[key].map(step => `<li>${step}</li>`).join('')}</ol><p>这里没有执行采集、生成或发布。</p>` : ''}<button class="seo-entry" data-geo-evidence-state="${key}">返回「${scenario.label}」演示 ↗</button>${next ? `<button class="seo-entry" data-geo-evidence-plan="${key}">拟定跟进方案</button>` : `<button class="seo-entry" data-geo-evidence-next="${key}">接下来怎么做？</button>`}`);
}

function plan(key) {
  if (!Object.hasOwn(scenarios, key)) return;
  const defaults = {
    insufficient: ['核对正式指标缺少哪些回答', '查看未计入回答的原因，确认问题和引擎范围；真实采集需另行安排。', '记录缺少的条件及后续安排；样本不足时保持未提供，不以零值代替。'],
    zero: ['核对零值对应的回答与页面', '查看合格回答中的品牌提及与官网引用，核对相关页面；可能原因作为假设分别记录。', '保留原文核对结果和待验证假设；不把零提及等同于没有咨询。'],
    incomparable: ['核对两周的比较条件', '逐项对照问题、引擎、供应商、模型和采样次数，列出发生变化的条件。', '保留条件对照与差异说明；不满足可比条件时不显示增长率。'],
  };
  const [title, note, criterion] = defaults[key];
  pPlan('geo', 'GEO-DEMO-' + key);
  const form = document.getElementById('pPlanForm');
  form.dataset.scenarioKind = 'synthetic';
  form.elements.namedItem('title').value = '演示 · ' + title;
  form.elements.namedItem('owner').value = 'GEO 运营负责人';
  form.elements.namedItem('note').value = '独立合成状态：' + scenarios[key].label + '。不是当前客户实测发现。' + note;
  form.elements.namedItem('criterion').value = criterion;
  form.insertAdjacentHTML('afterbegin', '<p><strong>这是独立数据状态的跟进演练。</strong>保存后为本地草稿，不会发给开发者或执行采集。请确认负责人和日期。</p>');
}

const originalBody = pCardBody;
pCardBody = function(key, scope) {
  return originalBody(key, scope) + (key === 'citations' ? '<button class="seo-entry" data-geo-evidence-state="insufficient">查看样本不足、零值与不可比的区别 ↗</button>' : '');
};
window.addEventListener('click', event => {
  const button = event.target.closest('[data-geo-evidence-state], [data-geo-evidence-close], [data-geo-evidence-discuss], [data-geo-evidence-next], [data-geo-evidence-plan]');
  if (!button) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (button.hasAttribute('data-geo-evidence-close')) closeDialog();
  else if (button.hasAttribute('data-geo-evidence-discuss')) discuss(button.dataset.geoEvidenceDiscuss);
  else if (button.hasAttribute('data-geo-evidence-plan')) plan(button.dataset.geoEvidencePlan);
  else if (button.hasAttribute('data-geo-evidence-next')) discuss(button.dataset.geoEvidenceNext, true);
  else preview(button.dataset.geoEvidenceState);
}, true);
renderPanorama();
