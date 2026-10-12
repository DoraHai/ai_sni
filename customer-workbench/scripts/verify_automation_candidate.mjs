// Read-only local release audit. This never connects to a server or applies SQL.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const sharedFiles=['app/automation_projects.py','app/automation_project_contract.py','app/automation_project_v2.py',
  'scripts/automation_projects_schema.sql','scripts/automation_projects_v2_schema.sql','scripts/automation_projects_permissions.sql'];
const git=(root,...args)=>execFileSync('git',['-C',root,...args],{encoding:'utf8'}).trim();
const load=file=>JSON.parse(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,''));
const requireCheck=(condition,message)=>{if(!condition)throw Error(message);};

export function checkedFile(root,name){
  requireCheck(typeof name==='string'&&!path.isAbsolute(name)&&!name.includes('\\')&&
    name.split('/').every(part=>part&&part!=='.'&&part!=='..'),'Unsafe artifact path');
  const base=fs.realpathSync(root),file=fs.realpathSync(path.join(base,name));
  requireCheck(file.startsWith(base+path.sep),'Artifact leaves its source root');
  return fs.readFileSync(file);
}

export function verifyBuild(root,commit){
  const workbench=path.join(root,'customer-workbench'),build=path.join(workbench,'dist','customer-workbench');
  const manifest=load(path.join(build,'release-manifest.json'));
  requireCheck(manifest.schema===1&&manifest.upstreamCommit===commit&&manifest.sourceTreeClean===true,'Build revision/clean source mismatch');
  requireCheck(Object.keys(manifest.files??{}).sort().join(',')==='app.css,app.js,index.html','Unexpected release file set');
  for(const [name,expected] of Object.entries(manifest.files)){
    const bytes=checkedFile(build,name);
    requireCheck(sha(bytes)===expected.sha256&&bytes.length===expected.bytes,'Build digest mismatch: '+name);
  }
  requireCheck(Object.keys(manifest.canonicalSources??{}).sort().join(',')==='src/store/session.js,src/store/sessionStorage.js','Unexpected host sources');
  for(const [name,expected] of Object.entries(manifest.canonicalSources))
    requireCheck(sha(checkedFile(path.join(root,'frontend'),name))===expected,'Host source mismatch: '+name);
  requireCheck(Object.keys(manifest.localSources??{}).length===62,'Frozen local source set must contain all 62 inputs');
  for(const name of ['js/production-entry.mjs','scripts/build.mjs','css/r12-base.css','css/workbench.css','css/connected.css','css/platform-console.css','css/advisor-workbench.css'])
    requireCheck(name in manifest.localSources,'Critical build input missing: '+name);
  for(const [name,expected] of Object.entries(manifest.localSources)){
    requireCheck(/^(?:js|css|scripts)\/[A-Za-z0-9._/-]+\.(?:mjs|js|css)$/.test(name),'Invalid local source name');
    requireCheck(sha(checkedFile(workbench,name))===expected,'Local source mismatch: '+name);
  }
  requireCheck(sha(checkedFile(path.join(root,'frontend'),'package-lock.json'))===manifest.hostLockSha256,'Host lock mismatch');
  requireCheck(sha(checkedFile(workbench,'package-lock.json'))===manifest.independentLockSha256,'Workbench lock mismatch');
  return {commit,files:3,local_sources:Object.keys(manifest.localSources).length,canonical_sources:2,
    manifest_sha256:sha(fs.readFileSync(path.join(build,'release-manifest.json')))};
}

export function verifyHttp(file,commit){
  const raw=fs.readFileSync(file),sample=JSON.parse(raw.toString('utf8').replace(/^\uFEFF/,''));
  requireCheck(sample.backend_commit===commit&&sample.source_tree_clean===true,'HTTP sample revision/clean source mismatch');
  const responses=[...Object.values(sample.responses??{}),...(sample.scenarios??[])];
  requireCheck(responses.length>0,'HTTP response evidence missing');
  requireCheck(responses.every(response=>response.headers?.['cache-control']==='no-store'),'HTTP evidence must be no-store');
  return {backend_commit:commit,sha256:sha(raw),source:sample.source??null,response_snapshots:responses.length,
    note:'Replay snapshots; not additional independent tests or deployed-service evidence.'};
}

