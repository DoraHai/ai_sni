export const nordDefaults=Object.freeze({module:'seo',tenant_id:1,scope_id:1,platform:'wechat-article',label:'诺德首条执行电脑（本机）',expires_in_seconds:600,timezone:'Asia/Shanghai',daily_limit:1,min_interval_seconds:3600,windows:[{start:0,end:1440}]});
export function readNordIdentity(text,now=Date.now()){
  if(typeof text!=='string'||text.length>2048)throw Error('INVALID_ACCOUNT_RECEIPT');
  const v=JSON.parse(text),keys=['schema','kind','module','tenant_id','scope_id','platform','device_id','external_account_id','observed_at','human_confirmed'];
  if(Object.keys(v).length!==keys.length||Object.keys(v).some(k=>!keys.includes(k))||v.schema!==1||v.kind!=='nord-local-account-observation'||v.module!=='seo'||v.tenant_id!==1||v.scope_id!==1||v.platform!=='wechat-article'||v.human_confirmed!==true||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v.device_id)||!/^gh_[a-f0-9]{12}$/.test(v.external_account_id)||!Number.isSafeInteger(v.observed_at)||v.observed_at>now+30000||now-v.observed_at>3600000)throw Error('INVALID_ACCOUNT_RECEIPT');
  return {...v,account_id:'nord-wechat-'+v.external_account_id.slice(3)};
}
export function nordBindingMatches(binding,identity){return binding.active&&binding.device_active&&binding.module==='seo'&&binding.tenant_id===1&&binding.scope_id===1&&binding.platform==='wechat-article'&&binding.device_id===identity.device_id&&binding.account_id===identity.account_id&&binding.external_account_id===identity.external_account_id;}
