import {escapeText as esc} from './customer-display.mjs';

const base='/customer-workbench/';
const positive=value=>Number.isSafeInteger(value)&&value>0;
export function entryScope(search){
  const p=new URLSearchParams(search),present=p.has('tenant_id')||p.has('site_id');
  const id=name=>p.getAll(name).length===1&&/^[1-9]\d*$/.test(p.get(name)||'')&&positive(Number(p.get(name)))?Number(p.get(name)):null;
  const tenantId=id('tenant_id'),siteId=id('site_id');
  return {tenantId,siteId,invalid:present&&!(tenantId&&siteId),login:p.get('login')==='1'};
}
export const workbenchPath=(tenantId,siteId)=>base+(positive(tenantId)&&positive(siteId)?'?'+new URLSearchParams({tenant_id:tenantId,site_id:siteId}):'');
export const workbenchLoginPath=(tenantId,siteId)=>workbenchPath(tenantId,siteId)+(positive(tenantId)&&positive(siteId)?'&':'?')+'login=1';

// Dedicated customer entry, using the existing auth API and canonical session store.
// No business writes, credential persistence, fallback tenant, or authority from URL.
export function mountWorkbenchEntry({root,session,search=location.search,fetchImpl=fetch,navigate=path=>location.assign(path)}){
  const scope=entryScope(search);
  let generation=0,disposed=false,ownSessionChange=false,tenants=[],sites=[],tenantId=null,siteId=null,controllers=new Set();
  const frame=body=>{root.innerHTML=`<header class="entry-header"><b>G-SNIPERS</b><span>客户工作台</span></header><main class="entry-layout"><section class="entry-intro"><small>你的推广工作，在这里继续</small><h1>看进展，确认稿件，<br>与顾问一起推进。</h1><p>使用已有账号登录，无需先进入运营模块。</p></section><section class="entry-card">${body}</section></main>`;};
  const invalidate=()=>{generation++;for(const c of controllers)c.abort();controllers.clear();};
  const current=g=>!disposed&&generation===g;
  function setSession(fn){ownSessionChange=true;try{fn();}finally{ownSessionChange=false;}}
  const status=text=>{const el=root.querySelector('[role=status]');if(el)el.textContent=text;};
  function expired(){setSession(()=>session.logout());invalidate();login('登录已失效，请重新登录。');}
  async function read(path,g){
    const token=session.token,revision=session.authRevision;
    const controller=new AbortController();controllers.add(controller);
    try{
      const r=await fetchImpl(path,{headers:{Authorization:`Bearer ${token}`,Accept:'application/json'},credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
      if(!current(g)||token!==session.token||revision!==session.authRevision)throw Error('STALE');
      if(r.status===401){expired();throw Error('STALE');}
      if(!r.ok)throw Error(r.status===403?'当前账号没有访问权限，请联系顾问或管理员。':'读取未完成，请稍后重试。');
      const data=await r.json();if(!current(g)||token!==session.token||revision!==session.authRevision)throw Error('STALE');return data;
    }finally{controllers.delete(controller);}
  }
  function errorView(text){frame(`<h2>暂时无法进入</h2><p role="status">${esc(text)}</p><button data-entry="retry">重新读取</button> <button data-entry="logout">退出当前账号</button>`);}
  function selector(note=''){
    frame(`<small>${esc(session.user?.display_name||session.user?.username||'已登录')}</small><h2>选择工作空间</h2><p>仅显示当前账号获准查看的客户与网站。</p><p role="status">${esc(note)}</p><label for="entry-tenant">客户</label><select id="entry-tenant"><option value="">请选择客户</option>${tenants.map(t=>`<option value="${t.id}" ${tenantId===t.id?'selected':''}>${esc(t.name||'客户 '+t.id)}</option>`).join('')}</select><label for="entry-site">网站</label><select id="entry-site" ${sites.length?'':'disabled'}><option value="">请选择网站</option>${sites.map(s=>`<option value="${s.id}" ${siteId===s.id?'selected':''}>${esc(s.name||s.domain||'网站 '+s.id)}</option>`).join('')}</select><button data-entry="enter" class="entry-primary" ${siteId?'':'disabled'}>进入工作台</button><div class="entry-footer"><button data-entry="retry">刷新可用空间</button><button data-entry="logout">退出账号</button></div><small>当前入口已接入 SEO 服务；SEM、GEO 的接入状态与模块开通分别显示。</small>`);
  }
  async function loadSites(id,auto=false){
    invalidate();const g=generation;tenantId=id;siteId=null;sites=[];selector('正在读取网站…');
    try{
      const data=await read('/api/v1/seo/workbench/sites?tenant_id='+id,g);
      if(data.tenant_id!==id||!Array.isArray(data.sites)||!data.selection_policy?.selectable_statuses?.includes('active'))throw Error('网站范围未通过核验。');
      sites=data.sites.filter(s=>positive(s.id)&&s.status==='active'&&(s.tenant_id==null||s.tenant_id===id));
      if(sites.length===1)siteId=sites[0].id;
      selector(sites.length?'':'此客户暂时没有可用网站，请顾问在模块中完成网站配置。');
      if(auto&&siteId)enter();
    }catch(e){if(current(g)&&e.message!=='STALE')selector(e.message);}
  }
  function enter(){if(!tenants.some(t=>t.id===tenantId)||!sites.some(s=>s.id===siteId))return;setSession(()=>session.setTenant(tenantId));navigate(workbenchPath(tenantId,siteId));}
  async function spaces(){
    invalidate();const g=generation;tenants=[];sites=[];tenantId=null;siteId=null;
    frame('<h2>正在打开工作台</h2><p role="status">核对账号与可用工作空间…</p>');
    try{
      const {user}=await read('/api/v1/auth/me',g);
      if(!positive(user?.id)||user.id!==session.user?.id||!user.permissions)throw Error('账号身份未通过核验，请退出后重新登录。');
      setSession(()=>session.refreshUser(user));
      const modules=await read('/api/v1/auth/modules',g);
      if(modules.tenant_id!==user.tenant_id||!Array.isArray(modules.modules)||!modules.modules.some(m=>m.module_code==='seo'&&m.available===true))throw Error('当前账号没有可用的 SEO 服务；其他模块尚未接入此客户工作台。');
      if(!['view','edit'].includes(user.permissions['seo.content']))throw Error('当前账号没有稿件查看权限，请联系顾问或管理员。');
      const data=await read('/api/v1/auth/tenants?module=seo',g);
      if(data.module!=='seo'||!Array.isArray(data.tenants))throw Error('客户清单未通过核验。');
      tenants=data.tenants.filter(t=>positive(t.id)&&(user.tenant_id==null||t.id===user.tenant_id));
      selector(tenants.length?'':'尚未分配可用客户，请联系顾问或管理员。');
      if(tenants.length===1)await loadSites(tenants[0].id,true);
    }catch(e){if(current(g)&&e.message!=='STALE')errorView(e.message);}
  }
  let captcha='';
  function refreshCaptcha(){
    // Matches the existing login page's local visual challenge, not server verification.
    const chars='23456789ABCDEFGHJKLMNPQRSTUVWXYZ';captcha=Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>chars[n%chars.length]).join('');
    const el=root.querySelector('[data-entry=captcha]');if(el)el.textContent=captcha;
    const input=root.querySelector('#entry-captcha');if(input)input.value='';
  }
  function login(note=''){
    frame(`<h2>登录客户工作台</h2><p>客户与顾问使用同一工作台，操作范围由账号权限决定。</p><form id="entry-login"><label for="entry-username">账号</label><input id="entry-username" name="username" autocomplete="username" maxlength="50" required><label for="entry-password">密码</label><input id="entry-password" name="password" type="password" autocomplete="current-password" maxlength="100" required><label for="entry-captcha">图形验证码</label><div class="entry-captcha"><input id="entry-captcha" name="captcha" autocomplete="off" maxlength="4" required><button type="button" data-entry="captcha" title="点击换一组验证码" aria-label="换一组验证码"></button></div><label class="entry-remember"><input type="checkbox" name="remember">记住登录状态（公共电脑请勿勾选）</label><p role="status">${esc(note)}</p><button type="submit" class="entry-primary">登录并进入</button></form>${session.token?'<button data-entry="continue">继续使用当前账号</button>':''}<p class="entry-footer">忘记密码或需要开通服务，请联系你的顾问。</p>`);refreshCaptcha();
  }
  async function submit(event){
    if(event.target.id!=='entry-login')return;event.preventDefault();
    const form=event.target,button=form.querySelector('[type=submit]');if(button.disabled)return;
    if(form.elements.captcha.value.trim().toUpperCase()!==captcha){refreshCaptcha();status('图形验证码不正确，请输入新验证码。');return;}
    const g=generation,username=form.elements.username.value.trim(),password=form.elements.password.value,remember=form.elements.remember.checked;
    button.disabled=true;status('正在登录…');const c=new AbortController();controllers.add(c);
    try{
      const r=await fetchImpl('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({username,password}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([c.signal,AbortSignal.timeout(20000)])});
      if(!current(g))return;
      if(!r.ok)throw Error(r.status===401?'用户名或密码不正确，或账号暂时被锁定。':r.status===403?'账号已停用，请联系管理员。':r.status===429?'尝试过于频繁，请稍后再试。':'登录未完成，请稍后重试。');
      const data=await r.json();if(!current(g))return;
      if(typeof data.token!=='string'||!data.token||/\s/.test(data.token)||!positive(data.user?.id)||!data.user.permissions)throw Error('登录返回不完整，请联系管理员。');
      setSession(()=>session.setAuth(data.token,data.user,remember));form.elements.password.value='';
      navigate(workbenchPath(scope.tenantId,scope.siteId));
    }catch(e){if(current(g)){status(e.name==='TimeoutError'?'登录超时，请重试。':e.message==='Failed to fetch'?'网络连接失败，请稍后重试。':e.message);form.elements.password.value='';refreshCaptcha();}}
    finally{controllers.delete(c);if(current(g))button.disabled=false;}
  }
  function click(event){
    const button=event.target.closest('[data-entry]');if(!button||button.disabled)return;
    const a=button.dataset.entry;
    if(a==='captcha')refreshCaptcha();
    if(a==='retry')void spaces();
    if(a==='logout'){invalidate();setSession(()=>session.logout());login('已退出。');}
    if(a==='continue')navigate(workbenchPath(scope.tenantId,scope.siteId));
    if(a==='enter')enter();
    if(a==='choose')navigate(base);
  }
  function change(event){
    if(event.target.id==='entry-tenant'){const id=Number(event.target.value);if(tenants.some(t=>t.id===id))void loadSites(id);else{invalidate();tenantId=null;siteId=null;sites=[];selector();}}
    if(event.target.id==='entry-site'){const id=Number(event.target.value);siteId=sites.some(s=>s.id===id)?id:null;root.querySelector('[data-entry=enter]').disabled=!siteId;}
  }
  function sessionChanged(){if(disposed||ownSessionChange)return;invalidate();if(!session.token)login('账号已退出，请重新登录。');else void spaces();}
  root.addEventListener('submit',submit);root.addEventListener('click',click);root.addEventListener('change',change);window.addEventListener('sem:auth-context-changed',sessionChanged);
  if(scope.invalid)frame('<h2>工作空间链接不完整</h2><p>客户或网站参数不正确，请重新选择。</p><button data-entry="choose">选择工作空间</button>');
  else if(!session.token||scope.login)login();else void spaces();
  return {dispose(){disposed=true;invalidate();root.removeEventListener('submit',submit);root.removeEventListener('click',click);root.removeEventListener('change',change);window.removeEventListener('sem:auth-context-changed',sessionChanged);root.replaceChildren();}};
}
