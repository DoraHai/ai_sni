// All records are synthetic. GEO task 88 is deliberately different from version ID 900.
export const receiptId = n => `00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export function publicationPage(module = 'seo', params = {}, context = {}) {
  const tenant = context.tenantId ?? 1, scope = (module === 'seo' ? context.siteId : context.projectId) ?? (module === 'seo' ? 9 : 10);
  const bucket = params.bucket ?? 'linked', id = params.article_id ?? null;
  const row = (source, n) => ({source,group_article_id:id,content_id:module==='seo'?id:null,task_id:module==='geo'?id:null,native_publication_id:source==='native'?n:null,external_receipt_id:source==='external'?receiptId(n):null,article_version_id:module==='geo'&&source==='native'?900:null,article_version_no:n===2?2:3,current_version_no:3,channel:source==='native'?'官网':'公众号',url:'https://example.com/article?mid=1&idx=2',status:source==='native'?'published':n===2?'failed':'success',verification:source==='native'?{status:'待页面核验'}:null,published_at:'2026-10-23T01:00:00Z',reported_at:'2026-10-23T01:10:00Z',received_at:'2026-10-23T01:11:00Z'});
  return {
    schema:'publication-groups.v1',read_only:true,context:{module,tenant_id:tenant,scope_id:scope,bucket,article_id:id},
    items:bucket==='unlinked'?[{...row('external',8),group_article_id:null,title:'示例客户甲待关联回传'}]:id?[row('native',1),row('native',2),row('external',1),row('external',2)]:[{group_article_id:88,title:'示例客户甲 · 文章选型说明',native_count:2,external_count:2},{group_article_id:89,title:'示例客户甲 · 文章选型说明',native_count:0,external_count:1}],
    counts:{native_records:2,external_records:4,article_groups:2,unlinked_records:1},next_cursor:null,has_more:false,completeness:{complete:true},
  };
}
