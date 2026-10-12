const queueState=s=>({'queued':'排队','awaiting-review':'待审核','awaiting-adaptation':'待适配','awaiting-authorization':'待授权',paused:'已暂停',scheduled:'待定时', 'awaiting-intervention':'待介入',superseded:'旧版本失效'}[s]||s);
const queueReason=s=>({'NOT_INTEGRATED':'未接入','NOT_AUTHORIZED':'超管未授权自动排队','REAL_CHANNEL_NOT_ACCEPTED':'实页发布与结果确认未验收','BINDING_UNAVAILABLE':'账号绑定或设备不可用','SOURCE_CHANGED':'稿件版本已变化','SOURCE_REVIEW_REQUIRED':'当前审核或来源门禁未通过','REVIEW_REQUIRED':'等待原模块审核','READY':'来源已就绪','APPROVED_SOURCE':'已审核来源','PROJECT_PAUSED':'项目未运行','CHANNEL_DISABLED':'项目渠道已停用','SCANNED':'已复核','AUTHORIZATION_REVOKED':'当前顾问权限已撤销','SOURCE_UNAVAILABLE':'来源暂不可用','SCAN_UNAVAILABLE':'扫描未完成','OUTCOME_UNKNOWN':'结果未知，保留占用等待核查','ACCOUNT_BUSY':'同账号正在处理其他任务','REVIEW_NOT_SUBMITTED':'尚未提交原模块审核','REVIEW_PENDING':'等待原模块审核','REVIEW_REJECTED':'原模块审核已退回','REVIEW_INVALID':'原模块审核信息无效或已过期','MASTER_STALE':'母稿版本已变化','CONTENT_EMPTY':'渠道稿正文或标题缺失','SOURCE_INVALID':'稿件来源未通过校验','PUBLISH_GATE_BLOCKED':'原模块发布规则或事实门禁未通过','ASSET_MANIFEST_INVALID':'素材清单与冻结稿不一致','ADAPTATION_INVALID':'渠道适配信息无效','ADAPTATION_PENDING':'等待渠道适配','SOURCE_READY':'来源已就绪','CONFIRMATION_REQUIRED':'等待原模块客户或顾问代确认','CONNECTION_UNAVAILABLE':'来源连接停用或尚未就绪','SOURCE_STALE':'母稿或渠道稿版本不匹配','ASSETS_UNAVAILABLE':'素材未冻结或与稿件不符','CONTENT_INVALID':'稿件格式或长度未通过渠道校验','KEYWORDS_INVALID':'关键词归属或内容覆盖未通过门禁','POLICY_REQUIRED':'超管尚未配置账号规则','POLICY_DISABLED':'账号规则未启用','ACCOUNT_PAUSED':'账号已暂停','CAPTCHA':'待人工处理验证码','LOGIN_REQUIRED':'待人工恢复登录','RESULT_CONFLICT':'发布结果冲突，待核查','DAILY_LIMIT':'等待下一日额度','MIN_INTERVAL':'等待最小间隔','OUTSIDE_WINDOW':'等待允许时段'}[s.replace(/^(geo|seo)_distribution_/i,'').toUpperCase()]||'原模块门禁未通过，请进入对应内容审核页核对');
import {createDistributionClient,safeDistributionUrl,distributionScope} from './distribution-client.mjs';
import {escapeText as esc} from './customer-display.mjs';
const labels={queued:'待执行',leased:'已下发，等待本机回执',running:'执行中','awaiting-human':'待人工处理',
  succeeded:'已完成',failed:'失败',unknown:'结果待核查',canceled:'已取消'};
const actionLabels={preflight:'预检',handoff:'交接人工',publish:'人工发布授权'};
const errors={NOT_INTEGRATED:'分发接口或来源适配尚未接入',PERMISSION_DENIED:'权限已变化，分发信息已清除',
  NOT_AUTHENTICATED:'请先登录',CONTRACT_MISMATCH:'返回的数据未通过范围和版本核验',CONFLICT:'状态、稿件或已有任务发生变化，请重新读取核对',
  WRITE_OUTCOME_UNKNOWN:'操作结果待核查，请刷新项目与已有任务；不要重复提交',REQUEST_FAILED:'当前渠道或稿件尚未满足分发条件',
  READ_FAILED:'读取未完成，请稍后重试',CONTEXT_CHANGED:'会话已变化，分发信息已清除'};
const key=s=>`${s.module}:${s.tenant_id}:${s.scope_id}`;
const time=n=>n?new Date(n).toLocaleString('zh-CN',{hour12:false}):'暂无记录';
const reasonLabels={READY:'可进入发布交接',POLICY_REQUIRED:'等待超管配置发布规则',POLICY_DISABLED:'发布规则未启用',
  ACCOUNT_PAUSED:'账号已暂停',ACCOUNT_BUSY:'账号有正在处理的任务',OUTCOME_UNKNOWN:'账号有结果待核查的任务',
  CAPTCHA:'遇到验证码，等待人工处理',LOGIN_REQUIRED:'需要人工登录',RESULT_CONFLICT:'核查记录与迟到回执冲突',
  DAILY_LIMIT:'已达系统日上限',MIN_INTERVAL:'等待发布间隔',OUTSIDE_WINDOW:'当前不在发布时段'};
const clock=n=>n===1440?'24:00':String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0');
const checkLabels={ADVISOR_CONFIRMED_PUBLIC_CONTENT:'顾问已核验公开访问、目标账号及完整稿件',PUBLIC_TEXT_AND_ACCOUNT_MATCHED:'公开文本与账号信息初检相符，仍需顾问核验展示及配图',
  PAGE_UNAVAILABLE:'公开页面暂时无法核验',CHANNEL_REQUIRES_HUMAN:'该渠道需要顾问核验',PAGE_LAYOUT_UNVERIFIED:'页面结构无法可靠识别',
  CONTENT_MISMATCH:'公开内容与审核稿不一致',ACCOUNT_UNVERIFIED:'平台账号身份尚未核验',ASSETS_REQUIRE_HUMAN:'配图需要顾问逐项核验'};
