import test from 'node:test';
import assert from 'node:assert/strict';
import {validateDistributionPlans,createDistributionClient} from './js/distribution-client.mjs';
import {distributionPlanningMarkup} from './js/distribution-panel.mjs';
const scope={module:'seo',tenant_id:4,scope_id:19},id='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const data=()=>({schema:1,...scope,automated_publish:false,items:[{id,queue_id:id,binding_id:id,draft_version:'draft_1',source_revision:'rev_1',planned_at:1,checked_at:1,basis:'rules',state:'planned',reason:'AI_INVALID_OUTPUT'}],requests:[{id,state:'failed',reason:'AI_INVALID_OUTPUT',attempts:1,retry_at:300000,updated_at:1}]});
test('plans reject foreign scope, forged execution and invalid basis',()=>{
 assert.equal(validateDistributionPlans(data(),scope).items[0].basis,'rules');
 for(const patch of [{tenant_id:5},{automated_publish:true},{items:[{...data().items[0],basis:'automated'}]}])assert.throws(()=>validateDistributionPlans({...data(),...patch},scope),{code:'CONTRACT_MISMATCH'});
});
test('plan UI distinguishes fallback and unknown outcomes without item start buttons',()=>{
 assert.match(distributionPlanningMarkup(data()),/规则安排/);assert.match(distributionPlanningMarkup(data()),/采用规则安排/);
 const d=data();d.requests[0].reason='AI_ATTEMPT_UNKNOWN';assert.match(distributionPlanningMarkup(d),/暂停重试并等待人工核查/);
 d.items[0].basis='ai';assert.match(distributionPlanningMarkup(d),/AI 建议/);assert.doesNotMatch(distributionPlanningMarkup(d),/<button/);
});
test('plans use scoped GET and clear access on revocation',async()=>{
 let denied=false;const calls=[];const client=createDistributionClient({session:{token:'synthetic',user:{id:7,tenant_id:4,permissions:{'seo.site':'edit','seo.content':'edit'}},logout(){}},fetchImpl:async(path,options)=>{calls.push({path,method:options.method});return denied?{status:403,ok:false}:{status:200,ok:true,json:async()=>data()};}});
 await client.plans(scope);denied=true;await assert.rejects(client.plans(scope),{code:'PERMISSION_DENIED'});assert(calls.every(c=>c.method==='GET'&&c.path.startsWith('/api/distribution/v1/plans?')));client.dispose();
});
