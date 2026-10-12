import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {checkedFile,verifyBuild,verifyHttp,verifyLinux} from '../scripts/verify_automation_candidate.mjs';

function fixture(t){
 const parent=fs.realpathSync(os.tmpdir()),root=fs.mkdtempSync(path.join(parent,'automation-candidate-test-'));
 t.after(()=>{assert.ok(fs.realpathSync(root).startsWith(parent+path.sep)&&path.basename(root).startsWith('automation-candidate-test-'));fs.rmSync(root,{recursive:true,force:true});});
 return root;
}
test('artifact paths cannot traverse to other files',t=>{
 const root=fixture(t);fs.writeFileSync(path.join(root,'safe.txt'),'safe');assert.equal(checkedFile(root,'safe.txt').toString(),'safe');
 for(const name of ['../outside.env','/outside.env','a/../../outside.env','a\\outside.env'])assert.throws(()=>checkedFile(root,name));
});
test('a complete build rejects stale revisions, omitted inputs and changed output bytes',t=>{
 const root=fixture(t),source=fileURLToPath(new URL('../../',import.meta.url));
 const build='customer-workbench/dist/customer-workbench',manifestPath=path.join(root,build,'release-manifest.json');
 const manifest=JSON.parse(fs.readFileSync(path.join(source,build,'release-manifest.json'),'utf8'));
 const names=[...Object.keys(manifest.files).map(name=>build+'/'+name),
   ...Object.keys(manifest.localSources).map(name=>'customer-workbench/'+name),
   ...Object.keys(manifest.canonicalSources).map(name=>'frontend/'+name),
   'frontend/package-lock.json','customer-workbench/package-lock.json'];
 for(const name of names){const target=path.join(root,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,checkedFile(source,name));}
 fs.writeFileSync(manifestPath,JSON.stringify(manifest));
 assert.equal(verifyBuild(root,manifest.upstreamCommit).local_sources,62);
 assert.throws(()=>verifyBuild(root,'stale'));
 const omitted=structuredClone(manifest);delete omitted.localSources['css/workbench.css'];
 fs.writeFileSync(manifestPath,JSON.stringify(omitted));assert.throws(()=>verifyBuild(root,manifest.upstreamCommit));
 fs.writeFileSync(manifestPath,JSON.stringify(manifest));fs.appendFileSync(path.join(root,build,'app.js'),'changed');
 assert.throws(()=>verifyBuild(root,manifest.upstreamCommit));
});
test('HTTP evidence rejects stale revisions and missing cache protection',t=>{
 const root=fixture(t),file=path.join(root,'sample.json');const sample={backend_commit:'current',source_tree_clean:true,responses:{a:{headers:{'cache-control':'no-store'},status:200,body:{}}}};
 fs.writeFileSync(file,JSON.stringify(sample));assert.equal(verifyHttp(file,'current').response_snapshots,1);assert.throws(()=>verifyHttp(file,'older'));
 sample.source_tree_clean=false;fs.writeFileSync(file,JSON.stringify(sample));assert.throws(()=>verifyHttp(file,'current'));
 sample.source_tree_clean=true;sample.responses.a.headers={};fs.writeFileSync(file,JSON.stringify(sample));assert.throws(()=>verifyHttp(file,'current'));
});
test('Linux evidence rejects Windows, skips and different production functions',t=>{
 const root=fixture(t),file=path.join(root,'linux.json');fs.mkdirSync(path.join(root,'app','geo'),{recursive:true});
 const code=Buffer.from('verified code');
 const sources=['app/geo/scheduler.py','app/geo/scheduler_observability.py',
   'tests/test_geo_followup_scheduler.py','tests/test_geo_scheduler.py',
   'tests/test_geo_scheduler_observability.py','tests/test_geo_scheduler_eligibility.py'];
 for(const name of sources){const target=path.join(root,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,code);}
 const digest=crypto.createHash('sha256').update(code).digest('hex');
 const result={schema:1,platform:'Linux',test_exit_code:0,counts:{tests:2,failures:0,errors:0,skipped:0},network_io_permitted:false,database_operations:false,production_approval:false,source_sha256:Object.fromEntries(sources.map(name=>[name,digest]))};
 fs.writeFileSync(file,JSON.stringify(result));assert.equal(verifyLinux(file,root).production_dependency_parity_verified,false);
 for(const change of [{platform:'Windows'},{counts:{...result.counts,skipped:1}},{source_sha256:{}}]){
  fs.writeFileSync(file,JSON.stringify({...result,...change}));assert.throws(()=>verifyLinux(file,root));
 }
 const extra=path.join(root,'customer-workbench','tests','test_linux_automation_process.py');
 fs.mkdirSync(path.dirname(extra),{recursive:true});fs.writeFileSync(extra,code);
 result.source_sha256['test_linux_automation_process.py']=digest;
 fs.writeFileSync(file,JSON.stringify(result));assert.doesNotThrow(()=>verifyLinux(file,root,root));
 fs.appendFileSync(extra,'changed');assert.throws(()=>verifyLinux(file,root,root));
});
