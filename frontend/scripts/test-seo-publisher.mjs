import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { readFile } from 'node:fs/promises'
import { fillField, validatePackage, platformHosts, validateResults, sanitizeRichText, publicationUrl } from '../src/views/seo/publisher/core.js'
import { createPublisherPackage, publisherZip } from '../src/views/seo/seoPublisher.js'
const row = {id:7,platform_code:'baijiahao',connection_name:'品牌A',status:'manual_required',adapted_title:'核验资料',adapted_content:'<p>正文事实</p><script>bad()</script><p>第二段</p>',handoff_url:'https://baijiahao.baidu.com/',source_version:2}
function dom(html, url='https://baijiahao.baidu.com/editor') {
  const d=new JSDOM(html,{url,pretendToBeVisual:true})
  for(const key of ['document','location','DOMParser']) globalThis[key]=d.window[key]
  globalThis.getComputedStyle=d.window.getComputedStyle.bind(d.window)
  d.window.HTMLElement.prototype.getClientRects = function() { return this.hidden ? [] : [{}] }
  return d
}

test('task export keeps only pending browser tasks, strips active content and unrelated fields',()=>{
  const d=dom('')
  try {
    const pack=createPublisherPackage([row,{...row,id:8,status:'published'}])
    assert.equal(pack.items.length,1);assert.equal(pack.items[0].text,'正文事实\n第二段')
    assert.equal(pack.items[0].source_version,'2');assert.equal(pack.items[0].account,'品牌A')
    assert.ok(!JSON.stringify(pack).includes('bad()'))
    const dirty={...pack,secret:'x',items:[{...pack.items[0],cookie:'secret'}]}
    assert.ok(!JSON.stringify(validatePackage(dirty)).includes('secret'))
    assert.throws(()=>validatePackage({...pack,items:[{...pack.items[0],editor_url:'https://baijiahao.baidu.com.attacker.test/'}]}))
    assert.throws(()=>validatePackage({...pack,items:[pack.items[0],pack.items[0]]}))
    assert.throws(()=>createPublisherPackage([]))
  } finally {d.window.close()}
})

test('fills a blank title using input event, refuses existing text, length overflow and wrong platform',()=>{
  const d=dom('<input placeholder="请输入标题" maxlength="20"><button id="publish">发布</button>')
  try {
    const input=document.querySelector('input');let events=0,clicks=0
    input.addEventListener('input',()=>events++);document.querySelector('button').onclick=()=>clicks++
    assert.equal(fillField('title','中文标题',platformHosts.baijiahao).ok,true)
    assert.equal(input.value,'中文标题');assert.equal(events,1);assert.equal(clicks,0)
    assert.equal(fillField('title','覆盖',platformHosts.baijiahao).ok,false)
    assert.equal(input.value,'中文标题')
    input.value='';assert.equal(fillField('title','字'.repeat(21),platformHosts.baijiahao).ok,false)
    assert.equal(fillField('title','标题',platformHosts.toutiao).ok,false)
  } finally {d.window.close()}
})

test('ambiguous fields require explicit focus and populated body is never replaced',()=>{
  const d=dom('<textarea></textarea><textarea></textarea>')
  try {
    assert.equal(fillField('body','正文',platformHosts.baijiahao).ok,false)
    const target=document.querySelector('textarea');target.focus()
    assert.equal(fillField('body','正文\n事实',platformHosts.baijiahao).ok,true)
    assert.equal(target.value,'正文\n事实')
    assert.equal(fillField('body','替换',platformHosts.baijiahao).ok,false)
  } finally {d.window.close()}
})

test('rich editor uses text insertion and never evaluates source HTML',()=>{
  const d=dom('<div contenteditable="true"></div><button>发布</button>')
  try {
    let command
    document.execCommand=(name,ui,text)=>{ command=name;document.querySelector('div').textContent=text;return true }
    assert.equal(fillField('body','<script>示例代码</script>\n段落',platformHosts.baijiahao).ok,true)
    assert.equal(command,'insertText');assert.equal(document.querySelectorAll('script').length,0)
    assert.ok(document.querySelector('div').textContent.includes('<script>'))
  } finally {d.window.close()}
})

test('installable ZIP has consistent central directory offsets',async()=>{
  const manifest=JSON.parse((await readFile(new URL('../src/views/seo/publisher/manifest.json',import.meta.url),'utf8')).replace(/^\uFEFF/,''))
  assert.deepEqual(manifest.permissions,['activeTab','scripting','storage','clipboardWrite'])
  assert.equal(manifest.host_permissions,undefined)
  const blob=publisherZip({'manifest.json':JSON.stringify(manifest),'README.txt':'中文说明'})
  const bytes=new Uint8Array(await blob.arrayBuffer()), view=new DataView(bytes.buffer)
  assert.equal(view.getUint32(0,true),0x04034b50)
  const end=bytes.length-22,offset=view.getUint32(end+16,true)
  assert.equal(view.getUint32(end,true),0x06054b50)
  assert.equal(view.getUint32(offset,true),0x02014b50)
  assert.equal(view.getUint16(end+8,true),2)
  assert.throws(()=>publisherZip({'../bad.js':'x'}))
})

