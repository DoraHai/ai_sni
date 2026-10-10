// Superadmin configuration UI. No secret is hydrated from a server response.
export function renderControlPanel({snapshot,esc,card,table,tenant}){
  const c=snapshot.controls;
  if(c?.state!=='enabled')return card('API 与预算管理','<p>管理功能等待启用。现有调用与费用统计继续可查看。</p>');
  const users=snapshot.sources.users.rows,tenants=snapshot.sources.tenants.rows;
  const hosts=[...new Set([...c.bindings.map(b=>b.host),...(c.default_rates||[]).map(r=>r.host)].filter(Boolean))].sort();
  const concurrency=c.capabilities?.includes('budget_concurrency_v1'),providerBudgets=c.capabilities?.includes('provider_budget_v1');
  const option=(value,label)=>`<option value="${esc(value)}">${esc(label)}</option>`;
  const field=(name,label,type='number',extra='')=>`<label>${label}<input name="${name}" type="${type}" ${extra}></label>`;
  const choices=(name,label,items)=>`<label>${label}<select name="${name}">${items}</select></label>`;
  const form=(kind,body)=>`<form class="pc-control-form" data-control-kind="${kind}"><input name="revision" type="hidden" value="0">${body}<button type="submit">保存${{budget:'预算',provider:'接口开关',rate:'单价',credential:'密钥设置'}[kind]}</button><p class="pc-note" data-control-version></p></form>`;
  const budgetForm=form('budget',choices('target','预算范围',option('global','全平台')+tenants.map(t=>option('tenant:'+t.id,'客户 · '+t.name)).join('')+users.map(u=>option('user:'+u.id,'账号 · '+u.username+(u.is_active?'':'（已停用）'))).join('')+(providerBudgets?hosts.map(h=>option('provider:'+h,'服务商 · '+h)).join(''):''))+
    field('daily_calls','每日请求上限','number','min="0" step="1"')+field('monthly_calls','每月请求上限','number','min="0" step="1"')+
    field('daily_cny','每日估算费用上限（元）','number','min="0" step="any"')+field('monthly_cny','每月估算费用上限（元）','number','min="0" step="any"')+(concurrency?field('max_concurrent','同时进行的调用上限','number','min="0" max="10000" step="1"'):'')+field('warning_percent','提醒阈值（%）','number','min="1" max="100" step="1" required'));
  const rows=c.budgets.map(b=>[esc(b.target==='global'?'全平台':b.target.startsWith('tenant:')?tenant(Number(b.target.slice(7))):users.find(u=>u.id===Number(b.target.slice(5)))?.username||b.target),
    esc(b.usage.daily_calls+' / '+(b.value.daily_calls??'无限制')),esc(b.usage.monthly_calls+' / '+(b.value.monthly_calls??'无限制')),
    esc('¥'+b.usage.daily_cny+' / '+(b.value.daily_cny??'无限制')),esc('¥'+b.usage.monthly_cny+' / '+(b.value.monthly_cny??'无限制')),
    ...(concurrency?[esc((b.usage.active_calls??'未知')+' / '+(b.value.max_concurrent??'无限制')),esc(b.usage.unresolved_calls??'未知')]:[]),
    esc({normal:'正常',warning:'接近上限',blocked:'已达上限',unknown:'未知费用，金额预算暂停'}[b.status])]);
  const providerForm=form('provider',choices('host','服务商',hosts.map(h=>option(h,h)).join(''))+choices('enabled','接口状态',option('true','启用')+option('false','停用')));
  const rateForm=form('rate',choices('host','服务商',hosts.map(h=>option(h,h)).join(''))+
    field('model','精确模型名 / 按次接口','text','maxlength="200" required list="pc-rate-models"')+
    `<datalist id="pc-rate-models">${[...new Set([...c.bindings.map(b=>b.model),...(c.default_rates||[]).map(r=>r.model),...(snapshot.api_costs?.recent||[]).map(r=>r.model||r.endpoint),...(snapshot.api_costs?.provider_totals||[]).map(r=>r.model||r.endpoint)].filter(Boolean))].map(m=>option(m,m)).join('')}</datalist>`+
    choices('unit','计价方式',option('tokens','每百万 Token')+option('request','每次请求'))+
    field('input','输入单价（元 / 百万）','number','min="0" step="any" data-price-unit="tokens"')+
    field('output','输出单价（元 / 百万）','number','min="0" step="any" data-price-unit="tokens"')+
    field('cached','缓存输入单价（可空）','number','min="0" step="any" data-price-unit="tokens"')+
    field('max_input','计价输入 Token 上限','number','min="1" max="10000000" step="1" data-price-unit="tokens"')+
    field('per_request','每次请求单价（元）','number','min="0" step="any" data-price-unit="request"')+
    field('source','单价依据 / 合同版本','text','maxlength="200" required'));
  const rotatable=c.bindings.filter(b=>b.configured&&b.can_rotate);
  const credentialForm=rotatable.length?form('credential',choices('binding','密钥绑定（同一密钥的服务共同生效）',rotatable.map(b=>option(b.id,b.module.toUpperCase()+' · '+b.label+' · '+b.host)).join(''))+
    choices('mode','设置方式',option('replace','替换密钥')+option('restore','恢复服务器原密钥'))+
    field('secret','新 API 密钥','password','autocomplete="off" minlength="8" maxlength="4096" required')):'<p>暂无支持在线轮换的已配置密钥。</p>';
  const bindings=c.bindings.map(b=>{const credential=c.credentials.find(k=>k.id===b.id),provider=c.settings.find(r=>r.key==='provider:'+b.host);return [esc(b.module.toUpperCase()),esc(b.label),esc(b.host),esc(b.model||'按次接口'),b.configured?'已配置':'未配置',provider?.value.enabled===false?'已停用':'启用',credential?.overridden?'管理密钥 · v'+credential.revision:'服务器配置'];});
  const prices=new Map((c.default_rates||[]).map(r=>['rate:'+r.host+':'+r.model,{...r,unit:r.unit||'tokens',version:r.version||'官方已审核'}]));
  for(const row of c.settings.filter(r=>r.kind==='rate'))prices.set(row.key,row.value);
  const priceRows=[...prices].map(([key,p])=>[esc(key.slice(5)),esc(p.unit==='request'?'每次请求':'每百万 Token'),
    esc(p.unit==='request'?p.per_request:p.input+' / '+p.output+' / '+(p.cached??'未设置')),esc(p.version)+(p.pricing_basis==='peak_ceiling'?'<small class="pc-cell-note">高峰单价 · 保守上限</small>':''),esc(p.source)]);
  return card('预算设置',budgetForm,'空白表示不限制，0 表示零额度。平台、客户、账号及服务商的限制共同检查；仅作用于已部署并启用准入保护的调用路径。日/月额度按北京时间重置；并发占用与未核清费用不会随日期重置。')+
    card('当前预算与占用',table(['范围','每日请求 / 上限','每月请求 / 上限','每日占用 / 上限','每月占用 / 上限',...(concurrency?['当前并发 / 上限','费用待核查']:[]),'状态'],rows),'金额占用包括预留额度。已结束但费用未知的调用会暂停金额预算；未结束调用保留并发占用。请在 API 调用明细中核查，告警标记已处理不会释放占用。')+
    card('接口与密钥登记',table(['模块','配置项','服务商','模型','配置状态','接口状态','密钥来源'],bindings),'配置状态由各服务登记，不表示已通过付费连通测试。百度推广 OAuth 沿用原授权流程。')+
    card('服务商开关',providerForm,'停用会拦截该服务商之后的新请求；已经发出的请求继续完成。')+
    card('当前单价',table(['服务商 / 模型或接口','单位','单价：输入 / 输出 / 缓存','版本','依据'],priceRows),'已审核的默认价格与管理员设置使用同一精确匹配规则。未登记价格的接口费用保持未知。')+
    card('API 单价',rateForm,'仅支持人民币。请按具体合同填写精确模型名及单价；输入 / 输出为每百万 Token 价格。新价格只用于之后的请求，历史调用保留原单价版本。')+
    card('密钥轮换',credentialForm,'密钥加密保存且不会回显。替换后用于之后的新调用；恢复时使用服务器原配置。此操作不会撤销服务商侧的旧密钥。');
}