const publicationUrl=t=>t.resolution?.outcome==='published'?t.resolution.public_url:t.receipt?.publicUrl;
export function distributionPublicationMarkup(task){
  const c=task.publication?.check,w=task.publication?.writeback,m=task.publication?.monitor;
  const monitorLabels={not_queued:'尚未安排检查',pending:'等待检查',running:'正在检查',captured:'已取得页面截图',
    observed:'已有公开文本匹配观察',failed:'检查失败',unreachable:'暂时无法读取公开页面',mismatch:'公开文本不匹配',
    version_changed:'稿件版本已变化，需核查',unavailable:'最新检查状态暂不可用'};
  return `${c?`<p>最近发布核验：${esc(checkLabels[c.code]||c.code)} · ${esc(time(c.checked_at))}${c.status==='needs-human'?' · 待人工处理':''}</p>`:''}
    ${w?`<p>原模块回写：${esc({written:'已写入发布记录',pending:'等待回写',blocked:'回写受阻，需处理'}[w.state])}</p>
      ${w.result?`<p>${esc(w.result.module.toUpperCase())} 发布记录 #${w.result.publication_id} · 首次登记：${esc({pending:'待原模块检查',not_queued:'尚未安排检查'}[w.result.monitor_state]||'检查状态未注明')}。最新执行进度请读取原模块状态。</p>`:''}`:''}
    ${m?`<p>最新${m.basis==='page-capture'?'页面截图检查':'公开文本检查'}：${esc(monitorLabels[m.state])}${m.evidence_source==='manual'?' · 人工上传证据':m.evidence_source==='auto'?' · 自动检查':' · 证据来源未注明'}</p>
      <p>实际观察：${esc(time(m.observed_at))}${m.next_check_at?' · 下次检查 '+esc(time(m.next_check_at)):''}${m.evidence_id?' · 检查记录 #'+m.evidence_id:''}</p>`:''}
    ${w?.result?'<p>页面截图与文本观察各自记录；收录和 AI 引用另行监测。</p>':''}`;
}
export function distributionMediaHref(value){const s=distributionScope(value);return s.module==='seo'?
  `/api/seo/distribution-media/workspace?tenant_id=${s.tenant_id}&site_id=${s.scope_id}`:
  `/geo/tasks?tenant_id=${s.tenant_id}&project_id=${s.scope_id}`;}
export function distributionScheduleMarkup(s){return !s?'<p>发布规则尚未读取，不能判断账号是否可执行。</p>':
  `<p>${esc(reasonLabels[s.reason])}${s.next_allowed_at&&!s.available?' · 下次可执行 '+esc(time(s.next_allowed_at)):''}</p>
  <p>系统今日占用或确认发布 ${s.system_used_today} / ${s.effective_daily_limit??'未配置'}，剩余 ${s.system_remaining??'未配置'}；平台剩余额度尚未核验。</p>
  ${s.policy?`<p>时区 ${esc(s.policy.timezone)} · 发布时段 ${esc(s.policy.windows.map(w=>clock(w.start)+'–'+clock(w.end)).join('、'))} · 最小间隔 ${s.effective_interval_seconds} 秒</p>`:''}`;}
