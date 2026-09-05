import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import { JSDOM } from 'jsdom'
const dom=new JSDOM('',{url:'https://example.test/seo/distribution'})
for(const key of ['window','history','sessionStorage'])globalThis[key]=dom.window[key]
const renderer=Vue.createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),setText(){},setElementText(){},patchProp(){},insert(){},remove(){},parentNode:()=>null,nextSibling:()=>null})
const flush=async()=>{for(let i=0;i<6;i++)await Vue.nextTick()}
async function mount(name,api,props,session={user:{id:7}}){
  const source=await readFile(new URL(`../src/views/seo/${name}.vue`,import.meta.url),'utf8')
  const compiled=compileScript(parse(source).descriptor,{id:name,genDefaultAs:'component'}).content
  const bindings={...Object.fromEntries(Object.entries(Vue).filter(([key])=>/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key))),...api,session}
  const code=compiled.replace(/^import .* from .*$/gm,'')
  const component=new Function('b',`const {${Object.keys(bindings).join(',')}}=b;${code};return component`)(bindings)
  component.render=()=>null
  const app=renderer.createApp({render:()=>Vue.h(component,props)}),root=app.mount({})
  await flush()
  return {app,state:root.$.subTree.component.setupState}
}
test('video waits for actual site before OAuth completion, consumes local state once',async()=>{
  history.replaceState({},'', '/seo/distribution?code=code&state=nonce')
  sessionStorage.setItem('seo-video-oauth-v1',JSON.stringify({scope:'1:10:7',tenant_id:1,site_id:10,connection_id:3,state:'nonce'}))
  const calls=[],props=Vue.reactive({tenantId:1,siteId:null,canEdit:true,contents:[]})
  const {app}=await mount('SeoVideoPublishing',{seoVideoGet:async()=>[],seoVideoPost:async(path,payload)=>{calls.push({path,payload});return {}}},props)
  try{
    assert.equal(window.location.search,'');assert.equal(calls.length,0)
    props.siteId=10;await flush()
    assert.equal(calls.length,1);assert.equal(calls[0].payload.site_id,10)
    assert.equal(sessionStorage.getItem('seo-video-oauth-v1'),null)
  }finally{app.unmount()}
})
test('video ignores stale list response, read-only cannot upload or authorize',async()=>{
  const reads=[],writes=[],props=Vue.reactive({tenantId:1,siteId:10,canEdit:true,contents:[]})
  const {app,state}=await mount('SeoVideoPublishing',{seoVideoGet:(path,params)=>new Promise(resolve=>reads.push({path,params,resolve})),seoVideoPost:async(...args)=>writes.push(args)},props)
  try{
    props.siteId=20;await flush()
    reads.slice(2).forEach(r=>r.resolve([]));reads.slice(0,2).forEach(r=>r.resolve([{id:999}]));await flush()
    assert.deepEqual(state.publications,[])
    props.canEdit=false;await flush();await state.authorize({connection_id:3});assert.equal(writes.length,0)
  }finally{app.unmount()}
})
test('backlink followup captures scope, no stale result after site change',async()=>{
  let release;const writes=[],props=Vue.reactive({tenantId:1,siteId:10,canEdit:true})
  const {app,state}=await mount('SeoBacklinkWorkflow',{fetchSeoWorkOrders:async()=>[],fetchSeoBacklinkOutcomes:async()=>({items:[]}),updateSeoWorkOrder:(id,payload)=>{writes.push({id,payload});return new Promise(resolve=>release=resolve)},saveSeoReferral:async()=>{}},props)
  try{
    state.notes={3:'联系计划'};const pending=state.update({id:3},'in_progress');await flush()
    props.siteId=20;await flush();release();await pending
    assert.equal(writes[0].payload.site_id,10);assert.deepEqual(state.tasks,[])
    props.canEdit=false;await flush();await state.update({id:3},'done');assert.equal(writes.length,1)
  }finally{app.unmount()}
})
