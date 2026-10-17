import {isPlatformAdmin} from './platform-console-client.mjs';
import {escapeText as esc} from './customer-display.mjs';

const positive=id=>Number.isSafeInteger(id)&&id>0;
const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
export function eligibleAdvisor(user,roles){
  if(user?.is_active!==true||!positive(user.id)||!positive(user.tenant_id))return false;
  const role=roles.find(r=>r.id===user.role_id),p=role?.permissions;
  // The built-in administrator gains settings edit rights on the server.
  if(!p||role.is_system&&role.name==='管理员'||Object.entries(p).some(([k,v])=>k.startsWith('settings.')&&v==='edit'))return false;
  return p['seo.site']==='edit'&&p['seo.content']==='edit'||p['geo.assets']==='edit'&&p['geo.content']==='edit';
}
export function advisorLinkPayload(ids,groupId,users,roles){
  const group=String(groupId||'').trim();
  if(!Array.isArray(ids)||ids.length<2||ids.length>20||new Set(ids).size!==ids.length||ids.some(id=>!positive(id)))throw Error('请选择 2–20 个不同账号。');
  if(group&&!uuid.test(group))throw Error('已有 group_id 必须为完整 UUID。');
  const selected=ids.map(id=>users.find(u=>u.id===id));
  if(selected.some(u=>!eligibleAdvisor(u,roles)))throw Error('选中账号的顾问资格不符，请重新读取账号。');
  if(new Set(selected.map(u=>u.tenant_id)).size!==selected.length)throw Error('同一关联组的账号必须属于不同客户。');
  return {user_ids:ids,...(group?{group_id:group}:{})};
}

export function createAdvisorLinksClient({session,fetchImpl=fetch}){
  let epoch=0;const pending=new Set();
  const key=()=>JSON.stringify([session.token,session.user?.id,session.user?.tenant_id,session.authRevision,session.user?.permissions]);
  function invalidate(){epoch++;for(const c of pending)c.abort();pending.clear();}
  async function request(path,body,stamp,context){
    const current=()=>{if(epoch!==stamp||key()!==context||!isPlatformAdmin(session.user))throw Error('会话或权限已变化，请重新打开表单。');};
    current();
    const token=session.token;if(typeof token!=='string'||!token||/\s/.test(token))throw Error('请使用平台管理员正规登录。');
    const c=new AbortController();pending.add(c);
    try{
      const r=await fetchImpl(path,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},
        ...(body?{body:JSON.stringify(body)}:{}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.any([c.signal,AbortSignal.timeout(20000)])});
      current();const data=await r.json();current();
      if(!r.ok){
        // Use fixed messages: never render arbitrary server bodies or credentials.
        const labels={401:'登录已失效，请重新登录。',403:'权限不足、账号资格不符或同客户冲突。',404:'关联组不存在，请核对 group_id。',409:'账号已有关联组，请勿重复关联。',422:'请求字段未通过校验，请核对账号与 group_id。',503:'关联服务暂不可用，请稍后重试。'};
        throw Error(labels[r.status]||`请求未完成（HTTP ${r.status}），请核对后重试。`);
      }
      return data;
    }catch(e){
      if(e.name==='AbortError'||e.name==='TimeoutError'||e instanceof TypeError||e instanceof SyntaxError)throw Error(body?'提交结果未确认，请先核实关联状态，勿重复提交。':'账号读取未完成，请重试。');
      throw e;
    }finally{pending.delete(c);}
  }
  async function authorized(stamp,context){
    const data=await request('/api/v1/auth/me',null,stamp,context);
    if(data.user?.id!==session.user?.id||!isPlatformAdmin(data.user))throw Error('需要当前已启用的实名平台管理员。');
  }
  return {invalidate,
    async catalog(){
      const stamp=epoch,context=key();await authorized(stamp,context);
      const [u,r]=await Promise.all([request('/api/v1/users',null,stamp,context),request('/api/v1/roles',null,stamp,context)]);
      if(!Array.isArray(u.users)||!Array.isArray(r.roles)||u.users.some(v=>!positive(v?.id))||r.roles.some(v=>!positive(v?.id)))throw Error('账号目录格式未通过校验。');
      return {users:u.users,roles:r.roles};
    },
    async create(payload){
      const stamp=epoch,context=key();await authorized(stamp,context);
      const data=await request('/api/v1/auth/account-links',payload,stamp,context);
      if(!uuid.test(data.group_id)||!Array.isArray(data.user_ids)||data.user_ids.some(id=>!positive(id))||new Set(data.user_ids).size!==data.user_ids.length||payload.user_ids.some(id=>!data.user_ids.includes(id))||payload.group_id&&payload.group_id.toLowerCase()!==data.group_id.toLowerCase())throw Error('提交结果格式未确认，请先核实关联状态，勿重复提交。');
      return data;
    },
  };
}

