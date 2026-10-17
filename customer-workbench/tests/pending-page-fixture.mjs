// Synthetic identities/counts, matching the recorded production response shapes.
// Evidence: ui-deploy/verification-failure.json and ui-review/text/platform-*-1440.txt.
export const pendingAdmin={id:7,username:'fixture-admin',display_name:'本地预览管理员',tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}};
const source=rows=>({state:'available',total:rows.length,rows,truncated:false});
export function pendingSnapshot(){
 const sources=Object.fromEntries(['tenants','users','roles','tenant_modules','seo_sites','geo_projects','api_audit_logs','geo_tracking_engines','sem_tasks','seo_tasks','geo_async_jobs','geo_action_tickets','baidu_oauth_grants'].map(k=>[k,source([])]));
 sources.tenants=source(Array.from({length:15},(_,i)=>({id:i+1,name:`本地示例客户 ${i+1}`,industry:'制造业'})));
 sources.users=source([pendingAdmin]);
 return {schema:1,mode:'read_only_inventory',generated_at:'2026-10-17T08:44:41Z',sources,
  calls:{total:45123,failed:35730,average_latency_ms:90},costs:{actual_amount:null,estimated_amount:null,date:'2026-10-17',usage:[],note:'费用待核对'},
  coverage:{api:'已有调用台账',backup:'备份结果未接入',audit:'管理操作审计等待启用，账号最近登录仍可查看。'},alerts:[{id:'fixture-alert',tenant_id:null,message:'本地示例：接口异常待核对',severity:'error'}],
  controls:{state:'schema_pending',connections:[{id:'sem.deepseek',module:'sem',label:'DeepSeek 官方',registered:false,supported:true,revision:0,parameters:{},fields:[],secret_fields:[]}],module_status:[]},
  operations:{state:'schema_pending',suppliers:[],provider_health:[],call_monitor:{state:'schema_pending'}}};
}
export function pendingGovernance(){
 return {schema:1,state:'available',modules:['sem','seo','geo'].map(module=>({module,provider:module==='sem'?'api.deepseek.com':null,model:module==='sem'?'deepseek-chat':null,configured:module==='sem'?true:null,
  metering:{state:module==='sem'?'recording':module==='seo'?'observed':'available_no_recent_events'},calls:{failed:module==='sem'?35515:0,unknown:module==='sem'?1:0,source:'api_usage_events',window:{kind:'last_24_hours'}},
  // controls absent -> management schema and runtime protection show unknown.
  limits:[{kind:'calls',state:'unavailable'},{kind:'budget',state:'schema_pending'},{kind:'scope',state:'schema_pending'}]}))};
}
export const availableHealth=module=>({schema:1,module,scope:{kind:'global',tenant_id:null},as_of:'2026-10-17T08:44:41Z',state:'available',counts:{projects:0,runs:0,pending_human:0,unknown_cost:0},rows:[],truncated:false});