export function distributionTaskMarkup(task){
  const r=task.receipt;
  const status=task.status==='succeeded'?(task.action==='preflight'?'预检完成':task.action==='handoff'?'素材交接完成，仍未发布':task.publication?.check?.status==='verified'?'发布已核验':'人工回填发布，页面待核验'):labels[task.status];
  const url=publicationUrl(task);
  return `<article class="distribution-task"><h4>${esc(actionLabels[task.action])} · ${esc(status)}</h4>
    <p>任务 ${esc(task.id)} · 渠道稿 #${task.variant_id} · ${esc(task.source_revision)}</p>
    <p>创建 ${esc(time(task.created_at))} · 授权到期 ${esc(time(task.grant_expires_at))}</p>
    <p>${task.platform==='wechat-article'?'公众号文章':'小红书图文'} · 账号 ${esc(task.account_id)}${task.revoked?' · 授权已失效':''}</p>
    ${r?`<p>最近回执 ${esc(time(r.at))} · ${esc(r.code)}${r.evidence==='human-reported'?' · 人工报告':''}</p>`:''}
    ${task.schedule?distributionScheduleMarkup(task.schedule):''}
    ${url&&safeDistributionUrl(task.platform,url)?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">查看人工回填链接</a>${task.publication?.check?.status==='verified'?'':'<p>链接尚未通过内容及公开访问核验。</p>'}`:''}
    ${distributionPublicationMarkup(task)}
    ${task.status==='unknown'?'<strong>先核查平台实际结果，不能自动重新发布。</strong>':''}</article>`;
}
export function createAdvisorDistributionPanel({session,fetchImpl=fetch,subscribeSession,browser=window,onChange=()=>{},scopesForAdvisor=()=>[]}){
  const client=createDistributionClient({session,fetchImpl,subscribeSession});
  let modules=[],filter='all',selected=null,snapshot=null,tasks=[],events=[],sources=[],schedules=[],bindingId=null,variantId=null,preview=null;
  let reviewed=false,manual=false,busy=false,epoch=0,disposed=false,notice='';
  let publicationPreview=null,channels=[],queueItems=[],queueScans=[],plans=null,platformDirectory=[],executionProgress=null;
  function clearPublication(){for(const url of publicationPreview?.image_urls||[])URL.revokeObjectURL(url);publicationPreview=null;}
  const scopes=()=>scopesForAdvisor().filter(s=>modules.includes(s.module)&&(filter==='all'||filter===s.module));
  const scope=()=>{const value=scopes().find(s=>key(s)===selected);return value?{module:value.module,tenant_id:value.tenant_id,scope_id:value.scope_id}:null;};
  function clear(){clearPublication();channels=[];queueItems=[];queueScans=[];plans=null;platformDirectory=[];executionProgress=null;snapshot=null;tasks=[];events=[];sources=[];schedules=[];bindingId=null;variantId=null;preview=null;reviewed=false;manual=false;}
  function invalidate(){epoch++;clear();busy=false;notice='';client.invalidate();}
  const unsubscribe=client.subscribe(()=>{epoch++;clear();busy=false;notice='会话或权限已变化，请重新核验。';onChange();});
  async function load(){
    const s=scope();if(!s||disposed)return;
    if(snapshot&&['module','tenant_id','scope_id'].some(k=>snapshot[k]!==s[k]))clear();
    clearPublication();channels=[];queueItems=[];queueScans=[];plans=null;platformDirectory=[];executionProgress=null;tasks=[];events=[];sources=[];schedules=[];
    const stamp=++epoch;busy=true;preview=null;reviewed=false;manual=false;notice='正在读取项目分发状态…';onChange();
    try{
      const value=await client.scope(s);if(disposed||epoch!==stamp)return;snapshot=value;
      if(!value.bindings.some(b=>b.id===bindingId))bindingId=value.bindings[0]?.id||null;
      const binding=value.bindings.find(b=>b.id===bindingId);
      const results=await Promise.allSettled([client.tasks(s),client.events(s),binding?client.sources(s,binding.platform):Promise.resolve({items:[]}),client.schedules(s),client.projectChannels(s),client.queue(s),client.plans(s),client.platformDirectory(s),client.executionProgress(s)]);
      if(disposed||epoch!==stamp)return;
      tasks=results[0].status==='fulfilled'?results[0].value.items:[];
      events=results[1].status==='fulfilled'?results[1].value.items:[];
      sources=results[2].status==='fulfilled'?results[2].value.items:[];
      schedules=results[3].status==='fulfilled'?results[3].value.items:[];
      channels=results[4].status==='fulfilled'?results[4].value.items:[];
      queueItems=results[5].status==='fulfilled'?results[5].value.items:[];queueScans=results[5].status==='fulfilled'?results[5].value.scans:[];
      plans=results[6].status==='fulfilled'?results[6].value:null;
      platformDirectory=results[7].status==='fulfilled'?results[7].value.items:[];
      executionProgress=results[8].status==='fulfilled'?results[8].value:null;
      variantId=sources.some(v=>v.variant_id===variantId)?variantId:sources[0]?.variant_id||null;
      const rejected=results.find(r=>r.status==='rejected');notice=rejected?errors[rejected.reason.code]||'部分信息未能读取，请核对':'已读取。发布由人工完成，自动上传和发文尚未接入。';
    }catch(error){if(epoch===stamp){clear();notice=errors[error.code]||'读取未完成，请稍后重试';}}
    finally{if(epoch===stamp){busy=false;onChange();}}
  }
  async function perform(operation){
    if(busy||!scope())return;const stamp=epoch;busy=true;notice='正在提交…';onChange();
    try{await operation();if(disposed||epoch!==stamp)return;busy=false;await load();}
    catch(error){if(epoch===stamp){busy=false;preview=null;reviewed=false;manual=false;notice=errors[error.code]||'操作未完成，请重新读取核对';onChange();}}
  }
  function html(){
    if(!modules.length)return '';
    const options=scopes(),s=scope(),p=snapshot?.project,binding=snapshot?.bindings.find(b=>b.id===bindingId),schedule=schedules.find(v=>v.binding_id===bindingId);
    const owned=!p||p.owner_user_id===null||p.owner_user_id===session.user?.id;
    return `<section class="advisor-group distribution-panel" data-distribution-panel><h2>发布与分发</h2>
      <p>选择已分配项目的审核稿，交给多号通预检或人工发布。人工回填链接与页面核验分别记录。</p>
      <p role="status" aria-live="polite">${esc(notice)}</p>
      ${!options.length?'<p>本页暂无已分配项目。可读取其他任务页后选择项目。</p>':`<label>项目 <select name="distribution_scope" ${busy?'disabled':''}>
        ${options.map(v=>`<option value="${key(v)}" ${selected===key(v)?'selected':''}>${v.module.toUpperCase()} · ${esc(v.tenant_name||'客户 #'+v.tenant_id)} / ${esc(v.scope_name||'项目 #'+v.scope_id)}</option>`).join('')}</select></label>
        <button type="button" data-distribution="refresh" ${busy?'disabled':''}>刷新分发记录</button>`}
      ${s&&snapshot?`<p>项目分发：${esc({running:'运行中',paused:p.revision?'已暂停':'尚未启动',ended:'已结束'}[p.state])} · 版本 ${p.revision}</p>
        <p><a href="${esc(distributionMediaHref(s))}">${s.module==='seo'?'打开 SEO 配图与审核':'进入 GEO 内容模块选择渠道稿配图'}</a> · 换图后必须重新审核。</p>
        <div class="advisor-tools">${p.state==='paused'?`<button type="button" data-distribution="${p.revision?'resume':'start'}" ${busy||!owned?'disabled':''}>${p.revision?'恢复分发':'开始分发'}</button>`:''}
        ${p.state==='running'?`<button type="button" data-distribution="pause" ${busy||!owned?'disabled':''}>暂停分发</button>`:''}
        ${p.revision&&p.state!=='ended'?`<button type="button" data-distribution="end" ${busy||!owned?'disabled':''}>结束项目分发</button>`:''}</div>
        ${!owned?'<p>项目分发由其他顾问控制，当前账号不能启动或暂停。</p>':''}
        ${!snapshot.bindings.length?'<p>尚未绑定可用执行设备和平台账号，请由超管配置。</p>':`<label>执行账号 <select name="distribution_binding" ${busy?'disabled':''}>${snapshot.bindings.map(b=>`<option value="${b.id}" ${b.id===bindingId?'selected':''}>${esc(b.device_label)} · ${b.platform==='wechat-article'?'公众号文章':'小红书图文'} · ${esc(b.account_id)}</option>`).join('')}</select></label>
          <p>设备最近联系：${esc(time(binding?.last_seen_at))}；不代表平台登录已核验。</p>
          ${distributionScheduleMarkup(schedule)}
          ${schedule?.policy?`<details><summary>项目发布节奏（不能放宽超管规则）</summary><div data-restriction>
            <label>每日最多 <input name="restriction_daily" type="number" min="1" max="${schedule.policy.daily_limit}" value="${schedule.effective_daily_limit}"></label>
            <label>最小间隔（秒）<input name="restriction_interval" type="number" min="${schedule.policy.min_interval_seconds}" max="86400" value="${schedule.effective_interval_seconds}"></label>
            <button type="button" data-distribution="restrict" ${busy||!owned?'disabled':''}>保存项目节奏</button></div></details>`:''}
          <label>已审核渠道稿 <select name="distribution_variant" ${busy||!sources.length?'disabled':''}>${sources.map(v=>`<option value="${v.variant_id}" ${v.variant_id===variantId?'selected':''}>${esc(v.title)} · #${v.variant_id}</option>`).join('')}</select></label>
          ${sources.length?`<button type="button" data-distribution="preview" ${busy?'disabled':''}>核对审核稿</button>`:'<p>当前账号渠道没有可分发的最新审核稿，或渠道尚未接入。</p>'}`}
        ${preview?`<details open><summary>审核稿预览 · ${esc(preview.source_revision)}</summary><h3>${esc(preview.content.title)}</h3><pre>${esc(preview.content.body)}</pre><p>素材 ${preview.content.assets.length} 项</p></details>
          <label><input type="checkbox" name="distribution_reviewed" ${reviewed?'checked':''} ${busy?'disabled':''}>我已核对本文稿、项目和目标账号</label>
          <label><input type="checkbox" name="distribution_manual" ${manual?'checked':''} ${busy?'disabled':''}>授权在此账号由人工发布本文稿，并回填结果</label>
          <div class="advisor-tools">${['preflight','handoff','publish'].map(action=>`<button type="button" data-distribution="${action}" ${busy||!owned||p.state!=='running'||!reviewed||action==='publish'&&!manual?'disabled':''}>${esc(actionLabels[action])}</button>`).join('')}</div>`:''}
        <h3>项目渠道排队配置</h3><p>配置并开启项目后，后台扫描自动入队；入队不等于获准发布。真实自动提交关闭。停用排队不撤销旧版逐稿人工授权；已有任务请通过项目暂停、绑定停用及结果核查处理。</p>
        ${channels.map(c=>`<article><h4>${esc(c.capability.label)} · ${esc(c.account_id)} · ${c.capability.mode==='manual'?'人工发布':'未接入'}</h4>
          <p>系统步骤：${esc(c.capability.automatic_steps.join('、')||'无')}</p><p>人工步骤：${esc(c.capability.manual_steps.join('、')||'无')}</p>
          <p>不可执行原因：${esc(queueReason(c.capability.reason))}</p>
          <button type="button" data-distribution="channel-toggle" data-id="${c.binding_id}" ${busy||!owned?'disabled':''}>${c.selected?'停用项目渠道排队':'选择并启用排队'}</button></article>`).join('')||'<p>渠道配置未读取或尚无绑定。</p>'}
        <h3>自动入队记录</h3>${queueScans.map(c=>`<p>${c.discovery==='completed-draft-polling'?'已完成渠道稿分页扫描':c.discovery==='approved-source-polling'?'仅已审核来源扫描；待审核稿发现尚未接线':'扫描不可用'} · ${esc(time(c.checked_at))} · ${esc(queueReason(c.reason))}</p>`).join('')}
        ${queueItems.map(q=>{const c=channels.find(c=>c.binding_id===q.binding_id);return `<article><p>${esc(c?.capability.label||({'wechat-article':'公众号文章','xiaohongshu-image':'小红书图文'}[q.platform]||q.platform))} · 账号 ${esc(c?.account_id||'绑定 '+q.binding_id)}</p><p>稿件 #${q.variant_id} · ${esc(queueState(q.state))}</p><p>${esc(queueReason(q.reason))} · 最近复核 ${esc(time(q.checked_at))}${q.next_allowed_at?' · 下次 '+esc(time(q.next_allowed_at)):''}</p><details><summary>内容版本</summary><p>${esc(q.draft_version)}</p></details></article>`;}).join('')||'<p>暂无入队记录。后台入口需要在集成环境独立启用。</p>'}
        ${distributionPlanningMarkup(plans)}
        ${distributionExecutionMarkup(platformDirectory,executionProgress,snapshot.bindings,busy||!owned||!p.revision||p.state==='ended')}
        <h3>逐稿授权与交接记录 · 最多 100 项（发布授权独立于自动排队开关）</h3>${tasks.map(t=>distributionTaskMarkup(t)+distributionHandoffInvestigationMarkup(t,busy||!owned)+distributionHandoffRetryMarkup(t,busy||!owned||p.state!=='running')+
          (t.resolution?`<p>人工核查 ${esc(time(t.resolution.checked_at))} · ${t.resolution.outcome==='published'?'回填已发布':'确认未发布'}</p>`:'')+
          (t.status==='succeeded'&&t.action==='publish'&&safeDistributionUrl(t.platform,publicationUrl(t))?`<details><summary>核验公开内容并回写模块</summary><div data-publication="${t.id}">
            <p>机器初检核对公开文本与账号信息；顾问仍需查看公开页面，对照本次冻结审核稿核验实际展示与全部配图。</p>
            <button type="button" data-distribution="check-machine" ${busy||!owned?'disabled':''}>尝试机器初检</button>
            <button type="button" data-distribution="publication-preview" ${busy||!owned?'disabled':''}>查看本次冻结审核稿与配图</button>
            ${t.publication?.writeback?.state==='written'?`<button type="button" data-distribution="monitor-status" ${busy||!owned?'disabled':''}>读取最新检查进度</button>`:''}
            ${publicationPreview?.task_id===t.id?`<h4>${esc(publicationPreview.content.title)}</h4><p>平台原始账号 ID：${esc(publicationPreview.external_account_id)} · 冻结版本 ${esc(publicationPreview.source_revision)}</p>
              <pre>${esc(publicationPreview.content.body)}</pre>${publicationPreview.image_urls.map((url,i)=>`<figure><img src="${esc(url)}" alt="冻结配图 ${i+1}" style="max-width:100%;height:auto"><figcaption>第 ${i+1} 张 · ${esc(publicationPreview.content.assets[i].sha256)}</figcaption></figure>`).join('')}`:''}
            <label><input type="checkbox" name="publication_public">已确认该作品可以公开访问</label>
            <label><input type="checkbox" name="publication_account">已核对作品属于本任务绑定的平台账号</label>
            <label><input type="checkbox" name="publication_content">已逐项核对标题、正文及全部配图与冻结审核稿一致</label>
            <button type="button" data-distribution="check-human" ${busy||!owned||publicationPreview?.task_id!==t.id?'disabled':''}>记录人工核验并回写</button>
            ${t.publication?.writeback&&t.publication.writeback.state!=='written'?`<button type="button" data-distribution="retry-writeback" ${busy||!owned?'disabled':''}>仅重试模块回写</button>`:''}
            </div></details>`:'')+
          (t.status==='unknown'&&t.action==='publish'?`<details><summary>核查并记录实际结果</summary><div data-resolution="${t.id}">
            <p>先停止本机执行器，并在平台后台核对实际文章。系统保留历史记录，不会自动重发。</p>
            <label>实际结果 <select name="resolution_outcome"><option value="">请选择</option>${!t.resolution?'<option value="not-published">确认未发布</option>':''}<option value="published">确认已发布</option></select></label>
            <label>已发布的公开链接 <input name="resolution_url" type="url" placeholder="填写该平台文章的公开链接"></label>
            <label><input type="checkbox" name="resolution_checked">已在平台后台核查实际结果</label>
            <label><input type="checkbox" name="resolution_stopped">已停止本机执行及人工发布操作</label>
            <button type="button" data-distribution="resolve" ${busy||!owned?'disabled':''}>保存人工核查</button></div></details>`:'')).join('')||'<p>暂无分发任务。</p>'}
        <details><summary>最近操作日志 · ${events.length} 条</summary>${events.map(e=>`<p>${esc(time(e.at))} · ${esc(e.action)} · ${esc(e.result)}</p>`).join('')||'<p>暂无记录。</p>'}</details>`:''}</section>`;
  }
  function click(event){
    const b=event.target.closest('[data-distribution]');if(!b||b.disabled)return;
    const action=b.dataset.distribution,s=scope();
    if(action==='refresh'){if(!s)selected=scopes()[0]?key(scopes()[0]):null;void load();return;}
    if(!s||!snapshot||busy)return;
    if(action==='handoff-toggle'){const id=b.dataset.id,current=executionProgress?.permissions.find(p=>p.binding_id===id);if(!snapshot.bindings.some(v=>v.id===id))return;
      if(!current?.enabled&&!browser.confirm('授权本项目当前和后续已审核版本自动进行素材人工交接。标题或正文更改须回原模块重新审核；此次不授权正式发布。'))return;
      void perform(()=>client.configureHandoff(s,{binding_id:id,enabled:!current?.enabled,stage:current?.stage||'handoff',confirm_reviewed_handoff:true,expected_revision:current?.revision||0,request_id:browser.crypto.randomUUID()}));return;}
    if(action==='channel-toggle'){const c=channels.find(c=>c.binding_id===b.dataset.id);if(!c)return;
      void perform(()=>client.selectChannel(s,{binding_id:c.binding_id,content_type:c.capability.content_type,enabled:!c.selected,expected_revision:c.revision,request_id:browser.crypto.randomUUID()}));return;}
    if(action==='monitor-status'){
      const box=b.closest('[data-publication]'),task=tasks.find(t=>t.id===box?.dataset.publication);if(!task)return;
      const stamp=epoch;busy=true;notice='正在读取原模块最新检查进度…';
      tasks=tasks.map(t=>t.id===task.id?{...t,publication:{...t.publication,monitor:undefined}}:t);onChange();
      void (async()=>{
        try{const value=await client.publicationMonitor(s,task);if(disposed||epoch!==stamp)return;
          tasks=tasks.map(t=>t.id===task.id?{...t,publication:{...t.publication,monitor:value.monitor}}:t);
          notice='已读取最新检查状态；读取不会启动检查或重新发布。';
        }catch(error){if(epoch===stamp)notice=errors[error.code]||'检查状态未能读取，请稍后重试';}
        finally{if(epoch===stamp){busy=false;onChange();}}
      })();return;
    }
    if(action==='publication-preview'){
      const box=b.closest('[data-publication]'),task=tasks.find(t=>t.id===box?.dataset.publication);if(!task)return;
      clearPublication();const stamp=epoch;busy=true;notice='正在读取本次冻结稿与原配图…';onChange();
      void (async()=>{const urls=[];let adopted=false;
        try{
          const value=await client.publicationSource(s,task);if(value.content.assets.reduce((total,a)=>total+a.bytes,0)>100000000)throw Error('asset_budget');
          for(const asset of value.content.assets){const blob=await client.publicationAsset(s,task,asset);
            if(disposed||epoch!==stamp)return;urls.push(URL.createObjectURL(blob));}
          if(disposed||epoch!==stamp)return;publicationPreview={...value,image_urls:urls};adopted=true;notice='已读取本次冻结审核稿；请与公开作品逐项核对。';
        }catch(error){if(epoch===stamp){clearPublication();notice=errors[error.code]||'冻结稿或原配图未能完整读取，暂不能记录人工核验。';}}
        finally{if(!adopted)for(const url of urls)URL.revokeObjectURL(url);if(epoch===stamp){busy=false;onChange();}}
      })();return;
    }
    if(['check-machine','check-human','retry-writeback'].includes(action)){
      const box=b.closest('[data-publication]'),task=tasks.find(t=>t.id===box?.dataset.publication);if(!box||!task)return;
      if(action==='retry-writeback'){void perform(()=>client.retryPublicationWriteback(s,task,browser.crypto.randomUUID()));return;}
      const confirmPublic=box.querySelector('[name="publication_public"]').checked,confirmAccount=box.querySelector('[name="publication_account"]').checked,
        confirmContent=box.querySelector('[name="publication_content"]').checked;
      if(action==='check-human'&&![confirmPublic,confirmAccount,confirmContent].every(Boolean)){notice='请核对公开访问、平台账号和完整审核稿后，逐项勾选确认。';onChange();return;}
      void perform(()=>client.checkPublication(s,{task,preview:publicationPreview,mode:action==='check-human'?'human':'machine',confirmPublic,confirmAccount,confirmContent,requestId:browser.crypto.randomUUID()}));return;
    }
    if(action==='restrict'){const box=b.closest('[data-restriction]'),current=schedules.find(v=>v.binding_id===bindingId);
      if(!box||!current?.policy)return;const daily=Number(box.querySelector('[name="restriction_daily"]').value),interval=Number(box.querySelector('[name="restriction_interval"]').value);
      if(!Number.isInteger(daily)||daily<1||daily>current.policy.daily_limit||!Number.isInteger(interval)||interval<current.policy.min_interval_seconds||interval>86400){notice='项目节奏只能收紧超管规则，请核对数值。';onChange();return;}
      void perform(()=>client.restrictAccount(s,{binding_id:bindingId,expected_revision:current.restriction?.revision??0,daily_limit:daily,min_interval_seconds:interval,request_id:browser.crypto.randomUUID()}));}
    if(action==='resolve'){const box=b.closest('[data-resolution]');if(!box)return;
      const outcome=box.querySelector('[name="resolution_outcome"]').value,url=box.querySelector('[name="resolution_url"]').value.trim();
      const task=tasks.find(t=>t.id===box.dataset.resolution);
      if(!task||!['published','not-published'].includes(outcome)||!box.querySelector('[name="resolution_checked"]').checked||!box.querySelector('[name="resolution_stopped"]').checked||
        outcome==='published'&&!safeDistributionUrl(task.platform,url)||outcome==='not-published'&&url){notice='请选择实际结果，核对公开链接，并确认已核查平台及停止执行。';onChange();return;}
      void perform(()=>client.resolveTask(s,{task_id:task.id,outcome,public_url:outcome==='published'?url:null,confirm_platform_checked:true,confirm_executor_stopped:true,request_id:browser.crypto.randomUUID()}));}
    if(action==='handoff-investigate'){const box=b.closest('[data-handoff-investigation]'),task=tasks.find(t=>t.id===box?.dataset.handoffInvestigation);if(!task||!(task.status==='unknown'||task.handoff_investigable===true)||task.action!=='handoff')return;
      if(!['handoff_checked','handoff_stopped','handoff_unpublished'].every(name=>box.querySelector(`[name="${name}"]`).checked)){notice='请逐项确认平台核查、执行已停止及没有发布事实；未知结果不能直接解锁。';onChange();return;}
      void perform(()=>client.resolveHandoff(s,{task_id:task.id,source_revision:task.source_revision,content_digest:task.content_digest,outcome:'not-published',confirm_platform_checked:true,confirm_executor_stopped:true,confirm_no_publication:true,request_id:browser.crypto.randomUUID()}));}
    if(action==='handoff-retry'){const box=b.closest('[data-handoff-retry]'),task=tasks.find(t=>t.id===box?.dataset.handoffRetry);if(!task||!['canceled','failed'].includes(task.status)||task.action!=='handoff')return;
      if(!['retry_stopped','retry_unpublished'].every(name=>box.querySelector(`[name="${name}"]`).checked)){notice='确认旧尝试已经停止且没有发布后，才能申请新的交接授权。';onChange();return;}
      void perform(()=>client.retryHandoff(s,{task_id:task.id,source_revision:task.source_revision,content_digest:task.content_digest,confirm_executor_stopped:true,confirm_no_publication:true,request_id:browser.crypto.randomUUID()}));}
    if(['start','pause','resume','end'].includes(action)){
      if(action==='end'&&!browser.confirm('结束后不能恢复本项目分发。已开始的人工操作需要自行停止；不确定结果会保留待核查。'))return;
      void perform(()=>client.control(s,action,snapshot.project.revision,browser.crypto.randomUUID()));
    }
    if(action==='preview'&&bindingId&&variantId){const binding=snapshot.bindings.find(v=>v.id===bindingId),stamp=epoch;
      busy=true;onChange();void client.preview(s,variantId,binding.platform).then(value=>{if(epoch===stamp&&!disposed){preview=value;reviewed=false;manual=false;notice='请核对审核稿与目标账号。';}})
        .catch(error=>{if(epoch===stamp){preview=null;notice=errors[error.code]||'审核稿读取失败';}}).finally(()=>{if(epoch===stamp){busy=false;onChange();}});
    }
    if(['preflight','handoff','publish'].includes(action)&&preview&&reviewed&&(action!=='publish'||manual))
      void perform(()=>client.enqueue(s,{bindingId,preview,action,confirmManual:manual,requestId:browser.crypto.randomUUID()}));
  }
  function change(event){const name=event.target.name;
    if(name==='distribution_scope'){selected=event.target.value;clear();void load();}
    if(name==='distribution_binding'){bindingId=event.target.value;preview=null;void load();}
    if(name==='distribution_variant'){variantId=Number(event.target.value);preview=null;reviewed=false;manual=false;onChange();}
    if(name==='distribution_reviewed'){reviewed=event.target.checked;onChange();}
    if(name==='distribution_manual'){manual=event.target.checked;onChange();}
  }
  return {html,click,change,invalidate,
    remoteContext(){const s=scope(),binding=snapshot?.bindings.find(b=>b.id===bindingId);return s&&binding?.platform==='wechat-article'?{...s,binding_id:binding.id,account_id:binding.account_id}:null;},
    remoteTasks(){const s=scope();return s?tasks.filter(t=>t.module===s.module&&t.tenant_id===s.tenant_id&&t.scope_id===s.scope_id&&t.binding_id===bindingId&&t.platform==='wechat-article'&&!t.revoked&&['preflight','handoff'].includes(t.action)&&['leased','running','awaiting-human'].includes(t.status)&&/^[a-f0-9]{64}$/.test(t.content_digest||'')).map(t=>({id:t.id,source_revision:t.source_revision,content_digest:t.content_digest,action:t.action,status:t.status})):[];},
    async initialize(allowed){modules=allowed;selected=scopes()[0]?key(scopes()[0]):null;await load();},
    filterModule(value){filter=value;if(!scope()){selected=scopes()[0]?key(scopes()[0]):null;clear();void load();}},
    dispose(){disposed=true;epoch++;unsubscribe();client.dispose();clear();},
  };
}

