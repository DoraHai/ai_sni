// Public parameters only. A secret is accepted once, cleared, and never hydrated.
export function renderSystemConfig({snapshot,esc,card,table,selected}){
  const c=snapshot.controls,connections=c?.connections||[],enabled=c?.state==='enabled';
  const sourceLabel=r=>!r.registered?'尚未登记':r.source==='managed'?'超管配置':'服务器配置';
  const rows=connections.map(r=>[esc(r.module.toUpperCase()),esc(r.label),esc(sourceLabel(r)),
    !r.registered?'未知':(Object.values(r.secret_status||{}).some(Boolean)?'已配置':'未配置')+(r.parameters?.enabled===false?' · 默认停用':''),
    esc(r.parameters?.model||'按次接口'),esc(r.parameters?.base_url||'尚未登记'),
    `<button data-pc-connection="${esc(r.id)}">查看 / 配置</button>`]);
  const chosen=connections.find(r=>r.id===selected)||connections.find(r=>r.registered&&r.supported)||connections[0];
  const runtime=(c?.module_status||[]).flatMap(r=>(r.settings||[]).map(f=>[esc(r.module.toUpperCase()),esc(f.label),esc(typeof f.value==='boolean'?(f.value?'开启':'关闭'):String(f.value)),esc(r.seen_at||'未登记')]));
  let body='';
  if(chosen){
    const active=enabled&&chosen.registered&&chosen.supported,disabled=active?'':'disabled';
    const fields=(chosen.fields||[]).map(f=>{
      const name='connection-param-'+f.name;
      const control=f.type==='boolean'?`<select name="${name}" data-connection-param="${esc(f.name)}"><option value="true">启用</option><option value="false">停用平台默认配置</option></select>`:
        `<input name="${name}" data-connection-param="${esc(f.name)}" type="${f.type==='timeout'?'number':f.type==='url'?'url':'text'}" ${f.type==='timeout'?'min="1" max="120" step="any"':f.type==='url'?'maxlength="500"':'maxlength="120"'} required>`;
      return `<label>${esc(f.label)}${control}</label>`;
    }).join('');
    const secrets=(chosen.secret_fields||[]).map(f=>`<label>${esc(f.label)} · ${chosen.secret_status?.[f.name]?'已配置':'未配置'}<input name="connection-secret-${esc(f.name)}" data-connection-secret="${esc(f.name)}" type="password" autocomplete="off" maxlength="4096" placeholder="留空保留原值，首次配置请填写"></label><label><input type="checkbox" data-connection-clear="${esc(f.name)}">明确清除此项密钥</label>`).join('');
    body=`<form class="pc-control-form" data-control-kind="connection" data-connection-id="${esc(chosen.id)}"><input name="revision" type="hidden" value="${chosen.revision||0}"><label>配置项<select name="connection_id">${connections.map(r=>`<option value="${esc(r.id)}" ${r.id===chosen.id?'selected':''}>${esc(r.module.toUpperCase()+' · '+r.label)}</option>`).join('')}</select></label><p class="pc-note">生效范围：${esc(chosen.module.toUpperCase())} 的平台默认配置。已在运行的任务保留本轮配置；后续请求或任务读取新版本。客户专属凭据沿用原权限与优先级。</p><label>设置方式<select name="connection_mode" ${disabled}><option value="update">保存参数 / 首次配置 / 更换密钥</option><option value="restore">恢复该项服务器原配置</option></select></label><fieldset data-connection-fields ${disabled}>${fields}${secrets}</fieldset>${chosen.note?`<p class="pc-note">${esc(chosen.note)}</p>`:""}<button type="submit" ${disabled}>保存接口配置</button><p class="pc-note" data-control-version>当前配置版本：${chosen.revision||0}</p>${!active?'<p class="pc-note">管理表及功能尚未启用，或该模块尚未登记此配置；当前不能保存。</p>':''}<p class="pc-note">密钥不回显，保存时立即清空输入。保存配置不调用付费 API，也不代表连通测试成功。接口地址仅允许对应服务商的官方 HTTPS 域名。</p></form>`;
  }
  return card('SEM / SEO / GEO 系统配置',table(['模块','接口配置','来源','密钥状态','模型','接口地址','操作'],rows),enabled?'统一管理平台默认接口参数与首次密钥配置。':'配置管理尚未启用，调用计量继续运行。')+
    card('接口参数与密钥',body||'<p>配置清单尚未接入，请刷新核对服务版本。</p>')+
    card('业务运行配置',runtime.length?table(['模块','运行参数','当前服务器值','登记时间'],runtime):'<p>各模块尚未登记运行配置，启用后显示。</p>','用于核对自动采集、巡检、生成、发布与恢复开关。此表是服务器登记值；调度参数由发布配置管理，客户服务计划在对应客户范围管理。')+
    card('已有业务配置入口',`<div class="pc-shortcuts"><a class="pc-link" href="/platform/customers">客户、模块与推广账号授权 ↗</a><a class="pc-link" href="/geo/models">GEO 监测引擎 ↗</a><a class="pc-link" href="/geo/publishing">GEO 发布渠道与客户账号 ↗</a><a class="pc-link" href="/seo/distribution">SEO 发布渠道与客户账号 ↗</a></div>`,'客户专属配置需进入对应客户范围；这里的接口参数不改变客户业务归属、服务计划或资金写回授权。')+
    card('启用与检查范围',`<p>当前配置管理：${esc({enabled:'已启用',ready:'管理表已就绪，功能未启用',schema_pending:'管理表等待安装'}[c?.state]||'状态未提供')}。</p><p>本页显示配置登记、密钥是否存在及公开参数。实际接口健康请结合调用结果查看；首次付费连通测试应明确发起。</p><p>预算、单价、接口开关见“API 与预算管理”；变更记录见“安全与运维”。未登记价格的调用保留“待定价”。</p>`);
}

export function hydrateConnectionForm(form,snapshot){
  const r=snapshot.controls?.connections?.find(r=>r.id===form.dataset.connectionId);if(!r)return;
  form.elements.revision.value=r.revision||0;
  for(const input of form.querySelectorAll('[data-connection-param]'))input.value=r.parameters?.[input.dataset.connectionParam]??(input.tagName==='SELECT'?'true':'');
  setConnectionMode(form);
}

export function setConnectionMode(form){
  const active=Boolean(form.querySelector('button[type=submit]')&&!form.querySelector('button[type=submit]').disabled);
  const restore=form.elements.connection_mode.value==='restore';
  form.querySelector('[data-connection-fields]').disabled=!active||restore;
  for(const input of form.querySelectorAll('[data-connection-secret]'))if(restore)input.value='';
}

export function connectionPayload(form){
  const restore=form.elements.connection_mode.value==='restore',parameters={},secrets={};
  if(!restore){
    for(const input of form.querySelectorAll('[data-connection-param]'))parameters[input.dataset.connectionParam]=input.tagName==='SELECT'?input.value==='true':input.type==='number'?Number(input.value):input.value.trim();
    for(const input of form.querySelectorAll('[data-connection-secret]')){
      const name=input.dataset.connectionSecret,clear=[...form.querySelectorAll('[data-connection-clear]')].find(c=>c.dataset.connectionClear===name)?.checked;
      if(clear)secrets[name]=null;else if(input.value)secrets[name]=input.value;
      input.value='';
    }
  }
  return {request_id:crypto.randomUUID(),kind:'connection',key:'connection:'+form.dataset.connectionId,
    expected_revision:Number(form.elements.revision.value),value:{parameters,secrets,restore}};
}
