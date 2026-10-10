import test from 'node:test';
import assert from 'node:assert/strict';
import {usageReviewPayload,renderUsageReview,canReviewUsage} from './js/platform-usage-review.mjs';
import {escapeText as esc} from './js/customer-display.mjs';
const eventId='12345678-1234-1234-1234-123456789abc',requestId='87654321-4321-4321-4321-cba987654321';
const row={id:eventId,state:'error',review_version:3,provider:'deepseek',module:'seo',endpoint:'api.deepseek.com/chat/completions',estimated_amount:null,reviewed_provider_request_id:'vendor-123',can_review:true};
const fields={event_id:eventId,terminal_state:'error',provider_request_id:'vendor-123',verified_amount:'',source:'provider_request_record',
 reference:'case-123',sha256:'a'.repeat(64),summary:'供应商请求记录确认失败，扣款金额仍待核对。',observed_at:'2026-10-11T08:00:00+08:00',terminal_confirmed:'on'};
const build=(changes={},record=row)=>usageReviewPayload({row:record,fields:{...fields,...changes},requestId});

test('manual terminal evidence binds the precise ledger version and keeps unknown money null',()=>{
 const payload=build();assert.equal(payload.event_id,eventId);assert.equal(payload.expected_version,3);assert.equal(payload.expected_state,'error');
 assert.equal(payload.verified_amount,null);assert.equal(payload.currency,null);assert.equal(payload.evidence.provider_host,'api.deepseek.com');
 assert.equal(payload.evidence.observed_at,'2026-10-11T00:00:00.000Z');assert.equal(payload.request_id,requestId);
 assert(!('estimated_amount' in payload));assert(!('tenant_id' in payload));
});

test('money needs billing evidence and zero charges need explicit vendor confirmation',()=>{
 assert.throws(()=>build({verified_amount:'0'}),/账务或客服证据/);
 assert.throws(()=>build({source:'provider_billing_record',verified_amount:'0'}),/零扣款证据/);
 assert.equal(build({source:'provider_support_record',verified_amount:'0.000',zero_charge_confirmed:'on'}).verified_amount,'0.000');
 assert.equal(build({source:'provider_billing_record',verified_amount:'12.345678901234'}).verified_amount,'12.345678901234');
 for(const amount of ['-1','NaN','1e2','1.0000000000001','9999999999999'])assert.throws(()=>build({source:'provider_billing_record',verified_amount:amount}),/非负人民币金额/);
});

test('a changed event, forged version fields, missing attestation and invalid proof cannot produce a request',()=>{
 for(const change of [{event_id:requestId},{expected_version:0},{terminal_confirmed:''},{sha256:'not-a-digest'},{source:'guessed_free'},{observed_at:'not-a-time'}])assert.throws(()=>build(change));
 assert.throws(()=>build({provider_request_id:'another-vendor-call'}),/不能改绑/);
 assert.throws(()=>build({}, {...row,review_version:undefined}));
 assert.throws(()=>build({}, {...row,endpoint:'/missing-provider'}));
});

test('manual review stays hidden until the exact capability and schema are enabled',()=>{
 const card=(title,body,note)=>title+body+note,history={data:{rows:[row]}};
 for(const usage_reviews of [undefined,{state:'enabled',capabilities:['usage_review_v1']},{schema:1,state:'ready',capabilities:['usage_review_v1']},{schema:1,state:'enabled',capabilities:[]}]){
  const snapshot={usage_reviews};assert(!canReviewUsage(snapshot));assert(!renderUsageReview({snapshot,history,esc,card}).includes('<form'));
 }
 const snapshot={usage_reviews:{schema:1,state:'enabled',capabilities:['usage_review_v1']}};
 const html=renderUsageReview({snapshot,history:{...history,reviewBlocked:true},esc,card});
 assert.match(html,/请先重新查询明细核对/);assert.match(html,/<button disabled>/);assert.match(html,/不宣称已自动验证/);
 assert(!html.includes('checked'));
 const unsafe=renderUsageReview({snapshot,history:{data:{rows:[{...row,provider:'<script>bad()</script>'}]}},esc,card});
 assert(!unsafe.includes('<script>'));assert.match(unsafe,/&lt;script&gt;/);
});
