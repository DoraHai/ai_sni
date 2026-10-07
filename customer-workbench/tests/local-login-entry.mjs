// Local integration host only. No fixture identities, tokens or business responses.
import {session} from '@existing-host/session';
const form=document.querySelector('form'),message=document.querySelector('[role="status"]');
document.querySelector('#local-logout').onclick=()=>{session.logout();message.textContent='已清空原会话，请登录合成账号。';};
form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button');button.disabled=true;message.textContent='正在向本机后端登录…';
  try{
    const path=new URLSearchParams(location.search).get('redirect');
    if(!path||!/^\/customer-workbench\/\?tenant_id=[1-9]\d*&site_id=[1-9]\d*$/.test(path))throw Error('缺少准确的本机客户/站点返回路径');
    const response=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value}),credentials:'omit',redirect:'error'});
    if(!response.ok)throw Error(`本机登录失败 HTTP ${response.status}`);
    const {token,user}=await response.json();session.setAuth(token,user,false);
    form.elements.password.value='';
    const tenants=await fetch('/api/v1/auth/tenants',{headers:{Authorization:`Bearer ${session.token}`},credentials:'omit',redirect:'error'});
    if(!tenants.ok)throw Error(`本机客户列表失败 HTTP ${tenants.status}`);
    session.setTenants((await tenants.json()).tenants);
    location.assign(path);
  }catch(error){message.textContent=error.message;}finally{button.disabled=false;}
};
