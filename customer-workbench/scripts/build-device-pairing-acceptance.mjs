import {build} from 'esbuild';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'dist/device-pairing-acceptance');
const sha=value=>createHash('sha256').update(value).digest('hex');
const commit=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
if(execFileSync('git',['-C',root,'status','--porcelain'],{encoding:'utf8'}).trim())throw Error('Clean committed acceptance source required');
const result=await build({absWorkingDir:root,entryPoints:['js/device-pairing-acceptance-entry.mjs'],bundle:true,write:false,format:'esm',platform:'browser',target:['es2022'],minify:true,metafile:true,
 alias:{'@existing-host/session':path.resolve(root,'../frontend/src/store/session.js'),vue:path.join(root,'node_modules/vue/dist/vue.runtime.esm-bundler.js')},
 define:{'import.meta.env.DEV':'false','import.meta.env.VITE_AUTH_ORIGIN':'""','process.env.NODE_ENV':'"production"','__VUE_OPTIONS_API__':'false','__VUE_PROD_DEVTOOLS__':'false','__VUE_PROD_HYDRATION_MISMATCH_DETAILS__':'false'}});
const files={
 'app.js':result.outputFiles[0].contents,
 'index.html':Buffer.from('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>独立验收 · 设备配对</title><link rel="stylesheet" href="/customer-workbench/app.css"></head><body><main id="app"></main><script type="module" src="./app.js"></script></body></html>'),
};
const sources={};for(const input of Object.keys(result.metafile.inputs)){const file=path.resolve(root,input);if(!file.includes(path.sep+'node_modules'+path.sep))sources[path.relative(root,file).replaceAll('\\','/')]=sha(await fs.readFile(file));}
files['manifest.json']=Buffer.from(JSON.stringify({schema:1,sourceCommit:commit,sourceTreeClean:true,production:false,sources,files:Object.fromEntries(Object.entries(files).map(([name,value])=>[name,{sha256:sha(value),bytes:value.length}]))},null,2));
await fs.mkdir(output,{recursive:true});for(const name of await fs.readdir(output))if(!(name in files))throw Error('Foreign acceptance artifact');
for(const [name,value]of Object.entries(files))await fs.writeFile(path.join(output,name),value);
console.log(JSON.stringify({sourceCommit:commit,output,production:false}));