export function mountDistributionAdmin({root,session,fetchImpl=fetch,browser=window,catalog=[]}){
  const subscribeSession=fn=>session.$subscribe?session.$subscribe(fn,{detached:true}):()=>{};
  const client=createDistributionClient({session,fetchImpl,subscribeSession});
  let devices=[],bindings=[],schedules=[],events=[],channelCatalog=[],credential=null,notice='',busy=false,disposed=false,epoch=0;
  const admin=()=>session.user?.tenant_id===null&&['settings.accounts','settings.customers'].every(k=>session.user?.permissions?.[k]==='edit');
  function render(){if(disposed)return;root.innerHTML=!admin()?'<p>请重新核验超管身份。</p>':`<section class="pc-card distribution-panel"><h2>多号通执行设备与账号绑定</h2>
    <p>为内部执行端分配设备凭证和客户平台账号；项目启动、审核稿授权及暂停由顾问操作。</p><p role="status">${esc(notice)}</p>
    <form data-distribution-admin="device"><label>设备名称 <input name="label" required maxlength="80"></label><button ${busy?'disabled':''}>创建执行设备</button></form>
    ${credential?`<p>设备凭证仅本次展示，请保存至受控凭证存储。离开页面后不能再次读取。</p><textarea readonly aria-label="本次设备凭证">${esc(credential)}</textarea>`:''}
    <button type="button" data-distribution-admin="refresh" ${busy?'disabled':''}>刷新设备与绑定</button>
    ${devices.map(d=>`<p>${esc(d.label)} · ${d.active?'启用':'已停用'} · 最近联系 ${esc(time(d.last_seen_at))}${d.active?` <button type="button" data-distribution-admin="revoke" data-id="${d.id}" ${busy?'disabled':''}>停用</button>`:''}</p>`).join('')}
    <form data-distribution-admin="binding"><h3>绑定客户平台账号</h3>
      <label>执行设备 <select name="device_id" required>${devices.filter(d=>d.active).map(d=>`<option value="${d.id}">${esc(d.label)}</option>`).join('')}</select></label>
      <label>客户与网站／项目 <select name="target_scope" required>${catalog.map(s=>`<option value="${key(s)}">${esc(s.module.toUpperCase())} · ${esc(s.tenant_name)} / ${esc(s.scope_name)}</option>`).join('')}</select></label>
      ${catalog.length?'':'<p>当前盘点未提供可绑定的网站或项目，请先登记并刷新。</p>'}
      <label>本地账号标识 <input name="account_id" pattern="[a-zA-Z0-9_-]{1,100}" required></label>
      <label>平台账号标识 <input name="external_account_id" pattern="[a-zA-Z0-9_-]{1,100}" required></label>
      <label>发布渠道 <select name="platform"><option value="wechat-article">公众号文章</option><option value="xiaohongshu-image">小红书图文</option></select></label>
      <label><input type="checkbox" name="confirm_account_ownership" required>已人工核对该平台账号属于此客户</label>
      <button ${busy||!devices.some(d=>d.active)||!catalog.length?'disabled':''}>保存绑定</button>
    </form><p>绑定是人工声明，平台登录和真实发布能力需要另行核验。</p>
    <h3>现有账号绑定 · 最多 100 项</h3>${bindings.map(b=>`<p>${esc(b.module.toUpperCase())} · 客户 #${b.tenant_id} / 项目 #${b.scope_id} · ${esc(b.device_label)} · ${esc(b.account_id)} / ${esc(b.external_account_id)} · ${b.active&&b.device_active?'启用':'已停用'}
      ${b.active?`<button type="button" data-distribution-admin="revoke-binding" data-id="${b.id}" ${busy?'disabled':''}>停用此绑定</button>`:''}</p>`).join('')||'<p>暂无账号绑定。</p>'}
    <h3>全局自动排队授权与能力</h3><p>能力上限由已验收代码决定；超管授权不能把未验收通路升级为全自动。日上限仍由下方账号规则管理。</p>
    ${channelCatalog.map(c=>`<article><p>${esc(c.label)} · ${c.mode==='manual'?'人工发布':'未接入'} · ${esc(queueReason(c.reason))}</p>
      <p>系统步骤：${esc(c.automatic_steps.join('、')||'无')}；人工步骤：${esc(c.manual_steps.join('、')||'无')}</p>
      <button type="button" data-distribution-admin="channel-permission" data-platform="${esc(c.platform)}" ${busy||c.mode==='not-integrated'?'disabled':''}>${c.enabled?'撤销全局排队授权':'允许此渠道排队'}</button></article>`).join('')}
    <h3>平台账号发布规则</h3><p>相同平台账号在各设备及项目共用额度；以下是系统上限，平台实际额度和站外人工发布需要另行核查。未配置或未启用的账号不会收到发布任务。</p>
    ${bindings.filter(b=>b.active&&b.device_active).map(b=>{const s=schedules.find(v=>v.binding_id===b.id),p=s?.policy;return `<details><summary>${esc(b.module.toUpperCase())} · 客户 #${b.tenant_id} / 项目 #${b.scope_id} · ${esc(b.external_account_id)}</summary>
      ${distributionScheduleMarkup(s)}<form data-distribution-admin="policy" data-id="${b.id}" data-revision="${p?.revision??0}">
        <label><input name="enabled" type="checkbox" ${p?.enabled?'checked':''}>启用此账号发布规则</label>
        <label>时区 <input name="timezone" value="${esc(p?.timezone||'Asia/Shanghai')}" maxlength="60" required></label>
        <label>系统日上限 <input name="daily_limit" type="number" min="1" max="1000" value="${p?.daily_limit??''}" required></label>
        <label>最小间隔（秒）<input name="min_interval_seconds" type="number" min="0" max="86400" value="${p?.min_interval_seconds??''}" required></label>
        <label>发布时段（每行一个，跨午夜分成两行）<textarea name="windows" required placeholder="09:00-18:00">${esc(p?.windows.map(w=>clock(w.start)+'-'+clock(w.end)).join('\n')||'')}</textarea></label>
        <button ${busy||!s?'disabled':''}>保存发布规则</button></form>
        ${p?`<button type="button" data-distribution-admin="account-${p.paused_reason?'resume':'pause'}" data-id="${b.id}" data-revision="${p.revision}" ${busy?'disabled':''}>${p.paused_reason?'人工处理后恢复账号':'暂停账号分发'}</button>`:''}</details>`;}).join('')}
    <details><summary>最近分发操作日志 · 最多 100 条</summary>${events.map(e=>`<p>${esc(time(e.at))} · 操作者 ${esc(e.actor)} · ${esc(e.action)} · ${esc(e.result)}${e.target.module?' · '+esc(e.target.module.toUpperCase()):''}${e.target.tenant_id?' · 客户 #'+esc(e.target.tenant_id):''}${e.target.scope_id?' / 项目 #'+esc(e.target.scope_id):''}${e.target.binding_id?' · 绑定 '+esc(e.target.binding_id):''}${e.target.platform?' · 渠道 '+esc(e.target.platform):''}${e.target.content_type?' · 内容类型 '+esc(e.target.content_type):''}${e.task_id?' · 任务 '+esc(e.task_id):''}</p>`).join('')||'<p>暂无分发记录。</p>'}</details></section>`;}
  const clear=client.subscribe(()=>{epoch++;devices=[];bindings=[];schedules=[];events=[];channelCatalog=[];credential=null;busy=false;notice='身份或权限已变化，设备信息已清除。';render();});
  async function operation(work){if(!admin()||busy)return;const stamp=epoch;busy=true;notice='正在处理…';render();
    try{await work();if(epoch!==stamp||disposed)return;const result=await Promise.all([client.devices(),client.bindings(),client.accountPolicies(),client.adminEvents(),client.channelCatalog()]);
      if(epoch!==stamp||disposed)return;devices=result[0].items;bindings=result[1].items;schedules=result[2].items;events=result[3].items;channelCatalog=result[4].items;notice='已更新。';}
    catch(error){if(epoch===stamp){credential=null;notice=errors[error.code]||'接入尚未就绪，请核对';}}
    finally{if(epoch===stamp){busy=false;render();}}}
  function submit(event){const form=event.target.closest('[data-distribution-admin]');if(!form||form.tagName!=='FORM')return;event.preventDefault();
    const value=Object.fromEntries(new browser.FormData(form));
    if(form.dataset.distributionAdmin==='policy'){
      try{const windows=value.windows.trim().split(/\r?\n/).map(line=>{const m=/^(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})$/.exec(line.trim());
        if(!m||Number(m[1])>23||Number(m[2])>59||Number(m[3])>24||Number(m[4])>59||Number(m[3])===24&&Number(m[4])!==0)throw Error();
        return {start:Number(m[1])*60+Number(m[2]),end:Number(m[3])*60+Number(m[4])};});
        if(!windows.length||windows.length>8||windows.some((w,i)=>w.start>=w.end||i>0&&windows[i-1].end>w.start))throw Error();
        credential=null;void operation(()=>client.savePolicy({binding_id:form.dataset.id,expected_revision:Number(form.dataset.revision),enabled:value.enabled==='on',
          timezone:value.timezone.trim(),daily_limit:Number(value.daily_limit),min_interval_seconds:Number(value.min_interval_seconds),windows,request_id:browser.crypto.randomUUID()}));
      }catch{notice='请填写有效、按时间排序且不重叠的发布时段，例如09:00-18:00。';render();}}
    if(form.dataset.distributionAdmin==='device'){credential=null;void operation(async()=>{const result=await client.createDevice(value.label);credential=result.device.credential;});}
    if(form.dataset.distributionAdmin==='binding'){
      const s=catalog.find(s=>key(s)===value.target_scope);if(!s)return;
      credential=null;void operation(()=>client.bind({module:s.module,tenant_id:s.tenant_id,scope_id:s.scope_id,
        device_id:value.device_id,account_id:value.account_id,external_account_id:value.external_account_id,platform:value.platform,
        confirm_account_ownership:value.confirm_account_ownership==='on'}));
    }
  }
  function click(event){const b=event.target.closest('button[data-distribution-admin]');if(!b||b.disabled)return;
    if(b.dataset.distributionAdmin==='channel-permission'){const c=channelCatalog.find(c=>c.platform===b.dataset.platform);if(!c)return;
      void operation(()=>client.saveChannelPermission({platform:c.platform,content_type:c.content_type,enabled:!c.enabled,expected_revision:c.revision,request_id:browser.crypto.randomUUID()}));}
    if(b.dataset.distributionAdmin==='refresh')void operation(async()=>{});
    if(['account-pause','account-resume'].includes(b.dataset.distributionAdmin)){credential=null;
      void operation(()=>client.pauseAccount(b.dataset.id,Number(b.dataset.revision),b.dataset.distributionAdmin==='account-pause'?'pause':'resume',browser.crypto.randomUUID()));}
    if(b.dataset.distributionAdmin==='revoke'&&browser.confirm('停用设备后停止继续派发；已经开始的操作仍需核查。')){credential=null;void operation(()=>client.revoke(b.dataset.id));}
    if(b.dataset.distributionAdmin==='revoke-binding'&&browser.confirm('停用此账号绑定后停止继续派发；已经开始的操作仍需核查。')){credential=null;void operation(()=>client.revokeBinding(b.dataset.id));}
  }
  root.addEventListener('submit',submit);root.addEventListener('click',click);render();void operation(async()=>{});
  return {dispose(){disposed=true;epoch++;clear();client.dispose();credential=null;devices=[];bindings=[];schedules=[];events=[];root.removeEventListener('submit',submit);root.removeEventListener('click',click);root.replaceChildren();}};
}

