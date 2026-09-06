const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'demo-finish.js'),'utf8');
const data=new Map([['drafts','saved plans'],['cockpit-rehearsals-v1','saved rehearsals'],['unrelated','keep']]);
let submit,reloads=0;
vm.runInNewContext(source.slice(source.lastIndexOf("document.addEventListener('submit'"),source.lastIndexOf('renderPanorama();')),{document:{addEventListener:(type,fn)=>submit=fn},storageKey:'drafts',sessionStorage:{getItem:k=>data.get(k)??null,removeItem:k=>data.delete(k),setItem:(k,v)=>data.set(k,v)},location:{reload:()=>reloads++},toast:()=>{}});
const event=checked=>({preventDefault(){},target:{id:'demoResetForm',reportValidity:()=>true,elements:{confirmed:{checked}}}});
submit(event(false));assert.equal(data.size,3);assert.equal(reloads,0);
submit(event(true));assert.equal(data.has('drafts'),false);assert.equal(data.has('cockpit-rehearsals-v1'),false);assert.equal(data.get('unrelated'),'keep');assert.equal(reloads,1);
console.log('Reset checks passed: explicit confirmation required; only the two prototype storage keys removed.');
