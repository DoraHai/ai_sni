import test from 'node:test'
import assert from 'node:assert/strict'
import { retestDiagnosis } from '../src/utils/geoRetestDiagnosis.js'
import { executionNext } from '../src/utils/geoExecutionOverview.js'
test('unfinished and missing result never count as matching',()=>{
 assert.equal(retestDiagnosis(null),null)
 assert.equal(retestDiagnosis({status:'running',result:{comparable:true}}).label,'复测尚未结束')
 assert.equal(retestDiagnosis({status:'completed'}).label,'样本匹配结果未知')
 assert.equal(retestDiagnosis({status:'completed',result:{comparable:'true'}}).label,'样本匹配结果未知')
})
test('matching sampling matrix does not claim metric acceptance',()=>{
 assert.match(retestDiagnosis({status:'completed',result:{comparable:true}}).note,/不代表目标已达成/)
})
test('missing cells preserve server counts and ignore invalid navigation ids',()=>{
 const valid={prompt_id:71,engine:'deepseek',count:2}
 const value=retestDiagnosis({status:'completed',result:{comparable:false,missing:[valid,{prompt_id:-1,engine:'kimi',count:1},{prompt_id:1,engine:'kimi',count:0}]}})
 assert.deepEqual(value.missing,[valid]);assert.equal(value.label,'采样矩阵不匹配')
})
test('equal total counts do not override server distribution mismatch',()=>{
 const run={status:'completed',result:{comparable:false,expected_samples:8,qualified_samples:8,missing:[]}}
 assert.match(retestDiagnosis(run).note,/总数相同/)
 assert.equal(executionNext({id:1,status:'in_progress',params:{}},{baseline_valid:true,latest_retest:run,can_retest:false}).stage,'复测样本不匹配')
})
test('failed execution retains the actual reason',()=>{
 assert.equal(retestDiagnosis({status:'failed',error:'模型不一致'}).note,'模型不一致')
})
