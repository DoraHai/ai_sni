// Uses the verified GEO host. Never accepts a key, origin or caller-selected scope.
const positive=n=>Number.isSafeInteger(n)&&n>0;
const fail=(message,code)=>Object.assign(Error(message),{code});
export const visibilityAdvisor=user=>user?.tenant_id===null&&user?.permissions?.['settings.accounts']==='edit'&&user?.permissions?.['settings.customers']==='edit'||
  ['geo.assets','geo.content'].every(k=>user?.permissions?.[k]==='edit');
export const visibilityServiceHelp='平台的搜索服务还没接通，需要超管联系技术人员在服务器上配置搜索服务。';
export function visibilityNotEnabled({advisor=false,admin=false,enabled}={}){
  if(!advisor)return '这项检查还没开始。开通后，这里每周会显示你的品牌在 DeepSeek 搜索里能不能被找到。想开通请联系你的顾问。';
  const setup='点击本块右上方「项目设置」，打开「每周核对这个项目」并点击「保存项目设置」。';
  const service=admin?visibilityServiceHelp:'平台的搜索服务还没接通，需要超管处理，请联系超管。';
  if(enabled===true)return '项目已开启，但'+service;
  if(enabled===false)return '还没开启。'+setup+'搜索服务接通后，每周一北京时间早上 6 点会自动检查一次。';
  return '这项检查还没开始。'+setup+'若已经开启，'+service;
}
export function visibilityConfig(input){
  const list=(name,max)=>{
    const values=Array.isArray(input[name])?input[name]:String(input[name]||'').split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(values.some(v=>typeof v!=='string'))throw fail('请每行填写一条文字或链接。');
    if(values.length>max)throw fail(`最多填写 ${max} 条，请精简后保存。`);
    return [...new Set(values)];
  };
  const config={enabled:input.enabled===true,customer_visible:input.customer_visible===true,
    domains:list('domains',3),zh_url:String(input.zh_url||'').trim(),brand_terms:list('brand_terms',5),
    core_terms:list('core_terms',20),extra_article_urls:list('extra_article_urls',20)};
  if([...config.brand_terms,...config.core_terms].some(v=>!v.trim()||v.length>128||/[\x00-\x1f]/.test(v)))throw fail('每个搜索词最多 128 字，不能包含换行或空白词。');
  if(config.domains.some(v=>v.length>123||! /^[^\s/:?#@]+\.[^\s/:?#@]+$/.test(v)))throw fail('网站域名不带协议或路径，例如 example.com。');
  for(const value of [config.zh_url,...config.extra_article_urls].filter(Boolean)){
    let url;try{url=new URL(value);}catch{throw fail('请填写完整的网页链接，以 http:// 或 https:// 开头。');}
    if(value.length>2048||!['http:','https:'].includes(url.protocol)||url.username||url.password)throw fail('请填写公开网页链接，不要在链接中填写账号或密码。');
  }
  return config;
}
export function createSearchVisibilityClient({transport,getContext,getNotEnabledMessage=()=>visibilityNotEnabled()}){
  const context=()=>{const c=getContext();if(!c?.connected||!positive(c.tenantId)||!positive(c.projectId))throw fail('请先选择并核验 GEO 项目。','CONTEXT_CHANGED');return {...c};};
  const stamp=c=>JSON.stringify([c.tenantId,c.projectId,c.userId,c.revision]);
  async function request(suffix='',method='GET',body,download=false){
    const c=context(),key=stamp(c);
    const current=()=>{if(stamp(context())!==key)throw fail('项目或身份已变化，旧结果已清除。','CONTEXT_CHANGED');};
    let response;
    try{response=await transport(`/api/v1/geo/projects/${c.projectId}/search-visibility${suffix}?tenant_id=${c.tenantId}`,{method,...(body===undefined?{}:{body:JSON.stringify(body)})});}
    catch(e){current();if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;
      throw fail(method==='GET'?'暂时无法读取，请稍后刷新。':'提交结果暂时无法确认，请先刷新核对；系统不会重复提交。','OUTCOME_UNKNOWN');}
    current();
    if(download&&response.ok&&response.headers?.get('content-type')?.startsWith('text/csv')){
      const bytes=await response.arrayBuffer();current();return new Blob([bytes],{type:'text/csv;charset=utf-8'});
    }
    let data;try{data=await response.json();}catch{current();throw fail('读取结果格式不完整，请稍后刷新。');}
    current();
    if(!response.ok){
      const detail=typeof data?.detail==='string'?data.detail:'';
      throw fail(response.status===404?(suffix.startsWith('/runs/')?'本次检查记录不存在，请刷新后重新选择。':getNotEnabledMessage()):response.status===422?'设置未通过校验，请检查填写数量、词长度和网页链接。':
        response.status===409?detail||'已有任务在运行或今天已运行，请刷新核对。':'暂时无法完成，请联系顾问核对权限或服务状态。');
    }
    if(download)throw fail(data?.state==='not_open'?'暂未开放':getNotEnabledMessage());
    return data;
  }
  const id=value=>{if(!positive(value))throw fail('请选择有效的检查记录。');return value;};
  const validJob=job=>job===null||positive(job?.id)&&['pending','running','succeeded','failed'].includes(job.status)&&
    job.result&&Array.isArray(job.result.items)&&job.result.summary&&typeof job.result.summary==='object'&&
    job.result.items.every(item=>item&&typeof item==='object'&&(!['brand','core','index'].includes(item.kind)||Array.isArray(item.results)));
  return {
    async overview(){const data=await request();if(!['ready','not_open','not_enabled'].includes(data?.state)||data.state==='ready'&&(!Array.isArray(data.weeks)||data.weeks.length>12||!validJob(data.latest)))throw fail('读取结果格式不完整，请稍后刷新。');return data;},
    config:()=>request('/config'),save:input=>request('/config','PUT',visibilityConfig(input)),
    run:()=>request('/run','POST'),detail:jobId=>request('/runs/'+id(jobId)),
    csv:jobId=>request('/runs/'+id(jobId)+'/csv','GET',undefined,true),
  };
}
