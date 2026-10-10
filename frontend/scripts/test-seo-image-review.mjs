import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { imageReviewPrecondition, requireImageVersion } from '../src/utils/seoImageReview.js'

test('creation explicitly requires absence; editing retains the observed version', () => {
  assert.deepEqual(imageReviewPrecondition(null), {expected_review_id:null, expected_review_version:null})
  const observed = {id:8,version:'a'.repeat(64)}
  const request = imageReviewPrecondition(observed)
  observed.version = 'b'.repeat(64)
  assert.equal(request.expected_review_version, 'a'.repeat(64))
  assert.equal(request.expected_review_id, 8)
})

test('old or malformed drafts cannot silently use null or a replacement version', () => {
  for (const row of [{id:8}, {id:8,version:null}, {id:8,version:'bad'}, {version:'a'.repeat(64)}, {id:0,version:'a'.repeat(64)}]) {
    assert.throws(() => imageReviewPrecondition(row))
  }
  for (const value of [null,undefined,'', 'x'.repeat(64)]) assert.throws(() => requireImageVersion(value))
})

function dialogFixture() {
  const source=readFileSync(new URL('../src/views/seo/SeoImageEvidenceDialog.vue',import.meta.url),'utf8')
  const script=source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm,'')
  const calls=[],errors=[]
  const env={
    ref:value=>({value}),computed:fn=>({get value(){return fn()}}),watch:()=>{},onBeforeUnmount:()=>{},
    defineProps:()=>({visible:true,tenantId:1,siteId:1,page:{id:10},canEdit:true}),defineEmits:()=>()=>{},
    ElMessage:{success:()=>{},warning:()=>{},error:message=>errors.push(message)},ElMessageBox:{confirm:async()=>{}},
    imageReviewPrecondition,requireImageVersion,
    fetchSeoImageEvidence:async()=>{calls.push('read');return {snapshot_id:12,evidence:{items:[{position:1}]}}},
    fetchSeoImageRemediation:async()=>({snapshot_id:12,items:[{id:8,position:1,version:'a'.repeat(64),decision:'informative',alt_suggestion:'old',review_status:'draft'}]}),
    fetchSeoImageRemediationHistory:async()=>({current_snapshot_id:12,items:[{snapshot_id:11,approved_count:1,approved_version:'c'.repeat(64)}]}),
    fetchSeoImageRemediationReusePreview:async()=>({target_snapshot_id:12,eligible_count:1,source_page_count:1,reuse_version:'b'.repeat(64)}),
    saveSeoImageRemediation:async payload=>{calls.push(payload);throw new Error('409 stale version')},
    copySeoImageRemediation:async payload=>{calls.push(payload);return {copied:0}},
    reuseSeoImageRemediation:async payload=>{calls.push(payload);return {copied:0}},
  }
  const component=new Function(...Object.keys(env),script+'; return {load,saveReview,copyPrevious,reuseAcrossPages,drafts};')(...Object.values(env))
  return {component,calls,errors}
}

test('actual dialog sends the observed version and never refreshes/retries a rejected edit', async () => {
  const {component,calls,errors}=dialogFixture()
  await component.load()
  component.drafts.value[1].alt_suggestion='user edit'
  await component.saveReview({position:1})
  assert.equal(calls.length,2)
  assert.equal(calls[1].expected_review_version,'a'.repeat(64))
  assert.equal(calls[1].alt_suggestion,'user edit')
  assert.deepEqual(errors,['409 stale version'])
  assert.equal(component.drafts.value[1].alt_suggestion,'user edit')
})

test('actual dialog binds copy and reuse to the displayed source/preview versions', async () => {
  const {component,calls}=dialogFixture()
  await component.load();await component.copyPrevious();await component.reuseAcrossPages()
  const writes=calls.filter(value=>typeof value==='object')
  assert.equal(writes.length,2)
  assert.equal(writes[0].expected_source_version,'c'.repeat(64))
  assert.equal(writes[1].expected_reuse_version,'b'.repeat(64))
})
