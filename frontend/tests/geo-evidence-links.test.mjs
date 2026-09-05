import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceTaskLink, evidenceLinkTarget } from '../src/utils/geoEvidenceLinks.js'
test('links retain customer and task identity',()=>{
 const link=evidenceTaskLink(7,999)
 assert.equal(link.path,'/geo/tickets')
 assert.deepEqual(evidenceLinkTarget(link.query,7),{id:999,error:''})
 assert.deepEqual(evidenceLinkTarget(link.query,'7'),{id:999,error:''})
 assert.equal(evidenceLinkTarget(link.query,8).id,null)
 assert.ok(evidenceLinkTarget(link.query,8).error)
})
test('malformed, ambiguous and unscoped links cannot select a task',()=>{
 for(const value of ['0','1.2','1e2','-1',['12'],'9007199254740992']) {
  const result=evidenceLinkTarget({evidence_task_id:value,evidence_tenant_id:'7'},7)
  assert.equal(result.id,null);assert.ok(result.error)
 }
 assert.ok(evidenceLinkTarget({evidence_task_id:'12'},7).error)
 assert.deepEqual(evidenceLinkTarget({},7),{id:null,error:''})
})