export function verifyLinux(file,geoRoot,advisorRoot){
  const result=load(file);
  requireCheck(result.schema===1&&result.platform==='Linux'&&result.test_exit_code===0&&
    result.counts?.tests>0&&result.counts.failures===0&&result.counts.errors===0&&result.counts.skipped===0,'Linux evidence is not a passing native run');
  for(const name of ['app/geo/scheduler.py','app/geo/scheduler_observability.py',
    'tests/test_geo_followup_scheduler.py','tests/test_geo_scheduler.py',
    'tests/test_geo_scheduler_observability.py','tests/test_geo_scheduler_eligibility.py']){
    // Export attributes and Windows checkouts can use CRLF while Git blobs
    // use LF. Accept only the exact bytes or these two newline encodings.
    const bytes=checkedFile(geoRoot,name),lf=bytes.toString('utf8').replace(/\r\n/g,'\n');
    requireCheck([sha(bytes),sha(lf),sha(lf.replace(/\n/g,'\r\n'))].includes(result.source_sha256?.[name]),'Linux source mismatch: '+name);
  }
  if(advisorRoot)requireCheck(result.source_sha256?.['test_linux_automation_process.py']===sha(checkedFile(advisorRoot,'customer-workbench/tests/test_linux_automation_process.py')),'Linux supplemental test source mismatch');
  requireCheck(result.network_io_permitted===false&&result.database_operations===false&&result.production_approval===false,'Unexpected Linux test scope');
  return {kernel:result.kernel,python:result.python,counts:result.counts,sha256:sha(fs.readFileSync(file)),scope:result.scope,
    production_dependency_parity_verified:false};
}

export function audit(options){
  const roots=Object.fromEntries(['advisor','seo','geo','platform'].map(module=>[module,fs.realpathSync(options[module])]));
  const sources={};
  for(const [module,root] of Object.entries(roots)){
    requireCheck(!git(root,'status','--porcelain'),'Uncommitted source changes: '+module);
    sources[module]={commit:git(root,'rev-parse','HEAD'),branch:git(root,'branch','--show-current'),clean:true};
  }
  const shared=sharedFiles.map(file=>{
    const seo=git(roots.seo,'rev-parse','HEAD:'+file),geo=git(roots.geo,'rev-parse','HEAD:'+file);
    requireCheck(seo===geo,'Shared implementation mismatch: '+file);
    return {file,blob:seo};
  });
  const build=verifyBuild(roots.advisor,sources.advisor.commit);
  const http={};
  for(const module of ['seo','geo'])if(options[module+'Http'])http[module]=verifyHttp(options[module+'Http'],sources[module].commit);
  const linux=options.linux?verifyLinux(options.linux,roots.geo,roots.advisor):null;
  return {schema:1,captured_at:new Date().toISOString(),sources,build,shared,http,linux,
    local_artifacts_verified:true,production_release_approved:false,
    remaining_release_gates:['Independent migration and runtime-role review.',
      'Production versions, live queue and deployed-process health.',
      'Current model/business-plan review and an explicitly scoped pilot.',
      'Compatible rollback rehearsal preserving owned operations and uncertain charges.'],
    policy:{sem_ai_takeover:false,website_writes:'reserved',automatic_publication:'reserved',owner_handoff:'out_of_scope'}};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    const args=process.argv.slice(2),options={};
    const names={'--advisor':'advisor','--seo':'seo','--geo':'geo','--platform':'platform',
      '--seo-http':'seoHttp','--geo-http':'geoHttp','--linux':'linux','--report':'report'};
    for(let i=0;i<args.length;i+=2){requireCheck(names[args[i]]&&args[i+1],'Unknown or incomplete argument');options[names[args[i]]]=args[i+1];}
    requireCheck(['advisor','seo','geo','platform','report'].every(key=>options[key]),'Four roots and --report required');
    const result=audit(options);fs.writeFileSync(options.report,JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify({local_artifacts_verified:true,production_release_approved:false,sources:result.sources,report:options.report}));
  }catch(error){console.error(error.message);process.exitCode=1;}
}
