import {formatTime} from './customer-display.mjs';
import {isAdvisorRole} from '../../frontend/src/views/settings/advisorTenants.mjs';
export function platformTime(value){
  if(!value)return '暂无记录';
  const stamp=typeof value==='string'&&/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)?value+'Z':value;
  const text=formatTime(stamp);
  return text+(/时区未提供|时间待核对|时间未提供/.test(text)?'':'（北京时间）');
}
export function moduleAvailability(source,code,date){
  if(source.state!=='available')return '待接入';
  const count=source.rows.filter(m=>m.module_code===code&&['active','trial'].includes(m.status)&&(!m.expires_at||m.expires_at>=date)).length;
  return (source.truncated?'当前清单 ':'')+count;
}
export function accountScope(user,roles,tenant){
  const advisor=typeof user.is_advisor==='boolean'?user.is_advisor:isAdvisorRole(roles.find(r=>r.id===user.role_id));
  if(advisor){
    if(!Array.isArray(user.tenant_ids))return '授权范围未完整读取'+(user.tenant_id==null?'':' · 默认客户：'+tenant(user.tenant_id));
    if(!user.tenant_ids.length)return '未分配客户';
    return user.tenant_ids.map(tenant).join('、')+'（默认：'+tenant(user.default_tenant_id??user.tenant_id)+'）';
  }
  return user.tenant_id==null?'全局范围 · 受角色权限控制':tenant(user.tenant_id);
}
export function controlConfirmation(form){
  const kind=form.dataset.controlKind,f=form.elements;
  if(kind==='provider'&&f.enabled.value==='false')return '确认停用服务商 '+f.host.value+'？该服务商相关接口的后续请求将被停用。';
  if(kind==='credential'&&f.mode.value==='restore')return '确认恢复 '+f.binding.selectedOptions[0].textContent+' 的服务器原密钥？当前管理密钥将被移除，影响同一密钥绑定的全部服务。';
  if(kind==='connection'){
    const label=f.connection_id.selectedOptions[0].textContent;
    if(f.connection_mode.value==='restore')return '确认恢复 '+label+' 的服务器原配置？将移除当前管理参数与密钥覆盖，后续请求和任务使用服务器配置。';
    const cleared=[...form.querySelectorAll('[data-connection-clear]:checked')].map(i=>i.dataset.connectionClear);
    const disabled=[...form.querySelectorAll('[data-connection-param]')].some(i=>i.tagName==='SELECT'&&i.value==='false');
    if(cleared.length||disabled)return '确认修改 '+label+' 的平台默认配置？'+(disabled?'将停用平台默认接口。':'')+(cleared.length?'将清除密钥字段：'+cleared.join('、')+'。':'')+'影响后续请求和任务。';
  }
  return '';
}