const planningReasons={AI_PROVIDER_DISABLED:'超管已关闭服务商连接，采用规则安排',AI_BUDGET_EXHAUSTED:'AI 请求额度不足，采用规则安排',AI_CONCURRENCY_LIMIT:'AI 并发额度已占用，采用规则安排',AI_CHARGE_UNRESOLVED:'AI 费用结果待核查，暂停新请求',AI_PRICE_REQUIRED:'AI 计价信息不足，采用规则安排',AI_REQUESTED:'正在请求 AI 建议',AI_ADVICE_ADMITTED:'AI 建议已通过账号规则校验',AI_INVALID_OUTPUT:'AI 返回未通过校验，采用规则安排',AI_TIMEOUT:'AI 请求超时，采用规则安排',AI_FAILED:'AI 请求失败，采用规则安排',AI_GATEWAY_UNAVAILABLE:'主 AI 网关未接入，采用规则安排',AI_METERING_REQUIRED:'AI 计量未启用，采用规则安排',AI_NOT_CONFIGURED:'AI 配置缺失，采用规则安排',AI_ATTEMPT_UNKNOWN:'AI 请求结果未知，暂停重试并等待人工核查',ACCOUNT_SLOT_UNAVAILABLE:'允许时段内没有可用额度',ACCOUNT_SLOT_CHANGED:'账号占用变化，原建议已失效',PLANNING_RULES_CHANGED:'账号规则或项目状态变化，原建议已失效',AUTHORIZATION_OR_SOURCE_CHANGED:'权限或稿件变化，原建议已失效',AUTHORIZATION_REVOKED:'顾问权限已撤销',SOURCE_CHANGED:'稿件版本变化',REPLANNED:'已由新建议替代'};
export function distributionPlanningMarkup(value){return `<h3>发布计划建议</h3><p>后台自动规划顺序与时间；实际发布仍需人工完成。建议时间不会创建发布授权。</p>${!value?'<p>计划状态尚未读取。</p>':value.requests.map(r=>`<p>${esc(planningReasons[r.reason]||'计划需要核查')} · 尝试 ${r.attempts} / 3${r.retry_at?' · 下次重试 '+esc(time(r.retry_at)):''}</p>`).join('')+value.items.map(p=>`<article><p>${p.basis==='ai'?'AI 建议':'规则安排'} · ${esc({planned:'待人工发布',blocked:'已失效',superseded:'已替代'}[p.state])} · ${esc(time(p.planned_at))}</p><p>${esc(planningReasons[p.reason]||'计划需要核查')} · 稿件版本 ${esc(p.draft_version)} · 最近复核 ${esc(time(p.checked_at))}</p></article>`).join('')}${value&&!value.items.length?'<p>暂无计划建议。</p>':''}`;}

