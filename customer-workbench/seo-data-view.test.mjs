import test from 'node:test';
import assert from 'node:assert/strict';
import {rankingListView,pageListView,publicationListView,dataLink} from './js/seo-data-view.mjs';

test('missing, malformed and empty lists are different, scoped totals do not use whole-site stats',()=>{
  assert.match(rankingListView(null),/尚未读取/);
  assert.match(rankingListView({items:null}),/读取结果不完整/);
  const view=rankingListView({items:[],total:0,page:1,stats:{total:99}});
  assert.match(view,/当前筛选共 0 条/);assert.doesNotMatch(view,/99/);
});
test('stale ranking is not shown as current and zero delta is retained',()=>{
  const view=rankingListView({items:[{id:1,keyword:'甲',latest_rank:2,rank_delta:3,rank_is_stale:true,last_observed_rank:2},{id:2,keyword:'乙',latest_rank:4,rank_delta:0}],total:20,page:1,engine:'baidu'});
  assert.match(view,/需要更新/);assert.match(view,/上次记录：2 名/);assert.doesNotMatch(view,/上升 3/);assert.match(view,/持平/);assert.match(view,/本页 2 条 · 当前筛选共 20 条/);
});
test('page zero score is valid, missing score is not manufactured and indexing is qualified',()=>{
  const view=pageListView({items:[{id:1,title:'甲',audit_score:0,indexable:true,status:'needs_fix'},{id:2,title:'乙',audit_score:null,indexable:null,status:'pending'}],total:2});
  assert.equal((view.match(/检查评分/g)||[]).length,1);assert.match(view,/检查评分 0/);assert.match(view,/尚未检查/);assert.match(view,/不表示搜索引擎已经收录/);
});
test('publication readback never promotes available evidence into verified or search performance',()=>{
  const view=publicationListView({items:[{content:{title:'稿件'},publication:{id:4,status:'published',public_url:'https://example.invalid/article'},page_association:{association_status:'exact_unique'},page_check:{coverage:'available'}}],total:1,coverage:{partial:true}});
  assert.match(view,/已记录发布/);assert.match(view,/已有页面检查记录/);assert.doesNotMatch(view,/页面已核验/);assert.match(view,/范围不完整/);assert.match(view,/data-publication-detail/);
});
test('external content is escaped and links allow neither scripts nor embedded credentials',()=>{
  const view=rankingListView({items:[{id:'1 onclick=alert(1)',keyword:'<img src=x onerror=alert(1)>'}],total:1});
  assert.doesNotMatch(view,/<img/);assert.doesNotMatch(view,/<button/);assert.match(view,/&lt;img/);
  for(const url of ['javascript:alert(1)','data:text/html,x','https://user:password@example.invalid','/relative'])assert.doesNotMatch(dataLink(url),/<a /);
  assert.match(dataLink('https://example.invalid/x?a=1&b=2'),/noopener noreferrer/);
});
