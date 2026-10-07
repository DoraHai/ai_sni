(() => {
  const adapter = window.DEV_ADAPTER, $ = s => document.querySelector(s);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const button = (text, act, extra = '') => `<button data-action="${act}" ${extra}>${text}</button>`;
  let page = '首页', dataModule = adapter.modules[0], level = 'L1', selectedId = null, openedVersion = null;
  const combinations = ['SEM','SEO','GEO','SEM,SEO','SEM,GEO','SEO,GEO','SEM,SEO,GEO'];
  $('#app').innerHTML = `<div class="dev-banner">本地开发演示 · 所有确认、轻改、退回与进度均为模拟；刷新即重置。未连接生产、未发布、未投放。</div><header><b>G-SNIPERS</b><span>客户工作台 · 演示租户</span><small>开通模块：${esc(adapter.modules.join(' / ') || '无')}</small></header><div class="workspace tier-${adapter.modules.length}"><main class="main"><div class="navigation">${['首页','进度','数据','交付记录'].map(x => button(x,'page',`data-page="${x}"`)).join('')}</div><div id="content"></div><details><summary>开发体验：模块组合</summary><div class="combos">${combinations.map(c => `<a href="?modules=${encodeURIComponent(c)}">${esc(c.replaceAll(',', ' + '))}</a>`).join('')}</div></details></main><aside class="chat"><div class="chat-head"><b>工作助理</b><small>开发占位 · 对话服务未接通</small></div><div id="messages" class="messages"><div class="bubble">可直接从首页处理待办，从固定入口查看进度、数据和交付记录。当前不生成真实建议或事实。</div></div><div class="composer"><label for="input">追问当前工作</label><div class="compose-row"><textarea id="input" placeholder="输入问题…"></textarea>${button('发送','chat')}</div><small>此处只演示输入反馈，不提交服务器。</small></div></aside></div><div id="layer"></div>`;
  const roleName = () => adapter.role === 'customer' ? '客户' : '顾问';
  const waiting = t => t.state === '客户确认' ? '客户确认准确版本' : t.state === '顾问复核' ? '顾问处理' : t.state === '系统检查' ? '系统检查（开发未接通）' : t.state === '待修改' ? '修改稿件' : '系统接续与发布交接（开发未接通）';
  const actorName = actor => ({customer:'客户 · 模拟身份',advisor:'顾问 · 模拟身份',system:'系统 · 开发样例',ai:'AI · 开发占位'}[actor] || actor);
  const seoAreas = [
    ['网站检查','SEO-A02','网站诊断、TDK与页面建议、实施交接和复检'],
    ['关键词与搜索','SEO-A03','关键词排名、趋势、搜索观察与数据时效'],
    ['内容','SEO-A04','选题、稿件、意见、轻改、复核及确认'],
    ['发布核验','SEO-A05','渠道交接、发布地址与时间、页面证据、失败核对'],
    ['数据报告','SEO-A06','统计来源、发布清单、周期报告与缺数说明'],
    ['异常进度','SEO-A07','等待谁、提醒、暂停、失败与未知结果待核对'],
  ];
  let seoArea = '网站检查', settingsVersion = null;
  const confirmationText = c => `${c.onBehalf ? '顾问' : '客户'} ${c.actor.name}${c.onBehalf ? '代确认' : '本人确认'} · v${c.version}`;
  function progressCards(area = null) {
    return adapter.progressFor(area).map(p=>`<article class="timeline"><b>${esc(p.area)}</b><p>${esc(p.state)} · 等待${esc(p.waitingFor)} · v${p.version}</p><small>本地模拟 · 更新/期限：未知</small><p>${esc(p.nextAction)}</p>${p.reason ? `<p>阻塞/异常：${esc(p.reason)}</p>` : ''}${button('进度明细 / 历史 / 依据','progress-detail',`data-progress-id="${p.id}"`)}</article>`).join('');
  }
  function progressDrawer(id) {
    const p = adapter.progressFor().find(p=>p.id===id); if(!p) return;
    selectedId=null;openedVersion=null;
    $('#layer').innerHTML=`<div class="overlay" data-action="close"></div><aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="progress-title">${button('关闭','close','class="close"')}<small>统一进度 · 本地模拟 · 未返回服务器状态</small><h2 id="progress-title">${esc(p.area)}</h2><p>${esc(p.state)} · 等待${esc(p.waitingFor)}</p><p>业务对象：${esc(p.object.module)} / ${esc(p.object.type)} / ${esc(p.object.id)} · v${p.version}</p><p>更新：未知 · 期限：未知</p><h3>下一步与异常</h3><p>${esc(p.nextAction)}</p><p>${esc(p.reason || '本地样例无额外异常；真实异常状态未知')}</p><h3>处理历史</h3>${p.history.map(h=>`<div class="record"><small>${esc(actorName(h.actor))} · ${esc(h.at || '时间未知')} · 本地模拟</small><p>${esc(h.event)}</p></div>`).join('')}<h3>结果依据</h3>${p.evidence.map(e=>`<div class="record"><b>${esc(e.id)}</b><p>${esc(e.description)}</p><small>开发夹具 · 观察时间未知 · 不是生产结果</small></div>`).join('')}<div class="actions">${button('固定 SEO 数据依据 L3','progress-evidence')}${button('交付记录','progress-deliveries')}${p.area==='内容'?button('查看对应稿件版本','progress-content'):''}</div><p><small>失败或外部结果未知时不盲重试。发布回填与页面核验分别记录，代确认不代表发布。客户只确认稿件。</small></p></aside>`;
    $('.drawer .close').focus();
  }
  function controls() {
    $('.navigation').innerHTML = ['首页',...(adapter.modules.includes('SEO') ? ['SEO工作'] : []),'进度','数据','交付记录',...(adapter.modules.includes('SEO') && adapter.role === 'advisor' ? ['服务设置'] : [])].map(x=>button(x,'page',`data-page="${x}"`)).join('');
    const header = $('header');
    let node = $('#role-controls');
    if (!node) { node = document.createElement('div'); node.id = 'role-controls'; header.append(node); }
    node.innerHTML = `<span>开发身份切换（不代表鉴权）：</span>${button('客户','role','data-role="customer" class="'+(adapter.role === 'customer' ? 'selected' : '')+'"')}${button('顾问','role','data-role="advisor" class="'+(adapter.role === 'advisor' ? 'selected' : '')+'"')}<span>同一演示客户空间</span>`;
    node.insertAdjacentHTML('beforeend','<small id="api-connection">SEO 接口：未连接宿主身份 · 当前页面为本地模拟</small>');
    let policy = $('#policy-controls');
    if (!policy) { policy = document.createElement('details'); policy.id = 'policy-controls'; $('.main').append(policy); }
    policy.innerHTML = `<summary>开发规则样例 · SEO 人工介入待定</summary><p>切换只影响下一次轻改，不改变现有节点。不是正式业务规则。</p><label for="edit-policy">轻改后继续方式</label><select id="edit-policy"><option value="advisor_review" ${adapter.policy.afterEdit === 'advisor_review' ? 'selected' : ''}>等待顾问复核（样例）</option><option value="system_check" ${adapter.policy.afterEdit === 'system_check' ? 'selected' : ''}>等待系统检查（样例）</option></select><p>正常流程由系统推进，顾问按需介入；具体自动推进接口未接通。客户确认始终绑定准确版本，确认不等于发布。</p>`;
  }
  function renderMessages() {
    $('.chat-head').innerHTML = '<b>本客户空间 · 对话</b><small>客户 / 顾问 / AI 明确区分 · 全部本地模拟</small>';
    $('#messages').innerHTML = adapter.visibleMessages().map(m => `<div class="bubble ${m.visibility === 'internal' ? 'internal-note' : ''}"><small>${esc(actorName(m.actor))} · ${m.visibility === 'internal' ? '内部备注 · 客户不可见' : '客户可见'}${m.target ? ' · 交给'+esc(m.target === 'ai' ? 'AI' : m.target === 'advisor' ? '顾问' : '客户') : ''}${m.taskId ? ' · '+esc(m.taskId) : ''}</small>${esc(m.text)}<small>本地记录，未发送服务器或通知真人${m.target === 'ai' ? '，AI 服务未接通' : ''}</small></div>`).join('');
    $('.composer').innerHTML = `<label for="input">${roleName()}输入 · 本地模拟</label><div class="message-routing"><label for="message-target">接收方</label><select id="message-target">${adapter.role === 'customer' ? '<option value="advisor">顾问</option><option value="ai">AI</option>' : '<option value="customer">客户</option><option value="ai">AI</option>'}</select>${adapter.role === 'advisor' ? '<label for="message-visibility">可见范围</label><select id="message-visibility"><option value="customer">客户可见消息</option><option value="internal">内部备注</option></select>' : ''}</div><div class="compose-row"><textarea id="input" placeholder="输入意见或问题…"></textarea>${button('本地记录','chat')}</div><small>未连接消息服务；不代表真人收到或 AI 已回复。</small>`;
  }
  function taskList() {
    return adapter.tasks.map(t => `<div class="task-item"><div class="task-content"><div class="task-title">${esc(t.module)} · ${esc(t.title)}</div><div class="task-meta">v${t.version} · ${esc(t.state)} · 等待${esc(waiting(t))}${t.advisorRequested ? ' · 客户请求顾问协助（本地）' : ''}</div></div>${button(t.module === 'SEO' ? '查看并处理' : '只读查看','task',`data-id="${t.id}"`)}</div>`).join('') || '<p class="empty">没有开通模块；不显示其他模块内容。</p>';
  }
  function render() {
    if (page === '服务设置' && adapter.role !== 'advisor') page = '首页';
    controls(); renderMessages();
    document.querySelectorAll('[data-page]').forEach(b => b.classList.toggle('active',b.dataset.page === page));
    if (page === '首页') $('#content').innerHTML = `<section id="summary"><h2>${roleName()}首页 · 本客户空间</h2><p>结果：尚无真实交付结果，当前为 SEO 单篇交付的本地体验。</p>${adapter.role === 'customer' ? `<p>待我确认：${adapter.tasks.filter(t => t.module === 'SEO' && t.state === '客户确认').length} 项。查看稿件、依据与准确版本，也可请求顾问协助。</p>` : `<p>需我介入：${adapter.tasks.filter(t => t.module === 'SEO' && (t.state === '顾问复核' || t.advisorRequested)).length} 项。优先处理请求、例外和待复核稿件。</p><p>此处只显示获授权的单客户空间，不汇总其他客户。</p>`}<p>正常工作由系统接续；当前自动流程接口未连接，等待信息可在进度中查看。</p><small>下一次交付时间、数据期间与更新时间待接口提供</small></section><section class="home-modules">${adapter.modules.map(m => `<article class="module-card"><h3>${m}</h3><strong>待接入</strong><p>没有真实指标，不能按 0 解读。</p>${button('查看数据','module-data',`data-module="${m}"`)}</article>`).join('')}</section><section class="tasks"><h2>${adapter.role === 'customer' ? '我的稿件与待办' : '本客户稿件与介入事项'}</h2>${taskList()}</section>`;
    if (page === '进度') $('#content').innerHTML = `<section class="page-card"><h2>共享进度 · 本地模拟</h2><p>SEO六个环节使用相同状态口径：${adapter.progressStates.map(esc).join(' / ')}。</p>${progressCards() || '<p>未开通SEO，无SEO进度样例。</p>'}<p>“已完成”仅为开发样例；没有服务端回执就不能报告真实完成。没有配置审批或报告签收待办。</p></section>`;
    if (page === '数据') $('#content').innerHTML = `<section class="page-card"><h2>数据</h2><div class="data-links">${adapter.modules.map(m => button(m,'module-data',`data-module="${m}" class="${m === dataModule ? 'active' : ''}"`)).join('')}</div><div class="data-links">${['L1','L2','L3'].map(l => button(`${l} · ${{L1:'概览',L2:'明细',L3:'依据'}[l]}`,'level',`data-level="${l}" class="${l === level ? 'active' : ''}"`)).join('')}</div><h3>${esc(dataModule || '未开通')} / ${level}</h3><p>待接入真实${{L1:'结果概览',L2:'对象明细',L3:'原始依据与观察记录'}[level]}。</p><p>数据期间：未知 · 来源：尚未连接 · 更新时间：未知</p><p>缺失原因：当前为本地开发适配层。没有数据不等于真实零值。</p><small>发布、页面可访问、收录、排名与效果各自展示；确认记录不能充当发布依据。</small></section>`;
    if (page === '交付记录') $('#content').innerHTML = `<section class="page-card"><h2>交付记录</h2><p>暂无真实发布、核验或报告交付记录；生产历史接口待接入。报告直接查阅，不要求客户额外签收。</p><h3>本地确认演示记录</h3>${adapter.confirmationHistory.map(c => `<div class="record"><b>${esc(confirmationText(c))}</b><p>实际 actor：${esc(c.actor.id)} · 时间：${esc(c.at)}</p><p>${c.valid ? '当前有效的本地确认' : '已失效：'+esc(c.invalidReason)} · ${esc(c.scope)} · ${esc(c.snapshot)}</p><small>仅本地模拟，尚未发布；顾问代确认不需客户再次批准。</small></div>`).join('') || '<p class="empty">暂无本地确认。</p>'}</section>`;
    if (page === 'SEO工作') renderSeoWork();
    if (page === '服务设置') renderSettings();
  }
  function renderSeoWork() {
    const area = seoAreas.find(x=>x[0]===seoArea);
    $('#content').innerHTML = `<section class="page-card"><h2>SEO 工作 · 全流程入口</h2><div class="seo-areas">${seoAreas.map(a=>button(a[0],'seo-area',`data-area="${a[0]}" class="${a[0]===seoArea ? 'selected' : ''}"`)).join('')}</div><h3>${esc(area[0])}</h3><p>${esc(area[2])}</p><p>接口状态：未接通 · 数据期间与更新：未知 · 不把空数据当0。</p>${progressCards(seoArea)}${seoArea === '内容' ? taskList() : `<p>当前没有真实${esc(seoArea)}结果，已有模块能力待按契约适配。</p>`}<div class="actions">${seoArea === '数据报告' || seoArea === '关键词与搜索' || seoArea === '网站检查' ? button('固定数据入口 L1/L2/L3','module-data','data-module="SEO"') : ''}${seoArea === '发布核验' || seoArea === '数据报告' ? button('查看交付记录','page','data-page="交付记录"') : ''}${seoArea === '异常进度' ? button('查看共享进度','page','data-page="进度"') : ''}${adapter.role === 'advisor' ? button('资料 / 方向 / 关键词设置','page','data-page="服务设置"') : ''}</div><p><small>稿件确认、发布回填、页面核验、收录和效果分别记录。未知发布结果应待核对，不自动重试。</small></p></section>`;
  }
  function renderSettings() {
    settingsVersion = adapter.settings.version;
    $('#content').innerHTML = `<section class="page-card"><h2>顾问服务设置 · 本客户</h2><p>资料、优化方向和目标关键词由顾问维护，不生成客户配置审批待办。</p><small>本地模拟 v${settingsVersion} · 未写入服务器</small><form id="settings-form"><label for="materials">基础资料</label><textarea id="materials">${esc(adapter.settings.materials)}</textarea><label for="direction">优化方向</label><textarea id="direction">${esc(adapter.settings.direction)}</textarea><label for="keywords">目标关键词（每行一个）</label><textarea id="keywords">${esc(adapter.settings.keywords)}</textarea>${button('保存顾问设置（模拟）','settings-save','type="button"')}<p id="settings-result" role="status"></p></form><small>现有品牌资料和关键词API为复用候选；服务计划整体契约与顾问资格尚未接入。这里不配置真实账号或凭据。</small></section>`;
  }
  function drawer(id) {
    const t = adapter.tasks.find(t => t.id === id); if (!t) return;
    selectedId = id; openedVersion = t.version;
    const actions = adapter.actions(t), can = action => actions.includes(action);
    $('#layer').innerHTML = `<div class="overlay" data-action="close"></div><aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="task-title">${button('关闭','close','class="close"')}<small>本地模拟 · ${esc(t.module)} · ${roleName()}视图</small><h2 id="task-title">${esc(t.title)}</h2><p>准确版本 <b>v${t.version}</b> · ${esc(t.state)}</p><p>对象：${esc(t.scope)}<br>依据快照：${esc(t.snapshot)}</p><pre>${esc(t.body)}</pre><h3>依据与下一步</h3><p>${esc(t.evidence)}</p><p>等待${esc(waiting(t))}。确认只绑定当前版本，不代表发布；正常接续方式以服务端规则为准。</p><div class="actions">${can('confirm') ? button(`模拟确认 v${t.version}`,'confirm','class="primary"') : ''}${can('requestAdvisor') ? button(t.advisorRequested ? '已在本地请求顾问' : '请求顾问（模拟）','request-advisor') : ''}${can('intervene') && t.state !== '顾问复核' ? button('按需介入复核（模拟）','intervene') : ''}</div>${can('edit') ? `<label for="edit-body">轻改稿件</label><textarea id="edit-body">${esc(t.body)}</textarea>${button('保存轻改为新版本（模拟）','edit')}<p><small>保存后旧确认失效，进入${adapter.policy.afterEdit === 'advisor_review' ? '顾问复核' : '系统检查'}（可替换规则样例）；完成后需重新确认。</small></p>` : '<p>SEM/GEO 本轮只读，不扩展写入。</p>'}${can('return') || can('review') ? `<label for="reason">${can('review') ? '复核意见' : '退回意见'}</label><textarea class="reason" id="reason" placeholder="说明需调整的内容与依据"></textarea><div class="actions">${can('return') ? button('模拟退回顾问','return') : ''}${can('review') ? button('模拟复核通过','review')+button('模拟复核退回修改','reject') : ''}</div>` : ''}<div class="error" role="alert"></div>${can('comment') ? `<h3>稿件意见 · 绑定 v${t.version}</h3><label for="comment-text">意见</label><textarea id="comment-text" class="reason"></textarea>${adapter.role === 'advisor' ? '<label for="comment-visibility">意见可见范围</label><select id="comment-visibility"><option value="customer">客户可见意见</option><option value="internal">内部备注</option></select>' : ''}${button('本地记录意见','comment')}` : ''}<div class="comments">${t.comments.filter(c => adapter.role === 'advisor' || c.visibility === 'customer').map(c => `<div class="record ${c.visibility === 'internal' ? 'internal-note' : ''}"><small>v${c.version} · ${esc(actorName(c.actor))} · ${c.visibility === 'internal' ? '内部备注 · 客户不可见' : '客户可见'} · 本地未发送</small><p>${esc(c.text)}</p></div>`).join('')}</div><h3>版本记录</h3>${t.revisions.map(r => `<details><summary>v${r.version}${r.version === t.version ? '（当前）' : '（历史）'}</summary><pre>${esc(r.body)}</pre></details>`).join('')}<h3>操作记录 · 模拟</h3>${t.history.map(h => `<p>v${h.version} · ${esc(h.event)}</p>`).join('')}${t.state === '系统检查' ? `<details class="development-tools"><summary>开发工具 · 非真实系统结果</summary><p>只用于体验后续确认，不执行生成或发布。</p>${button('模拟系统检查完成','system-check')}</details>` : ''}</aside>`;
    if (can('confirmOnBehalf')) $('.drawer .actions').insertAdjacentHTML('afterbegin',button(`顾问代确认 v${t.version}（模拟）`,'confirm-on-behalf','class="primary"')+'<p>记录顾问实际身份，不需客户再批准代确认。</p>');
    if (t.confirmation) $('.drawer .actions').insertAdjacentHTML('beforebegin',`<div class="confirmation-card"><b>${esc(confirmationText(t.confirmation))}</b><p>实际 actor：${esc(t.confirmation.actor.id)} · ${esc(t.confirmation.at)}</p><small>本地记录 · 确认不等于发布</small></div>`);
    $('#layer .close').focus();
  }
  function close() { $('#layer').innerHTML = ''; selectedId = null; openedVersion = null; }
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') close();
    if (e.key === 'Tab' && $('.drawer')) {
      const controls = [...$('.drawer').querySelectorAll('button,textarea,summary,select')].filter(el => el.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-action]'); if (!el) return;
    const action = el.dataset.action;
    try {
      if (action === 'page') { page = el.dataset.page; render(); }
      if (action === 'module-data') { dataModule = el.dataset.module; page = '数据'; level = 'L1'; render(); }
      if (action === 'level') { level = el.dataset.level; render(); }
      if (action === 'task') drawer(el.dataset.id);
      if (action === 'close') close();
      if (action === 'role') { close(); adapter.setRole(el.dataset.role); render(); }
      if (action === 'seo-area') { seoArea = el.dataset.area; render(); }
      if (action === 'progress-detail') progressDrawer(el.dataset.progressId);
      if (action === 'progress-evidence') {close();page='数据';dataModule='SEO';level='L3';render();}
      if (action === 'progress-deliveries') {close();page='交付记录';render();}
      if (action === 'progress-content') drawer('local-SEO');
      if (action === 'settings-save') {
        adapter.saveSettings({materials:$('#materials').value,direction:$('#direction').value,keywords:$('#keywords').value},settingsVersion);
        render(); $('#settings-result').textContent='已保存在本地模拟设置中；没有提交服务器，也没有新增客户审批。';
      }
      if (['confirm','confirm-on-behalf','edit','return','review','reject','intervene','request-advisor','comment','system-check'].includes(action)) {
        const id = selectedId, version = openedVersion;
        if (action === 'confirm') adapter.confirm(id,version);
        if (action === 'confirm-on-behalf') adapter.confirm(id,version,true);
        if (action === 'edit') adapter.edit(id,version,$('#edit-body').value);
        if (action === 'return') adapter.returnTask(id,version,$('#reason').value);
        if (action === 'review') adapter.simulateReview(id,version);
        if (action === 'reject') adapter.simulateReview(id,version,'reject',$('#reason').value);
        if (action === 'intervene') adapter.intervene(id,version);
        if (action === 'request-advisor') adapter.requestAdvisor(id,version);
        if (action === 'comment') adapter.comment(id,version,$('#comment-text').value,$('#comment-visibility')?.value || 'customer');
        if (action === 'system-check') adapter.simulateSystemCheck(id,version);
        render(); drawer(id);
      }
      if (action === 'chat') {
        const text = $('#input').value.trim(); if (!text) return;
        adapter.sendMessage(text,$('#message-visibility')?.value || 'customer',$('#message-target').value);
        renderMessages();
      }
    } catch (error) { const output = $('.error') || $('#settings-result'); if (output) output.textContent = error.message; }
  });
  document.addEventListener('change', e => {
    if (e.target.id === 'edit-policy') { adapter.setPolicy(e.target.value); render(); if (selectedId) drawer(selectedId); }
  });
  render();
})();