const executionReasons={HANDOFF_NOT_AUTHORIZED:'尚未授权项目素材交接',CAPABILITY_UNAVAILABLE:'执行端能力证明缺失、过期或未匹配，等待接线',PROJECT_OR_HANDOFF_DISABLED:'项目或交接授权已关闭',PLAN_OR_VERSION_CHANGED:'排期或稿件版本已变化',CHANNEL_DISABLED:'渠道排队已停用',PLANNED_FOR_LATER:'等待建议时间',ACCOUNT_BUSY:'同账号正在处理其他任务',OUTCOME_UNKNOWN:'账号结果未知，等待人工核查',HANDOFF_RATE_LIMIT:'等待账号交接额度或间隔',DISPATCHED:'已关联执行任务',AUTHORIZATION_REVOKED:'顾问权限已撤销',SOURCE_OR_BINDING_UNAVAILABLE:'稿件或绑定未通过复核',BINDING_UNAVAILABLE:'账号绑定不可用',BINDING_CHANGED_RETRY:'账号绑定已切换，等待重新核对'};
export function distributionExecutionMarkup(directory,value,bindings,disabled){return `<h3>统一渠道目录</h3><p>新闻源与外链由服务器 API 执行；账号渠道由公司电脑上的多号通执行。各渠道自动发稿须分别验收。</p>${directory.map(p=>`<article><p>${esc(p.label)} · ${esc(p.content_types.map(t=>({article:'文章','image-text':'图文','image-note':'图文笔记',post:'帖子',video:'视频',answer:'回答'}[t])).join('、'))} · ${p.status==='manual-handoff-candidate'?'人工交接候选':p.status==='reserved'?'预留':'待接线'}</p><p>${esc(p.missing.join('、')||'需要有效执行端能力证明与项目交接授权')}</p></article>`).join('')||'<p>渠道目录尚未读取。</p>'}<h3>项目素材交接</h3><p>一次配置后，系统按审核版本、排期、能力与账号规则推进。交接和预检完成不代表已发布；正式发布需要独立授权。</p>${bindings.map(b=>{const p=value?.permissions.find(p=>p.binding_id===b.id);return `<p>${esc(b.account_id)} <button type="button" data-distribution="handoff-toggle" data-id="${b.id}" ${disabled||!value?'disabled':''}>${p?.enabled?'停用自动素材交接':'授权自动素材交接'}</button></p>`;}).join('')}${value?.waits.map(w=>`<p>${esc(executionReasons[w.reason]||'执行步骤等待复核')} · ${esc(time(w.checked_at))}</p>`).join('')||''}${value?.items.map(i=>`<article><p>${i.stage==='preflight'?'预检':'素材人工交接'} · ${esc(i.status==='succeeded'?(i.stage==='handoff'?'素材交接完成，仍未发布':'预检完成，仍未发布'):i.status==='awaiting-human'?'等待人工发稿或处理':labels[i.status])}${i.revoked?' · 授权已失效':''}</p><p>稿件版本 ${esc(i.draft_version)} · 关联任务 ${esc(i.task_id)}</p></article>`).join('')||'<p>暂无执行关联记录。</p>'}`;}

