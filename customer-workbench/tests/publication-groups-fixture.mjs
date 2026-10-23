// Synthetic HTTP DTOs aligned to SEO 158e52cb and GEO 388da53d handoffs.
// GEO task 88 is deliberately different from master-version row ID 900.
export const receiptId = n => `00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export function completePublicationPage(value) {
  if(value.context.module==='seo') value.counts.loaded=value.items.length;
  else {value.counts.loaded_items=value.items.length;value.completeness.pagination_complete=!value.has_more;}
  return value;
}
export function publicationPage(module = 'seo', params = {}, context = {}) {
  const tenant = context.tenantId ?? 1, scope = (module === 'seo' ? context.siteId : context.projectId) ?? (module === 'seo' ? 9 : 10);
  const bucket = params.bucket ?? 'linked', id = params.article_id ?? null;
  const identity = article => ({...(module==='seo'?{module,tenant_id:tenant,scope_id:scope}:{}),group_article_id:article,content_id:module==='seo'?article:null,task_id:module==='geo'?article:null});
  const row = (source, n) => ({...identity(id),source,native_publication_id:source==='native'?n:null,external_receipt_id:source==='external_report'?receiptId(n):null,article_version_id:module==='geo'&&source==='native'?900:null,article_version_no:id==null?null:n===2?2:3,...(module==='geo'?{current_version_no:id==null?null:3}:{}),channel:source==='native'?'官网':'公众号',url:'https://example.com/article?mid=1&idx=2',status:source==='native'?'published':n===2?'failed':'success',verification:module==='seo'?(source==='native'?'see_native_evidence':id==null?'unlinked':'unavailable'):{status:source==='native'?'see_native_evidence':'unavailable',evidence_valid:false},published_at:'2026-10-23T01:00:00Z',reported_at:'2026-10-23T01:10:00Z',received_at:'2026-10-23T01:11:00Z'});
  return completePublicationPage({
    schema:1,read_only:true,context:{module,tenant_id:tenant,scope_id:scope,bucket,article_id:id,...(module==='seo'?{revision:'synthetic-scope-revision-1'}:{audience:'client'})},
    items:bucket==='unlinked'?[{...row('external_report',8),title:'示例客户甲待关联回传'}]:id?[row('native',1),row('native',2),row('external_report',1),row('external_report',2)]:[{...identity(88),title:'示例客户甲 · 文章选型说明',current_version_no:3,native_count:2,external_count:2,details_loaded:false},{...identity(89),title:'示例客户甲 · 文章选型说明',current_version_no:3,native_count:0,external_count:1,details_loaded:false}],
    counts:module==='seo'?{native:2,external:4,articles:2,unlinked:1}:{native_records:2,external_records:4,article_groups:2,unlinked_records:1},next_cursor:null,has_more:false,completeness:module==='seo'?'complete_snapshot':{complete:true,visibility:'visible_current_master',pagination_complete:true,revision:'synthetic-scope-revision-1'},
  });
}