export function createAdvisorLinksPanel({session,fetchImpl=fetch,onChange=()=>{}}){
  const client=createAdvisorLinksClient({session,fetchImpl});
  let opened=false,busy=false,users=[],roles=[],selected=[],groupId='',message='',result=null,revision=0;
  function reset(){revision++;client.invalidate();opened=false;busy=false;users=[];roles=[];selected=[];groupId='';message='';result=null;}
  async function open(){
    reset();opened=true;busy=true;const stamp=revision;onChange();
    try{const data=await client.catalog();if(stamp!==revision)return;users=data.users;roles=data.roles;}
    catch(e){if(stamp===revision)message=e.message;}
    finally{if(stamp===revision){busy=false;onChange();}}
  }
  function validation(){try{advisorLinkPayload(selected,groupId,users,roles);return '';}catch(e){return e.message;}}
  return {reset,
    html(){
      if(!isPlatformAdmin(session.user))return '';
      if(!opened)return '<section class="pc-card"><h2>顾问账号关联</h2><p>将同一位顾问在不同客户下的账号关联，供顾问自行切换。</p><button data-pc="advisor-links-open">建立 / 扩展顾问关联组</button></section>';
      const candidates=users.filter(u=>eligibleAdvisor(u,roles));
      return `<section class="pc-card"><h2>建立 / 扩展顾问关联组</h2><p>请确认账号属于同一位顾问。选择 2–20 个启用、单客户且有 SEO 或 GEO 编辑权限的账号；每个账号须属于不同客户。</p><p>留空 group_id 新建组；填写已知 group_id 扩组。暂不提供关联组列表；请填写已知组 ID。账号是否已入组将在提交时核验。</p><form id="pc-advisor-links"><fieldset ${busy||result?'disabled':''}><legend>可关联账号（${candidates.length}）</legend>${candidates.map(u=>`<label class="pc-link-account"><input type="checkbox" name="advisor_user" value="${u.id}" ${selected.includes(u.id)?'checked':''}> ${esc(u.display_name||u.username)} · ${esc(u.username)} · ${esc(u.tenant_name||'客户 '+u.tenant_id)}（#${u.id}）</label>`).join('')||'<p>暂无符合条件的账号，或目录尚未读取完成。</p>'}<label>已有 group_id（可选）<input name="group_id" maxlength="36" value="${esc(groupId)}" autocomplete="off" placeholder="留空新建组，或输入已有 UUID"></label></fieldset><p role="status" aria-live="polite">${esc(busy?'正在处理…':message||validation())}</p>${result?`<p>操作成功。关联组：<code>${esc(result.group_id)}</code>；组内账号 ID：${result.user_ids.map(esc).join('、')}</p>`:''}<button type="submit" ${busy||result||validation()?'disabled':''}>${groupId.trim()?'扩展关联组':'创建关联组'}</button> <button type="button" data-pc="advisor-links-close" ${busy?'disabled':''}>关闭</button></form></section>`;
    },
    click(event){
      const action=event.target.closest('[data-pc]')?.dataset.pc;
      if(action==='advisor-links-open')void open();
      if(action==='advisor-links-close'&&!busy){reset();onChange();}
    },
    input(event){if(event.target.closest('#pc-advisor-links')&&event.target.name==='group_id'){
      groupId=event.target.value;message='';
      const form=event.target.form,button=form.querySelector('button[type=submit]');
      button.disabled=busy||!!result||!!validation();button.textContent=groupId.trim()?'扩展关联组':'创建关联组';
      form.querySelector('[role=status]').textContent=validation();
    }},
    change(event){if(event.target.closest('#pc-advisor-links')&&event.target.name==='advisor_user'&&!busy&&!result){
      selected=[...event.target.form.querySelectorAll('input[name=advisor_user]:checked')].map(v=>Number(v.value));message='';onChange();
    }},
    async submit(event){
      if(event.target.id!=='pc-advisor-links')return false;
      event.preventDefault();if(busy||result)return true;
      let payload;try{payload=advisorLinkPayload(selected,groupId,users,roles);}catch(e){message=e.message;onChange();return true;}
      busy=true;message='';const stamp=revision;onChange();
      try{const data=await client.create(payload);if(stamp===revision)result=data;}
      catch(e){if(stamp===revision)message=e.message;}
      finally{if(stamp===revision){busy=false;onChange();}}
      return true;
    },
  };
}
