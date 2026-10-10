// Scoped data access. Detail and maintenance IDs must come from the latest authorized list.
export function createSeoDataClient({transport,getContext,canMaintain=()=>false}) {
  let lists=new Map();
  const fail=code=>{lists.clear();throw Object.assign(Error(code),{code});};
  const context=()=>{const c=getContext();if(!c?.connected)fail('NOT_CONNECTED');return {...c};};
  const same=c=>{const n=context();if(['tenantId','siteId','userId','revision'].some(k=>c[k]!==n[k]))fail('CONTEXT_CHANGED');};
  async function read(path,c){same(c);const r=await transport(path,{method:'GET'});same(c);if(!r.ok){lists.clear();throw Object.assign(Error('READ_FAILED'),{code:'READ_FAILED',status:r.status});}const value=await r.json();same(c);return value;}
  const paths={keywords:'keywords',pages:'site-pages',publications:'workbench/publication-page-evidence',facts:'qa/facts'};
  const allowed={keywords:['q','engine','device','status'],pages:['q','status'],publications:[],facts:[]};
  return {
    invalidate(){lists.clear();},
    async list(kind,{page=1,filters={}}={}){
      if(!Object.hasOwn(paths,kind)||!Number.isSafeInteger(page)||page<1||page>10000)fail('INVALID_PAGINATION');
      const c=context(),query=new URLSearchParams({tenant_id:c.tenantId,site_id:c.siteId});
      if(kind!=='facts'){query.set('page',page);query.set('page_size',20);}
      for(const [key,value] of Object.entries(filters)){if(!allowed[kind].includes(key))fail('QUERY_DENIED');if(value!==undefined)query.set(key,String(value));}
      lists.delete(kind);const data=await read('/api/v1/seo/'+paths[kind]+'?'+query,c),items=kind==='facts'?data:data?.items;
      if(!Array.isArray(items)||(kind!=='facts'&&(!Number.isSafeInteger(data.total)||data.total<0||data.page!==page||data.page_size!==20||items.length>20||items.length>data.total))||(kind==='facts'&&items.length>500))fail('CONTRACT_MISMATCH');
      if(kind==='publications'&&(data.tenant_id!==c.tenantId||data.site_id!==c.siteId||data.read_only!==true))fail('SCOPE_MISMATCH');
      for(const item of items){const row=kind==='publications'?item.content:item;if(!Number.isSafeInteger(row?.id)||row.id<=0||row.tenant_id!==c.tenantId||row.site_id!==c.siteId)fail('SCOPE_MISMATCH');if(kind==='publications'&&(!Number.isSafeInteger(item.publication?.id)||item.publication.id<1))fail('CONTRACT_MISMATCH');}
      lists.set(kind,{c,items,filters:{...filters}});return data;
    },
    async detail(kind,id){
      const list=lists.get(kind);if(!list||!['keywords','pages'].includes(kind)||!list.items.some(v=>v.id===id))fail('SELECTION_REQUIRED');same(list.c);
      const query=new URLSearchParams({tenant_id:list.c.tenantId});
      if(kind==='keywords'){query.set('engine',list.filters.engine||'baidu');query.set('device',list.filters.device||'desktop');query.set('region','全国');query.set('days','90');}
      const data=await read(`/api/v1/seo/${kind==='keywords'?'keywords':'site-pages'}/${id}${kind==='pages'?'/detail':''}?${query}`,list.c),row=kind==='keywords'?data.keyword:data.page;
      if(row?.id!==id||row.tenant_id!==list.c.tenantId||row.site_id!==list.c.siteId)fail('SCOPE_MISMATCH');return data;
    },
    selected(kind,id){const list=lists.get(kind);if(!list)fail('SELECTION_REQUIRED');same(list.c);const row=list.items.find(v=>v.id===id);if(!row)fail('SELECTION_REQUIRED');return structuredClone(row);},
    async removeKeyword(id){
      if(!canMaintain('keywords'))fail('ADVISOR_REQUIRED');
      this.selected('keywords',id);const c=context();lists.clear();
      const query=new URLSearchParams({tenant_id:c.tenantId,site_id:c.siteId});
      let r;try{r=await transport(`/api/v1/seo/keywords/${id}?${query}`,{method:'DELETE'});}catch(e){if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;fail('DELETE_OUTCOME_UNKNOWN');}
      same(c);
      if(r.status>=500||r.status===408)fail('DELETE_OUTCOME_UNKNOWN');
      if(!r.ok)throw Object.assign(Error('DELETE_FAILED'),{code:'DELETE_FAILED',status:r.status});
      let value;try{value=await r.json();}catch(e){if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;fail('DELETE_OUTCOME_UNKNOWN');}same(c);
      if(value?.deleted!==true||value.keyword_id!==id)fail('DELETE_OUTCOME_UNKNOWN');
      return value;
    },
    async save(kind,input){
      if(!['facts','keywords'].includes(kind)||!canMaintain(kind))fail('ADVISOR_REQUIRED');
      const c=context();let body,method,path;
      const safeUrl=value=>{if(!value)return null;let url;try{url=new URL(value);}catch{fail('INVALID_MAINTENANCE_INPUT');}if(!['http:','https:'].includes(url.protocol)||url.username||url.password)fail('INVALID_MAINTENANCE_INPUT');return url.href;};
      if(kind==='facts'){
        if(!input.title?.trim()||!input.statement?.trim()||!input.source_name?.trim()||!['active','retired'].includes(input.status))fail('INVALID_MAINTENANCE_INPUT');
        if(input.id!=null){const row=this.selected(kind,input.id);if(row.version!==input.version)fail('CONTENT_VERSION_OR_SCOPE_MISMATCH');}
        if(input.expires_at&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/i.test(input.expires_at))fail('INVALID_MAINTENANCE_INPUT');
        body={tenant_id:c.tenantId,site_id:c.siteId,title:input.title.trim(),statement:input.statement.trim(),source_name:input.source_name.trim(),source_url:safeUrl(input.source_url),expires_at:input.expires_at||null,status:input.status,...(input.id?{version:input.version}:{})};
        method=input.id?'PATCH':'POST';path='/api/v1/seo/qa/facts'+(input.id?'/'+input.id:'');
      }else{
        if(input.id)this.selected(kind,input.id);else if(!input.keyword?.trim())fail('INVALID_MAINTENANCE_INPUT');if(!['P0','P1','P2','P3'].includes(input.priority))fail('INVALID_MAINTENANCE_INPUT');body={priority:input.priority,landing_page:safeUrl(input.landing_page)};if(input.id){method='PATCH';path=`/api/v1/seo/keywords/${input.id}?tenant_id=${c.tenantId}`;}else{method='POST';path='/api/v1/seo/keywords';body={...body,tenant_id:c.tenantId,site_id:c.siteId,keyword:input.keyword.trim()};}
      }
      let r;try{r=await transport(path,{method,body:JSON.stringify(body)});}catch(e){lists.clear();if(['AUTH_EXPIRED','PERMISSION_DENIED','CONTEXT_CHANGED'].includes(e.code))throw e;fail('WRITE_OUTCOME_UNKNOWN');}
      same(c);if(!r.ok){lists.clear();let value;try{value=await r.json();}catch{}throw Object.assign(Error('WRITE_FAILED'),{code:value?.detail?.code||'WRITE_FAILED',status:r.status});}
      const value=await r.json();same(c);lists.clear();if(value.tenant_id!==c.tenantId||value.site_id!==c.siteId||!Number.isSafeInteger(value.id)||(input.id&&value.id!==input.id))fail('CONTRACT_MISMATCH');return value;
    },
  };
}