export function hydrateControlForm(form,snapshot,loadValues=true){
  const c=snapshot.controls;if(!c)return;
  const f=form.elements,kind=form.dataset.controlKind;
  let key=kind==='budget'?'budget:'+f.target.value:kind==='provider'?'provider:'+f.host.value:kind==='rate'?'rate:'+f.host.value+':'+f.model.value:f.binding.value;
  const row=kind==='credential'?c.credentials.find(r=>r.id===key):c.settings.find(r=>r.key===key);
  f.revision.value=row?.revision??0;
  form.querySelector('[data-control-version]').textContent='当前配置版本：'+f.revision.value;
  if(loadValues){
    const defaults=kind==='budget'?{daily_calls:'',monthly_calls:'',daily_cny:'',monthly_cny:'',max_concurrent:'',warning_percent:80}:
      kind==='provider'?{enabled:true}:kind==='rate'?{unit:'tokens',input:'',output:'',cached:'',max_input:1000000,per_request:'',source:''}:{};
    const rate=kind==='rate'?(c.default_rates||[]).find(r=>r.host===f.host.value&&r.model===f.model.value):null;
    const data={...defaults,...rate,...row?.value};
    for(const [name,v] of Object.entries(data))if(f.namedItem(name))f.namedItem(name).value=v??'';
  }
  if(kind==='rate')for(const input of form.querySelectorAll('[data-price-unit]')){
    input.disabled=input.dataset.priceUnit!==f.unit.value;input.closest('label').hidden=input.disabled;
    input.required=!input.disabled&&input.name!=='cached';
  }
  if(kind==='credential'){
    f.secret.disabled=f.mode.value==='restore';f.secret.required=!f.secret.disabled;
    if(f.secret.disabled)f.secret.value='';
  }
}

export function controlPayload(form){
  const f=form.elements,kind=form.dataset.controlKind;
  let key,value;
  if(kind==='budget'){
    key='budget:'+f.target.value;value={};
    for(const name of ['daily_calls','monthly_calls','daily_cny','monthly_cny'])value[name]=f[name].value===''?null:name.endsWith('calls')?Number(f[name].value):f[name].value;
    value.warning_percent=Number(f.warning_percent.value);
    if(f.max_concurrent)value.max_concurrent=f.max_concurrent.value===''?null:Number(f.max_concurrent.value);
  }else if(kind==='provider'){
    key='provider:'+f.host.value;value={enabled:f.enabled.value==='true'};
  }else if(kind==='rate'){
    key='rate:'+f.host.value+':'+f.model.value.trim();value={unit:f.unit.value,source:f.source.value.trim()};
    if(value.unit==='request')value.per_request=f.per_request.value;
    else Object.assign(value,{input:f.input.value,output:f.output.value,cached:f.cached.value||null,max_input:Number(f.max_input.value)});
  }else{
    key=f.binding.value;value={key:f.mode.value==='restore'?null:f.secret.value};f.secret.value='';
  }
  return {request_id:crypto.randomUUID(),kind,key,expected_revision:Number(f.revision.value),value};
}