test('distribution view clears old scope before export and ignores stale loads',async()=>{
  const Vue=await import('vue')
  const {parse,compileScript}=await import('@vue/compiler-sfc')
  const source=await readFile(new URL('../src/views/seo/SeoDistributionView.vue',import.meta.url),'utf8')
  const script=compileScript(parse(source).descriptor,{id:'distribution-test',genDefaultAs:'component'}).content
  const bindings={}
  const code=script.replace(/^import\s+\{([\s\S]*?)\}\s+from\s+['"][^'"]+['"]/gm,(_,list)=>{
    for(const name of list.split(',').map(s=>s.trim()).filter(Boolean)) {
      const [original,alias]=name.split(/\s+as\s+/)
      bindings[alias||original]=Vue[original]||(()=>Promise.resolve({items:[]}))
    }
    return ''
  }).replace(/const publisherFiles = import\.meta\.glob\([^\n]+\)/,'const publisherFiles = {}')
  const tenant=Vue.ref(1),site=Vue.ref(10),reads=[]
  const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
  Object.assign(bindings,{currentTenantId:tenant,siteId:site,session:Vue.reactive({user:{id:7},isLoggedIn:true,canEdit:()=>true}),
    fetchSeoSites:async()=>({sites:[{id:10,status:'active'}]}),
    fetchSeoDistributionCatalog:async()=>({items:[]}),fetchSeoDistributionConnections:async()=>({items:[]}),
    fetchSeoContentAssets:async()=>({items:[]}),fetchSeoDistributionVariants:async()=>({items:[]}),
    fetchSeoContentPublications:()=>{const d=deferred();reads.push(d);return d.promise},
    ElMessage:{warning(){},success(){},error(){}},ElMessageBox:{},createPublisherPackage,publisherZip,
  })
  const component=new Function('b',`const {${Object.keys(bindings).join(',')}}=b;${code};return component`)(bindings)
  component.render=()=>null
  const renderer=Vue.createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),setText(){},setElementText(){},patchProp(){},insert(){},remove(){},parentNode:()=>null,nextSibling:()=>null})
  const app=renderer.createApp(component);const vm=app.mount({});const state=vm.$.setupState
  const flush=async()=>{for(let i=0;i<5;i++) await Vue.nextTick()}
  try {
    await flush();assert.equal(reads.length,1)
    state.handoffItem={...row};state.completeDialog=true
    tenant.value=2;await flush()
    assert.equal(state.completeDialog,false);assert.equal(state.handoffItem,null)
    reads[0].resolve({items:[{...row,content_id:999}]});await flush()
    assert.deepEqual(state.publications,[])
    assert.ok(source.includes('@click="exportPublisherTasks(filteredActiveTasks)"'))
    assert.ok(source.includes('@click="downloadPublisher"'))
  } finally {app.unmount()}
})


test('result recovery rejects another task, stale version, wrong platform and editor URLs',()=>{
  const data={schema:'seo-domestic-results-v1',items:[{publication_id:7,platform_code:'baijiahao',source_version:2,page_url:'https://baijiahao.baidu.com/s?id=123'}]}
  assert.equal(validateResults(data,[row])[0].publication_id,7)
  assert.throws(()=>validateResults(data,[{...row,source_version:3}]))
  assert.throws(()=>validateResults(data,[{...row,id:8}]))
  assert.throws(()=>validateResults({...data,items:[data.items[0],data.items[0]]},[row]))
  assert.throws(()=>publicationUrl('https://baijiahao.baidu.com.attacker.test/s?id=123','baijiahao'))
  assert.throws(()=>publicationUrl('https://baijiahao.baidu.com/editor','baijiahao'))
  assert.throws(()=>publicationUrl('https://u:p@baijiahao.baidu.com/s?id=123','baijiahao'))
})
test('rich copy preserves safe structure and image URLs without active HTML',()=>{
  const d=dom('')
  try {
    const cleaned=sanitizeRichText('<h2>标题</h2><p onclick="evil()">正文<img src="https://media.example/a.jpg" onerror="bad()"></p><iframe src="https://evil.test"></iframe><a href="javascript:bad()">资料</a>')
    assert.ok(cleaned.includes('<h2>标题</h2>'));assert.ok(cleaned.includes('https://media.example/a.jpg'))
    assert.ok(!/onclick|onerror|javascript|iframe|bad\(\)/.test(cleaned))
  } finally {d.window.close()}
})
