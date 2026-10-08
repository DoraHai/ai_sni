import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {verifyPayload} from './package-release.mjs';
const commit='a'.repeat(40);
function fixture(change={}){
  const files=new Map(['app.css','app.js','index.html'].map(name=>[name,Buffer.from('fixture '+name)]));
  const manifest={schema:1,base:'/customer-workbench/',sourceTreeClean:true,upstreamCommit:commit,files:Object.fromEntries([...files].map(([name,data])=>[name,{bytes:data.length,sha256:createHash('sha256').update(data).digest('hex')}])) ,...change};
  files.set('release-manifest.json',Buffer.from(JSON.stringify(manifest)));return files;
}
test('accepts only the exact clean four-file release',()=>assert.equal(verifyPayload(fixture(),commit).upstreamCommit,commit));
test('rejects dirty or different source versions',()=>{
  assert.throws(()=>verifyPayload(fixture({sourceTreeClean:false}),commit));
  assert.throws(()=>verifyPayload(fixture({upstreamCommit:'b'.repeat(40)}),commit));
});
test('rejects additional development or credential files',()=>{const files=fixture();files.set('.env',Buffer.from('fixture'));assert.throws(()=>verifyPayload(files,commit));});
test('rejects missing or tampered payloads',()=>{
  const missing=fixture();missing.delete('app.css');assert.throws(()=>verifyPayload(missing,commit));
  const altered=fixture();altered.set('app.js',Buffer.from('other'));assert.throws(()=>verifyPayload(altered,commit));
});
test('rejects a different URL base and malformed commit',()=>{
  assert.throws(()=>verifyPayload(fixture({base:'/'}),commit));assert.throws(()=>verifyPayload(fixture(),'HEAD'));
});
