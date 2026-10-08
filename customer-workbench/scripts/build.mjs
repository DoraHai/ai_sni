import {build} from 'esbuild';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const hostRoot=await fs.realpath(path.resolve(root,'../frontend')),output=path.join(root,'dist','customer-workbench');
const sources=['src/store/session.js','src/store/sessionStorage.js'];
const sha=data=>createHash('sha256').update(data).digest('hex');
const upstreamCommit=execFileSync('git',['-C',hostRoot,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const sourceTreeClean=!execFileSync('git',['-C',root,'status','--porcelain','--','.'],{encoding:'utf8'}).trim();
const dirty=execFileSync('git',['-C',hostRoot,'status','--porcelain','--',...sources,'package-lock.json'],{encoding:'utf8'}).trim();
if(dirty)throw Error('Canonical session/login sources or host lockfile are modified. Commit/review upstream first.');
const hostLock=JSON.parse(await fs.readFile(path.join(hostRoot,'package-lock.json'),'utf8'));
const ownLock=JSON.parse(await fs.readFile(path.join(root,'package-lock.json'),'utf8'));
const vueVersion=ownLock.packages['node_modules/vue'].version;
if(hostLock.packages['node_modules/vue']?.version!==vueVersion)throw Error('Vue lock versions differ; align the independent lock with the reviewed host lock.');
const sourceHashes=Object.fromEntries(await Promise.all(sources.map(async name=>[name,sha(await fs.readFile(path.join(hostRoot,name)))])));
// Existing output is never recursively deleted. An explicit known-file allowlist owns it.
await fs.mkdir(output,{recursive:true});
const built=await build({
  absWorkingDir:root,entryPoints:['js/production-entry.mjs'],bundle:true,write:false,
  outdir:output,format:'esm',platform:'browser',target:['es2022'],minify:true,
  sourcemap:false,metafile:true,legalComments:'eof',
  alias:{'@existing-host/session':path.join(hostRoot,sources[0]),vue:path.join(root,'node_modules/vue/dist/vue.runtime.esm-bundler.js')},
  define:{'import.meta.env.DEV':'false','import.meta.env.VITE_AUTH_ORIGIN':'""','process.env.NODE_ENV':'"production"','__VUE_OPTIONS_API__':'false','__VUE_PROD_DEVTOOLS__':'false','__VUE_PROD_HYDRATION_MISMATCH_DETAILS__':'false'},
});
const inputs=Object.keys(built.metafile.inputs);
if(inputs.some(p=>/(?:^|\/)(?:fixture[^/]*|adapter\.js|workbench\.js)$/.test(p)))throw Error('Demo/fixture code entered production graph.');
for(const name of sources)if(!inputs.some(p=>path.resolve(root,p)===path.join(hostRoot,name)))throw Error('Missing canonical source: '+name);
for(const name of sources)if(sha(await fs.readFile(path.join(hostRoot,name)))!==sourceHashes[name])throw Error('Canonical source changed during build.');
const js=built.outputFiles.find(f=>f.path.endsWith('.js')).contents;
const css=await Promise.all(['r12-base.css','workbench.css','connected.css'].map(name=>fs.readFile(path.join(root,'css',name))));
const files=new Map([
  ['app.js',js],['app.css',Buffer.concat(css.map(data=>Buffer.concat([data,Buffer.from('\n')])))] ,
  ['index.html',Buffer.from('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>客户工作台</title><link rel="stylesheet" href="./app.css"></head><body><div id="app"></div><script type="module" src="./app.js"></script></body></html>')],
]);
const localSources={};
for(const input of inputs){const full=path.resolve(root,input);if(full.startsWith(root+path.sep)&&!full.includes(path.sep+'node_modules'+path.sep))localSources[path.relative(root,full).replaceAll('\\','/')]=sha(await fs.readFile(full));}
for(const name of ['scripts/build.mjs','css/r12-base.css','css/workbench.css','css/connected.css'])localSources[name]=sha(await fs.readFile(path.join(root,name)));
const manifest={schema:1,base:'/customer-workbench/',upstreamCommit,sourceTreeClean,canonicalSources:sourceHashes,localSources,hostLockSha256:sha(await fs.readFile(path.join(hostRoot,'package-lock.json'))),independentLockSha256:sha(await fs.readFile(path.join(root,'package-lock.json'))),vueVersion,files:Object.fromEntries([...files].map(([name,data])=>[name,{sha256:sha(data),bytes:data.length}]))};
files.set('release-manifest.json',Buffer.from(JSON.stringify(manifest,null,2)+'\n'));
for(const name of await fs.readdir(output))if(!files.has(name))throw Error('Unexpected output file; inspect manually: '+name);
for(const [name,data] of files)await fs.writeFile(path.join(output,name),data);
console.log(JSON.stringify({output,upstreamCommit,vueVersion,files:[...files.keys()]},null,2));
