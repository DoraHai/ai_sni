import test from 'node:test';import assert from 'node:assert/strict';
import {createDistributionClient} from './js/distribution-client.mjs';
import {distributionExecutionMarkup} from './js/distribution-panel.mjs';
const scope={module:'seo',tenant_id:15,scope_id:6};
const row=id=>({platform_id:id,label:id==='news-source'?'新闻源接口发布':'外链接口发布',content_types:['article'],v1_platform:null,native_intake:false,automatic_publish:false,real_channel_verified:false,status:'not-integrated',missing:['尚未选择供应商'],execution_type:'server-api',configured:false,adapter_verified:false});
const client=items=>createDistributionClient({session:{token:'synthetic',user:{id:7,tenant_id:15,permissions:{'seo.site':'edit','seo.content':'edit'}}},fetchImpl:async()=>({ok:true,status:200,json:async()=>({schema:1,...scope,items})})});
test('unconfigured server API channels are visible without device or publication permission',async()=>{
 const c=client([row('news-source'),row('backlink')]);const v=(await c.platformDirectory(scope)).items;
 const html=distributionExecutionMarkup(v,null,[],true);assert.match(html,/新闻源接口发布/);assert.match(html,/外链接口发布/);assert.match(html,/服务器 API/);assert.match(html,/尚未选择供应商/);assert.doesNotMatch(html,/data-distribution="publish"/);c.dispose();
});
test('server API descriptions cannot become a device capability or claim verification',async()=>{
 for(const change of [{v1_platform:'wechat-article'},{native_intake:true},{configured:true},{adapter_verified:true},{automatic_publish:true},{real_channel_verified:true}]){
  const c=client([{...row('news-source'),...change}]);await assert.rejects(c.platformDirectory(scope),{code:'CONTRACT_MISMATCH'});c.dispose();
 }
});
