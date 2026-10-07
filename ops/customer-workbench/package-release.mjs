// Creates a local, immutable four-file artifact. Never uploads or activates it.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const digest=data=>createHash('sha256').update(data).digest('hex');
const expectedNames=['app.css','app.js','index.html','release-manifest.json'];
const plain=value=>value&&typeof value==='object'&&!Array.isArray(value);
export function verifyPayload(files, expectedCommit) {
  if(!/^[a-f0-9]{40}$/.test(expectedCommit))throw Error('A full reviewed Git commit is required');
  if([...files.keys()].sort().join('|')!==expectedNames.join('|'))throw Error('Unexpected or missing release file');
  const manifest=JSON.parse(files.get('release-manifest.json').toString('utf8'));
  if(manifest.schema!==1||manifest.base!=='/customer-workbench/'||manifest.sourceTreeClean!==true||manifest.upstreamCommit!==expectedCommit)throw Error('Manifest is not a clean build of the requested commit');
  if(!plain(manifest.files)||Object.keys(manifest.files).sort().join('|')!=='app.css|app.js|index.html')throw Error('Invalid manifest file set');
  for(const name of ['app.css','app.js','index.html']){
    const data=files.get(name),entry=manifest.files[name];
    if(!Buffer.isBuffer(data)||!data.length||data.length>32*1024*1024||entry?.bytes!==data.length||entry.sha256!==digest(data))throw Error('Payload digest or size mismatch: '+name);
  }
  return manifest;
}

export async function packageRelease({repo,commit,outputRoot}) {
  const git=(...args)=>execFileSync('git',['-C',repo,...args],{encoding:'utf8'}).trim();
  if(git('rev-parse','HEAD')!==commit)throw Error('Checkout does not match requested commit');
  if(git('status','--porcelain'))throw Error('Commit changes before creating a release');
  execFileSync(process.execPath,[path.join(repo,'customer-workbench/scripts/build.mjs')],{stdio:'pipe'});
  if(git('rev-parse','HEAD')!==commit||git('status','--porcelain'))throw Error('Source changed during build');
  const source=path.join(repo,'customer-workbench/dist/customer-workbench');
  const names=(await fs.readdir(source)).sort();
  if(names.join('|')!==expectedNames.join('|'))throw Error('Unexpected build output');
  const files=new Map();
  for(const name of names){const p=path.join(source,name),stat=await fs.lstat(p);if(!stat.isFile()||stat.isSymbolicLink()||stat.size>32*1024*1024)throw Error('Invalid build file');files.set(name,await fs.readFile(p));}
  verifyPayload(files,commit);
  await fs.mkdir(outputRoot,{recursive:true});
  const output=await fs.mkdtemp(path.join(path.resolve(outputRoot),'customer-workbench-'+commit.slice(0,12)+'-'));
  const stage=path.join(output,'customer-workbench');await fs.mkdir(stage);
  for(const [name,data] of files)await fs.writeFile(path.join(stage,name),data,{flag:'wx'});
  const archive=path.join(output,'customer-workbench-'+commit+'.tgz');
  execFileSync('tar',['-czf',archive,'-C',output,'customer-workbench'],{stdio:'pipe'});
  const sha256=digest(await fs.readFile(archive));
  await fs.writeFile(path.join(output,'SHA256SUMS'),`${sha256}  ${path.basename(archive)}\n`,{flag:'wx'});
  const result={commit,archive,sha256,files:expectedNames,activation:'not-run',migration:'not-run'};
  await fs.writeFile(path.join(output,'release-summary.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  return result;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
  const [commit,outputRoot=path.join(os.tmpdir(),'gsnipers-workbench-releases')]=process.argv.slice(2);
  if(!commit||!/^[a-f0-9]{40}$/.test(commit))throw Error('Usage: node ops/customer-workbench/package-release.mjs FULL_COMMIT [OUTPUT_DIRECTORY]');
  console.log(JSON.stringify(await packageRelease({repo,commit,outputRoot}),null,2));
}
