import test from 'node:test'
import assert from 'node:assert/strict'
import { executionNext, createOverviewLoader } from '../src/utils/geoExecutionOverview.js'
const task={id:1,status:'in_progress',params:{content_task_id:12}}
const base={baseline_valid:true,publication_evidence:{first_verified_at:'2026-09-01'}}
test('unknown and failed reads never become no-work or completed',()=>{
 assert.equal(executionNext(task,null).stage,'条件未知')
 assert.equal(executionNext(task,null,'网络故障').next,'网络故障')
 assert.equal(executionNext(task,{baseline_valid:false}).stage,'缺少有效基线')
})
test('publication candidates mean awaiting verification, not proof',()=>{
 assert.equal(executionNext(task,{baseline_valid:true}).stage,'缺少发布证据')
 assert.equal(executionNext(task,{baseline_valid:true,publication_candidates:[{id:1}]}).stage,'发布待核实')
})
test('retest stages never imply passing the metric goal',()=>{
 assert.equal(executionNext(task,{...base,latest_retest:{status:'running'},can_retest:true}).stage,'复测执行中')
 assert.equal(executionNext(task,{...base,can_retest:true}).stage,'可启动复测')
 assert.equal(executionNext(task,{...base,latest_retest:{status:'failed',error:'quota'}}).next,'quota')
 assert.equal(executionNext(task,{...base,latest_retest:{status:'completed'}}).stage,'等待后测或验收')
})
test('unlinked and terminal tasks are classified without demanding publication',()=>{
 assert.equal(executionNext({...task,params:{}},{baseline_valid:true,can_retest:true}).stage,'可启动复测')
 assert.equal(executionNext({...task,status:'cancelled'},null).stage,'已取消')
 assert.equal(executionNext(task,{status:'done'}).stage,'已完成')
})
test('loader limits concurrency and isolates per-task failures',async()=>{
 let active=0,max=0,calls=0
 const state={};const loader=createOverviewLoader(state,{readiness:async(t,id)=>{
  calls++;active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,2));active--
  if(id===2) throw Error('unavailable');return {task_id:id}
 }})
 await loader.load(7,Array.from({length:7},(_,i)=>({...task,id:i+1})))
 assert.equal(calls,7);assert.equal(max,3);assert.equal(state.rows[1].error,'unavailable');assert.equal(state.rows[6].detail.task_id,7)
})
test('customer change discards late responses and stops scheduling old tasks',async()=>{
 const pending=[];const calls=[];const state={}
 const loader=createOverviewLoader(state,{readiness:(tenant,id)=>{calls.push([tenant,id]);return new Promise(resolve=>pending.push(resolve))}})
 const first=loader.load(7,Array.from({length:10},(_,i)=>({...task,id:i+1})))
 await Promise.resolve() // Let the first three requests enter the adapter.
 await loader.load(8,[{...task,id:20,status:'done'}])
 pending.forEach(resolve=>resolve({task_id:1}));await first
 assert.equal(calls.length,3);assert.equal(state.rows[0].task.id,20);assert.equal(state.loading,false)
})


test('missing or malformed baseline flags remain unknown',()=>{
 for (const detail of [{},{baseline_valid:null},{baseline_valid:'false'}]) {
  assert.equal(executionNext(task,detail).stage,'条件未知')
 }
 assert.notEqual(executionNext(task,{...base,can_retest:'true'}).stage,'可启动复测')
})
test('rapid batch changes share the same three-request limit',async()=>{
 let active=0,max=0;const calls=[];const state={}
 const loader=createOverviewLoader(state,{readiness:async(tenant,id)=>{
  calls.push([tenant,id]);active++;max=Math.max(max,active)
  await new Promise(resolve=>setTimeout(resolve,8));active--
  return {task_id:id}
 }})
 const tasks=Array.from({length:10},(_,i)=>({...task,id:i+1}))
 const first=loader.load(7,tasks)
 await new Promise(resolve=>setTimeout(resolve,1))
 const second=loader.load(8,tasks)
 const third=loader.load(9,[{...task,id:99}])
 await Promise.all([first,second,third])
 assert.equal(max,3);assert.equal(state.rows[0].detail.task_id,99)
 assert.ok(!calls.some(([tenant])=>tenant===8))
 assert.equal(calls.filter(([tenant])=>tenant===7).length,3)
 assert.equal(state.loading,false)
})