export function distributionHandoffInvestigationMarkup(task,disabled){
 if(task.handoff_resolution)return `<p>交接调查：人工确认未发布 · ${esc(time(task.handoff_resolution.checked_at))}</p>`;
 if(task.action!=='handoff'||!(task.status==='unknown'||task.handoff_investigable===true)||!task.content_digest)return '';
 return `<details><summary>调查未知交接结果</summary><div data-handoff-investigation="${esc(task.id)}"><p>${task.status!=='unknown'?'交接授权已过期，执行结果需要核查。':''}核查本任务账号的实际结果。确认后终止旧尝试，不会自动重派或补发。</p><label><input type="checkbox" name="handoff_checked">已在平台后台核查本账号实际结果</label><label><input type="checkbox" name="handoff_stopped">已停止本机执行器及人工发布操作</label><label><input type="checkbox" name="handoff_unpublished">已确认本次交接没有发布事实</label><button type="button" data-distribution="handoff-investigate" ${disabled?'disabled':''}>保存未发布调查结果</button></div></details>`;
}

export function distributionHandoffRetryMarkup(task,disabled){
 if(task.action!=='handoff'||!['failed','canceled'].includes(task.status)||!task.handoff_attempt||!task.content_digest)return '';
 if(task.handoff_attempt>=3)return '<p>交接尝试已达上限，请重新核对稿件与账号配置。</p>';
 return `<details><summary>申请重新交接（已尝试 ${task.handoff_attempt}/3）</summary><div data-handoff-retry="${esc(task.id)}"><p>新授权会重新核对当前审核稿、渠道、能力与账号规则。登录或验证码暂停需先由超管处理账号状态。</p><label><input type="checkbox" name="retry_stopped">已确认旧尝试和人工操作停止</label><label><input type="checkbox" name="retry_unpublished">已确认旧尝试没有发布事实</label><button type="button" data-distribution="handoff-retry" ${disabled?'disabled':''}>申请新的交接任务</button></div></details>`;
}
