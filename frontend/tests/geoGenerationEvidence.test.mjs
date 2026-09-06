import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import {readFileSync} from 'node:fs'
const page=readFileSync(new URL('../src/views/geo/GeoTaskEditorView.vue',import.meta.url),'utf8')
const code=page.slice(page.indexOf('function validateBeforeGenerate()'),page.indexOf('async function ensurePrototypeMaterials()'))
function fixture(meta) {
 const context=vm.createContext({briefPayload:()=>({industry:'industry',audience:'audience',intent:'intent',content_type:'type',cta:'cta'}),
 task:{value:{facts:[1,2,3],generation_evidence:meta}},selectedFactIds:{value:[1,2,3]},libraryVerifiedCount:{value:20}})
 vm.runInContext(code,context);return context
}
test('many bound or library facts cannot override server evidence rejection',()=>{
 const ctx=fixture({ok:false,blocking_message:'#2 缺来源；#3 已过期'})
 assert.equal(ctx.validateBeforeGenerate(),'#2 缺来源；#3 已过期')
})
test('eligible evidence permits generation preflight without claiming review',()=>{
 const ctx=fixture({ok:true});assert.equal(ctx.validateBeforeGenerate(),null)
})
test('missing brief is still required with eligible evidence',()=>{
 const ctx=fixture({ok:true});ctx.briefPayload=()=>({})
 assert.match(ctx.validateBeforeGenerate(),/Brief 缺少/)
})
