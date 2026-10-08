// Entry availability is presentation only. The independent app rechecks access.
export function customerWorkbenchHref({ready,token,demo,tenantId,siteId,modules,sites}) {
  if (!ready || !token || demo || !Number.isSafeInteger(tenantId) || tenantId < 1
    || !Number.isSafeInteger(siteId) || siteId < 1
    || !modules?.some(item=>item.module_code==='seo')
    || !sites?.some(site=>site.id===siteId && site.status==='active')) return null;
  return '/customer-workbench/?'+new URLSearchParams({tenant_id:tenantId,site_id:siteId});
}

export async function probeCustomerWorkbench({fetchImpl=globalThis.fetch,signal}={}) {
  try {
    const response=await fetchImpl('/customer-workbench/',{
      method:'GET',credentials:'omit',cache:'no-store',redirect:'error',signal,
      headers:{Accept:'text/html'},
    });
    if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) return false;
    const html=await response.text();
    return html.length<8192 && html.includes('<title>客户工作台</title>')
      && html.includes('src="./app.js"') && html.includes('href="./app.css"');
  } catch { return false; }
}
