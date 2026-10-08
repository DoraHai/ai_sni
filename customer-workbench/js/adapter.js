/* Development adapter only. No network, credentials, production mutations or persistence. */
(() => {
  const all = ['SEM', 'SEO', 'GEO'];
  const requested = (new URLSearchParams(location.search).get('modules') || 'SEO').split(',');
  const modules = all.filter(m => requested.includes(m));
  const tasks = modules.map((module, i) => ({
    id: `local-${module}`, module, version: 1, state: '客户确认', owner: '负责顾问（开发占位）',
    title: {SEM: '单关键词出价方案 · 演练', SEO: '产品选型文章 · 单篇交付', GEO: '品牌问答事实补充'}[module],
    body: {SEM: '演练方案：目标关键词出价由 2.00 元调整为 2.10 元。未授权真实执行。', SEO: '选型文章草稿：先说明适用工况，再列经顾问核对的参数与来源。', GEO: '问答草稿：品牌与适用工况的关系需逐项引用官方事实。'}[module],
    evidence: '开发样例资料包 v1；无真实客户数据。', snapshot: `local-snapshot-${module}-1`,
    scope: `演示租户 / ${module} / 开发对象 ${i + 1}`, confirmation: null,
    history: [{version: 1, event: '开发样例：顾问复核通过，等待客户确认'}],
    revisions: [], comments: [], advisorRequested: false,
  }));
  tasks.forEach(t => t.revisions.push({version: 1, body: t.body, snapshot: t.snapshot}));
  function task(id) { const t = tasks.find(t => t.id === id); if (!t) throw Error('任务不存在'); return t; }
  function current(id, version) { const t = task(id); if (t.version !== version) throw Error('版本已变化，请重新打开当前稿件'); return t; }
  function record(t, event) { t.history.push({version: t.version, event,actor:role,at:new Date().toISOString()}); }
  let role = 'customer';
  const policy = {afterEdit: 'advisor_review'};
  const identities = {customer: {id:'local-customer-1',name:'陈经理（模拟客户）'},advisor: {id:'local-advisor-1',name:'李顾问（模拟顾问）'}};
  const settings = {version:1, materials:'开发样例资料，待顾问维护', direction:'开发样例：围绕产品选型与真实业务事实', keywords:'产品选型\n适用工况', history:[]};
  const confirmationHistory = [];
  const progressStates = ['程序处理中','顾问待处理','客户待确认稿件','人工发布待回填','失败待处理','已完成'];
  const progress = [
    ['网站检查','程序处理中','程序','等待检查结果','诊断接口尚未接通'],
    ['关键词与搜索','失败待处理','负责顾问','确认数据源后再决定恢复','开发样例：排名数据缺报，真实原因未知'],
    ['内容','客户待确认稿件','客户或代确认顾问','核对准确稿件版本',''],
    ['发布核验','人工发布待回填','发布负责人','回填准确版本、地址、发布时间后接续核验','没有实际发布地址或时间'],
    ['数据报告','顾问待处理','负责顾问','说明数据缺项与口径，客户直接查阅','统计来源未接入，不补0'],
    ['异常进度','已完成','程序','开发样例异常处理已结束；非真实业务完成',''],
  ].map((row,i)=>({id:`local-progress-${i+1}`,area:row[0],state:row[1],waitingFor:row[2],nextAction:row[3],reason:row[4],
    mode:'development',object:{module:'SEO',type:row[0]==='内容'?'content':'service',id:row[0]==='内容'?'local-SEO':`local-service-${i+1}`},
    version:1,updatedAt:null,deadline:null,evidence:[{id:`local-evidence-${i+1}`,kind:'development_fixture',description:row[1]==='已完成'?'本地模拟完成记录，不能证明生产完成':'本地状态样例，真实结果依据待接入',observedAt:null}],
    history:[{actor:'system',event:'本地模拟：创建本环节进度样例',at:null},{actor:'system',event:`本地模拟：${row[1]}`,at:null}],
  }));
  const messages = [{actor: 'system', visibility: 'customer', text: '开发样例：同一客户空间、同一稿件与进度。没有真人或 AI 服务消息。', taskId: null}];
  function writable(id, version) {
    const t = current(id, version);
    if (t.module !== 'SEO') throw Error('本轮仅体验 SEO 单篇流程，其他模块保留只读适配结构');
    return t;
  }
  function requireRole(expected) { if (role !== expected) throw Error('开发模拟身份不允许此操作；真实权限由后端判断'); }
  function afterChange(t) {
    invalidate(t,'稿件修改产生新版本');
    t.state = policy.afterEdit === 'advisor_review' ? '顾问复核' : '系统检查';
  }
  function invalidate(t,reason) {
    confirmationHistory.filter(c=>c.taskId===t.id && c.valid).forEach(c=>{c.valid=false;c.invalidReason=reason;});
    t.confirmation=null;
  }
  window.DEV_ADAPTER = {
    mode: 'development', modules, tasks, policy, messages, settings, confirmationHistory, progressStates,
    progressFor(area = null) {
      if (!modules.includes('SEO')) return [];
      return progress.filter(p=>!area || p.area===area).map(p=>{
        if(p.area!=='内容') return p;
        const t=task('local-SEO');
        return {...p,version:t.version,state:t.state==='客户确认'?'客户待确认稿件':t.state==='顾问复核'||t.state==='待修改'?'顾问待处理':'程序处理中',
          waitingFor:t.state==='客户确认'?'客户或代确认顾问':t.state==='顾问复核'||t.state==='待修改'?'负责顾问':'程序',
          nextAction:t.confirmation?'确认已记录（本地），等待系统发布交接；尚未发布':`等待${t.state}，准确版本v${t.version}`,
          history:[...p.history,...t.history.map(h=>({actor:h.actor||'system',event:`v${h.version} ${h.event}`,at:h.at||null}))]};
      });
    },
    get role() { return role; },
    setRole(next) { if (!['customer','advisor'].includes(next)) throw Error('未知模拟身份'); role = next; },
    setPolicy(next) { if (!['advisor_review','system_check'].includes(next)) throw Error('未知规则样例'); policy.afterEdit = next; },
    actions(t) {
      if (t.module !== 'SEO') return [];
      return ['edit','comment',...(role === 'customer' ? ['requestAdvisor',...(t.state === '客户确认' ? ['confirm','return'] : [])] : ['intervene',...(t.state === '客户确认' ? ['confirmOnBehalf'] : []),...(t.state === '顾问复核' ? ['review','reject'] : [])])];
    },
    saveSettings(patch, version) {
      requireRole('advisor');
      if (version !== settings.version) throw Error('服务设置版本已变化，请重新读取');
      for (const key of ['materials','direction','keywords']) if (typeof patch[key] !== 'string' || !patch[key].trim()) throw Error('请完整填写资料、方向与关键词');
      Object.assign(settings,{materials:patch.materials.trim(),direction:patch.direction.trim(),keywords:patch.keywords.trim(),version:settings.version+1});
      settings.history.push({version:settings.version,actor:{...identities.advisor},at:new Date().toISOString()});
      // No customer configuration approval task is created.
    },
    visibleMessages() { return messages.filter(m => role === 'advisor' || m.visibility === 'customer'); },
    comment(id, version, text, visibility = 'customer') {
      const t = writable(id, version);
      if (!text.trim()) throw Error('请填写意见');
      if (!['customer','internal'].includes(visibility)) throw Error('未知可见范围');
      if (visibility === 'internal') requireRole('advisor');
      t.comments.push({version, actor: role, visibility, text: text.trim()});
    },
    sendMessage(text, visibility = 'customer', target = 'advisor', taskId = null) {
      if (!text.trim()) throw Error('请填写消息');
      if (!['customer','internal'].includes(visibility) || !['advisor','ai','customer'].includes(target)) throw Error('未知消息范围或接收方');
      if (visibility === 'internal') requireRole('advisor');
      if (taskId) task(taskId);
      messages.push({actor: role, visibility, target, taskId, text: text.trim()});
    },
    requestAdvisor(id, version) {
      requireRole('customer'); const t = writable(id,version); t.advisorRequested = true;
      if (!messages.some(m => m.request && m.taskId === id && m.version === version)) {
        messages.push({actor:'customer',visibility:'customer',target:'advisor',taskId:id,version,request:true,text:`本地请求顾问协助核对 v${version}；没有通知真人。`});
      }
    },
    intervene(id, version) {
      requireRole('advisor'); const t = writable(id,version); t.state = '顾问复核'; t.advisorRequested = false; invalidate(t,'顾问重新介入复核');
      record(t,'开发模拟：顾问介入，旧确认失效；等待复核后重新确认');
    },
    confirm(id, version, onBehalf = false) {
      requireRole(onBehalf ? 'advisor' : 'customer'); const t = writable(id, version);
      if (t.state !== '客户确认') throw Error('当前版本尚未通过顾问复核，不能确认');
      t.confirmation = {version, snapshot: t.snapshot, scope: t.scope,actor:{...identities[role]},actorRole:role,onBehalf,at:new Date().toISOString()};
      confirmationHistory.push({taskId:id,...t.confirmation,valid:true});
      t.state = t.module === 'SEM' ? '待我方演练' : '待我方发布';
      record(t, `${identities[role].name}${onBehalf ? '代确认' : '本人确认'} v${version}；本地未写入服务器，未发布或执行`);
    },
    edit(id, version, body) {
      const t = writable(id, version);
      if (!body.trim()) throw Error('稿件或方案不能为空');
      if (body.trim() === t.body.trim()) throw Error('内容未变化，无需创建新版本');
      t.body = body.trim(); t.version++; afterChange(t);
      t.revisions.push({version: t.version, body: t.body, snapshot: t.snapshot});
      record(t, `${role === 'customer' ? '客户' : '顾问'}轻改产生新版本；旧确认失效，等待${t.state}后重新确认（规则样例可替换）`);
    },
    returnTask(id, version, reason) {
      requireRole('customer'); const t = writable(id, version); if (!reason.trim()) throw Error('请填写退回依据');
      if (t.state !== '客户确认') throw Error('当前任务不在客户确认节点');
      invalidate(t,'客户退回'); t.state = '顾问复核'; record(t, `客户退回：${reason.trim()}`);
    },
    simulateReview(id, version, decision = 'approve', reason = '') {
      requireRole('advisor'); const t = writable(id, version); if (t.state !== '顾问复核') throw Error('当前不等待顾问');
      if (!['approve','reject'].includes(decision)) throw Error('未知复核动作');
      if (decision === 'reject' && !reason.trim()) throw Error('请填写复核退回依据');
      t.state = decision === 'approve' ? '客户确认' : '待修改';
      record(t, decision === 'approve' ? '开发模拟：顾问复核通过，等待客户确认准确版本' : `开发模拟：顾问复核退回，需修改：${reason.trim()}`);
    },
    simulateSystemCheck(id, version) {
      const t = writable(id,version); if (t.state !== '系统检查') throw Error('当前不等待系统检查');
      t.state = '客户确认'; record(t,'开发工具模拟系统检查通过；不代表自动化已经接通，等待客户确认');
    },
  };
})();
