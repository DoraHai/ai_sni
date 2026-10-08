// UI-02: consumes the host's authenticated, authorized GET-only transport.
// Not mounted in the demo. No credentials, role authorization or business writes here.
export function createSeoContentReader({transport,getContext}) {
  if (typeof transport !== 'function' || typeof getContext !== 'function') throw Error('HOST_REQUIRED');
  const verified = new Map();
  function scope() {
    const context = getContext();
    if (!context || !Number.isSafeInteger(context.tenantId) || context.tenantId <= 0 || !Number.isSafeInteger(context.siteId) || context.siteId <= 0 || context.revision == null) throw Error('SCOPE_REQUIRED');
    return {...context};
  }
  function same(context) {
    const now = scope();
    if (now.revision !== context.revision || now.tenantId !== context.tenantId || now.siteId !== context.siteId) { verified.clear(); throw Error('CONTEXT_CHANGED'); }
  }
  async function read(path,context) {
    same(context);
    const response = await transport(path,{method:'GET',cache:'no-store'});
    same(context);
    if (!response.ok) { verified.clear(); const error = Error(response.status === 401 ? 'AUTH_EXPIRED' : response.status === 403 ? 'PERMISSION_DENIED' : 'READ_FAILED'); error.status=response.status; throw error; }
    const data = await response.json(); same(context); return data;
  }
  return {
    invalidate() {verified.clear();},
    async contents({page=1,pageSize=50,q='',status=''}={}) {
      if(!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(pageSize)||pageSize<1||pageSize>200)throw Error('INVALID_PAGINATION');
      const context=scope(); verified.clear();
      const query=new URLSearchParams({tenant_id:String(context.tenantId),site_id:String(context.siteId),page:String(page),page_size:String(pageSize)});
      if(typeof q!=='string'||q.length>200||typeof status!=='string')throw Error('INVALID_FILTER');if(q.trim())query.set('q',q.trim());if(status)query.set('status',status);
      const data=await read('/api/v1/seo/content-assets?'+query,context);
      if (!data || !Array.isArray(data.items) || !Number.isSafeInteger(data.total) || data.total<0 || data.page!==page || data.page_size!==pageSize || data.items.length>pageSize || data.items.length>data.total) throw Error('CONTRACT_MISMATCH');
      for(const item of data.items) {
        if (!Number.isSafeInteger(item.id) || item.id<=0 || item.tenant_id!==context.tenantId || item.site_id!==context.siteId) {verified.clear();throw Error('SCOPE_MISMATCH');}
      }
      for(const item of data.items) verified.set(item.id,context);
      return data;
    },
    async reviewHistory(contentId) {
      const context=verified.get(contentId);
      if (!context) throw Error('CONTENT_NOT_VERIFIED');
      same(context);
      // Backend accepts tenant scope; site ownership was verified via contents.
      return read(`/api/v1/seo/content-assets/${contentId}/review-history?tenant_id=${context.tenantId}`,context);
    },
  };
}
