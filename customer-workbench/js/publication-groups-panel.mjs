import {createPublicationGroupsClient, publicationContextKey, publicationGroupKey, publicationDetailKey, appendUnique} from './publication-groups-client.mjs';
import {escapeText as esc, formatTime, statusLabel} from './customer-display.mjs';
import {geoSafeLink} from './geo-project-view.mjs';
export function publicationLink(value) {
  return geoSafeLink(value);
}
const button = (action, label, extra = '', disabled = false) => `<button type="button" data-publication="${action}" ${extra} ${disabled ? 'disabled' : ''}>${label}</button>`;
const resultLabel = result => ({success:'操作人报告成功', failed:'操作人报告失败', pending_review:'操作人报告待复核', unknown:'操作人报告结果未知'}[result] || '操作人报告结果未知');
export function publicationDetailView(row) {
  const external = row.source === 'external';
  return `<article class="publication-source"><b>${external ? '外部回传' : '系统原生'}</b> · ${esc(row.channel || '渠道未提供')}<p>${external ? esc(resultLabel(row.status)) + ' · 正文暂不可核验' : esc(statusLabel(row.status, 'publication')) + ' · 核验状态：' + esc(row.verification?.status || '未提供')}</p><p>${row.group_article_id == null ? esc(row.title || '未提供报告标题') : `关联 v${esc(row.article_version_no ?? '未提供')}${row.current_version_no && row.current_version_no !== row.article_version_no ? `；当前 v${esc(row.current_version_no)}` : ''}`}${row.article_version_id ? ` · 母稿版本记录 #${esc(row.article_version_id)}` : ''}</p><p class="publication-url">${publicationLink(row.url)}</p><small>${external ? `报告时间 ${esc(formatTime(row.reported_at))} · 收到时间 ${esc(formatTime(row.received_at))}` : `发布/登记时间 ${esc(formatTime(row.published_at))}`}</small></article>`;
}
const blank = () => ({items:[], page:null, loading:false, error:null});
export function createPublicationGroupsPanel({module, host}) {
  const client = createPublicationGroupsClient({module, transport:host.transport, getContext:host.getContext});
  let node = null, binding = null, articleId = null, generation = 0, linked = blank(), unlinked = blank(), details = new Map(), source = 'all', disposed = false;
  function reset() { generation++; client.invalidate(); binding = null; linked = blank(); unlinked = blank(); details.clear(); source = 'all'; if (node) node.replaceChildren(); }
  const current = stamp => !disposed && stamp === generation && binding === publicationContextKey(module, host.getContext());
  function paint() {
    if (!node) return;
    if (!binding || binding !== publicationContextKey(module, host.getContext())) { node.innerHTML = '<p>请选择有权限的客户与网站/项目后查看发布记录。</p>'; return; }
    const page = linked.page, counts = page?.counts;
    const slotView = (slot, detail = false) => `${slot.error ? `<p role="alert">${slot.error === 'PUBLICATION_REFRESH_REQUIRED' ? '记录、权限或分页已变化，请刷新后重新读取。' : '发布记录读取不完整，请重新读取；外部回传数尚未确认。'}</p>${button('refresh','刷新发布记录')}` : ''}${slot.loading ? '<p role="status">正在读取发布记录…</p>' : ''}${slot.page && !slot.items.length ? '<p>当前范围暂无可见记录。</p>' : ''}${detail ? slot.items.filter(r => source === 'all' || r.source === source).map(publicationDetailView).join('') : ''}`;
    const detailView = (id, slot) => `${slotView(slot, true)}<p>该文章已加载 ${slot.items.length} 条；当前来源可见 ${slot.items.filter(r => source === 'all' || r.source === source).length} 条。</p>${slot.page?.has_more ? button('detail-more','继续加载该文章明细',`data-article="${id}"`,slot.loading) : ''}`;
    const groups = articleId ? detailView(articleId,linked) : linked.items.map(row => {
      const slot = details.get(row.group_article_id);
      return `<section class="publication-group">${button('expand',`${slot ? '收起' : '展开'} #${row.group_article_id} ${esc(row.title)}`,`data-article="${row.group_article_id}" aria-expanded="${!!slot}"`)}<p>系统 ${row.native_count} 条 / 外部回传 ${row.external_count} 条</p>${slot ? detailView(row.group_article_id,slot) : ''}</section>`;
    }).join('');
    node.innerHTML = `<section class="publication-groups" aria-label="按文章查看发布记录"><h2>${articleId ? '本稿件发布记录' : '按文章查看发布记录'}</h2><p>仅展示当前授权范围内可见记录；外部报告不改变原生发布、核验或报表指标。</p>${button('refresh','刷新发布记录')}<div class="publication-counts">${counts ? `范围内原生记录 ${counts.native_records} 条 · 外部回传 ${counts.external_records} 条 · 有记录文章 ${counts.article_groups} 篇` : '范围统计尚未取得'}</div><label>明细来源 <select data-publication-source>${[['all','全部来源'],['native','系统原生'],['external','外部回传']].map(([key,label])=>`<option value="${key}" ${source===key?'selected':''}>${label}</option>`).join('')}</select></label>${articleId ? '' : slotView(linked)}${groups}${!articleId ? `<p>已加载 ${linked.items.length} 篇；范围统计不随来源筛选变化。</p>${linked.page?.has_more ? button('groups-more','继续加载文章','',linked.loading) : ''}<section class="publication-unlinked"><h3>待关联${unlinked.page ? `（范围内 ${unlinked.page.counts.unlinked_records} 条）` : ''}</h3><p>当前客户及网站/项目内尚未选择稿件的外部回传。未选网站/项目的记录不在此范围。</p>${slotView(unlinked)}${unlinked.items.map(publicationDetailView).join('')}<p>已加载 ${unlinked.items.length} 条。</p>${unlinked.page?.has_more ? button('unlinked-more','继续加载待关联','',unlinked.loading) : ''}</section>` : ''}</section>`;
  }
  async function load(slot, params, more = false) {
    if (slot.loading || more && !slot.page?.has_more) return;
    const stamp = generation, cursor = more ? slot.page.next_cursor : null;
    slot.loading = true; slot.error = null; paint();
    try {
      const value = await client.read({...params, ...(cursor ? {cursor} : {})});
      if (!current(stamp)) return;
      if (more && value.has_more && value.next_cursor === cursor) throw Object.assign(Error(),{code:'PUBLICATION_REFRESH_REQUIRED'});
      slot.items = appendUnique(more ? slot.items : [], value.items, params.article_id != null || params.bucket === 'unlinked' ? row => publicationDetailKey(module,row) : row => publicationGroupKey(module,host.getContext(),row.group_article_id));
      slot.page = value;
    } catch (e) {
      if (!current(stamp)) return;
      if (['PUBLICATION_REFRESH_REQUIRED','PUBLICATION_RESPONSE_INVALID'].includes(e.code) || [401,403].includes(e.status)) {
        generation++; client.invalidate(); linked = blank(); unlinked = blank(); details.clear(); linked.error = e.code; 
      } else slot.error = e.code || 'PUBLICATION_READ_FAILED';
    } finally { slot.loading = false; if (!disposed) paint(); }
  }
  async function refresh() {
    const key = publicationContextKey(module,host.getContext());
    reset(); binding = key; paint();
    if (!host.getContext()?.connected) return;
    await Promise.allSettled([load(linked,{bucket:'linked',...(articleId ? {article_id:articleId} : {})}),...(!articleId ? [load(unlinked,{bucket:'unlinked'})] : [])]);
  }
  async function click(event) {
    const el = event.target.closest('[data-publication]'); if (!el || el.disabled) return;
    const action = el.dataset.publication, id = Number(el.dataset.article);
    if (action === 'refresh') await refresh();
    if (action === 'groups-more') await load(linked,{bucket:'linked'},true);
    if (action === 'unlinked-more') await load(unlinked,{bucket:'unlinked'},true);
    if (action === 'expand') {
      if (details.has(id)) { details.delete(id); paint(); }
      else { const slot = blank(); details.set(id,slot); await load(slot,{bucket:'linked',article_id:id}); }
    }
    if (action === 'detail-more') await load(articleId ? linked : details.get(id),{bucket:'linked',article_id:id},true);
  }
  const document = globalThis.document;
  const onVisible = () => { if (node?.isConnected && document.visibilityState === 'visible') void refresh(); };
  document?.addEventListener('visibilitychange',onVisible);
  return {
    reset, refresh,
    renderInto(element, id = null) {
      node = element;
      node.onclick = click;
      node.onchange = event => { if (event.target.matches('[data-publication-source]')) { source = event.target.value; paint(); } };
      if (binding !== publicationContextKey(module,host.getContext()) || articleId !== id) { articleId = id; void refresh(); } else paint();
    },
    dispose() { disposed = true; document?.removeEventListener('visibilitychange',onVisible); reset(); node = null; },
  };
}
