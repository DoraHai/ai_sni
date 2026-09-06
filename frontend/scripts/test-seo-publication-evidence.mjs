import test from 'node:test'
import assert from 'node:assert/strict'
import { publicationEvidence, channelBoundary, countPublishedListedContents } from '../src/utils/seoPublicationEvidence.js'

test('publication labels distinguish reported and API evidence without claiming verification',()=>{
  for(const publish_mode of ['manual','assisted','share']) assert.equal(publicationEvidence({status:'published',publish_mode}),'人工确认 / 链接登记')
  for(const publish_mode of ['publish','draft']) assert.equal(publicationEvidence({status:'published',publish_mode}),'接口任务，确认依据见尝试记录')
  assert.equal(publicationEvidence({status:'published'}),'历史发布记录，依据待确认')
  for(const status of ['manual_required','draft_created','publishing','failed']) assert.equal(publicationEvidence({status,publish_mode:'publish'}),'尚无发布成功记录')
})
test('catalog support does not imply account or publishing acceptance',()=>{
  assert.match(channelBoundary({available:true,mode:'assisted'}),/最终发布由真人/)
  assert.match(channelBoundary({available:true,mode:'api'}),/连接成功不代表发布/)
  assert.equal(channelBoundary({available:false,mode:'api'}),'当前尚未开放')
})

test('coverage uses current list scope and deduplicates platforms',()=>{
  const rows=[{status:'published',content_id:1},{status:'published',content_id:1},{status:'published',content_id:99},{status:'manual_required',content_id:2}]
  assert.equal(countPublishedListedContents([{id:1},{id:2}],rows),1)
  assert.equal(countPublishedListedContents([],rows),0)
})
