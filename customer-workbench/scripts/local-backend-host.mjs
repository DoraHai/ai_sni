import http from 'node:http';import https from 'node:https';import fs from 'node:fs/promises';import path from 'node:path';import os from 'node:os';
import {fileURLToPath} from 'node:url';import {execFileSync} from 'node:child_process';import {createHash,X509Certificate} from 'node:crypto';import {build} from 'esbuild';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const sha=value=>createHash('sha256').update(value).digest('hex');
export function loopbackBackend(value){
  const url=new URL(value);
  if(!['http:','https:'].includes(url.protocol)||!['127.0.0.1','[::1]'].includes(url.hostname)||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw Error('Explicit loopback backend origin required');
  return url;
}
export async function createLocalTls(){
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'workbench-ui12-tls-'));
  const cleanup=async()=>{for(const name of ['cert.pem','key.pem'])await fs.rm(path.join(directory,name),{force:true});await fs.rmdir(directory);};
  try{
    execFileSync('pwsh',['-NoProfile','-NonInteractive','-File',path.join(root,'scripts/local-tls.ps1'),'-OutputDirectory',directory],{stdio:'pipe',windowsHide:true});
    const cert=await fs.readFile(path.join(directory,'cert.pem')),key=await fs.readFile(path.join(directory,'key.pem'));
    const publicKey=new X509Certificate(cert).publicKey.export({type:'spki',format:'der'});
    return {cert,key,spki:createHash('sha256').update(publicKey).digest('base64'),cleanup};
  }catch(error){await cleanup();throw error;}
}
async function localAssets(){
  const dist=path.join(root,'dist/customer-workbench'),manifest=JSON.parse(await fs.readFile(path.join(dist,'release-manifest.json'),'utf8')),assets=new Map();
  const types={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','app.css':'text/css; charset=utf-8'};
  for(const [name,type] of Object.entries(types)){
    const bytes=await fs.readFile(path.join(dist,name));if(sha(bytes)!==manifest.files[name]?.sha256)throw Error('Build hash mismatch: '+name);
    assets.set('/customer-workbench/'+name,{bytes,type});
  }
  const host=path.resolve(root,'../frontend');
  for(const [name,hash] of Object.entries(manifest.canonicalSources))if(sha(await fs.readFile(path.join(host,name)))!==hash)throw Error('Host session source mismatch: '+name);
  const bundle=await build({absWorkingDir:root,entryPoints:['tests/local-login-entry.mjs'],bundle:true,write:false,format:'esm',platform:'browser',target:'es2022',alias:{'@existing-host/session':path.join(host,'src/store/session.js'),vue:path.join(root,'node_modules/vue/dist/vue.runtime.esm-bundler.js')},define:{'process.env.NODE_ENV':'"production"','__VUE_OPTIONS_API__':'false','__VUE_PROD_DEVTOOLS__':'false','__VUE_PROD_HYDRATION_MISMATCH_DETAILS__':'false'}});
  assets.set('/__local/login.js',{bytes:bundle.outputFiles[0].contents,type:types['app.js']});
  assets.set('/login',{type:types['index.html'],bytes:Buffer.from('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>UI-12 本机登录接线</title><h1>本机合成账号登录</h1><p>真实登录API与原session.setAuth；这是测试宿主页，不是原LoginView整页验收。</p><form><label>账号 <input name="username" autocomplete="off" required></label><label>密码 <input name="password" type="password" autocomplete="off" required></label><button>登录并返回工作台</button></form><button id="local-logout">清空原会话</button><p role="status"></p><script type="module" src="/__local/login.js"></script></html>')});
  return {assets,manifest};
}
export async function startLocalBackendHost({backendOrigin,port=0,tls}={}){
  const upstream=loopbackBackend(backendOrigin),{assets,manifest}=await localAssets(),ownedTls=!tls;
  tls??=await createLocalTls();const calls=[];let origin;
  const server=https.createServer({key:tls.key,cert:tls.cert},(req,res)=>{
    const reply=(status,message)=>{res.writeHead(status,{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'});res.end(message);};
    if(req.headers.host!==new URL(origin).host)return reply(421,'Local host mismatch');
    if(!req.url?.startsWith('/')||req.url.startsWith('//')||/[\\\r\n]/.test(req.url))return reply(400,'Invalid local path');
    const url=new URL(req.url,origin);
    if(url.pathname.startsWith('/api/')){
      if(!/^\/api\/v1\/(?:auth|seo)\//.test(url.pathname))return reply(404,'Unsupported API namespace');
      if((req.headers.origin&&req.headers.origin!==origin)||req.headers['sec-fetch-site']==='cross-site')return reply(403,'Cross-origin request rejected');
      if(!['GET','HEAD'].includes(req.method)&&req.headers.origin!==origin)return reply(403,'Same-origin write required');
      const headers={};for(const name of ['authorization','accept','content-type','content-length','if-none-match'])if(req.headers[name])headers[name]=req.headers[name];
      // Literal loopback origin; never follow redirects, retry, inject identity or synthesize API data.
      const outgoing=(upstream.protocol==='https:'?https:http).request(new URL(url.pathname+url.search,upstream),{method:req.method,headers,timeout:60000},response=>{
        calls.push({method:req.method,path:url.pathname,status:response.statusCode});
        const responseHeaders={'Cache-Control':'no-store'};for(const name of ['content-type','content-length','content-encoding','etag','content-disposition'])if(response.headers[name])responseHeaders[name]=response.headers[name];
        // Do not forward Location/Set-Cookie from a test backend to unrelated hosts or storage.
        res.writeHead(response.statusCode,responseHeaders);response.pipe(res);response.on('error',()=>res.destroy());
      });
      outgoing.on('timeout',()=>outgoing.destroy(Error('Local backend timeout')));
      outgoing.on('error',()=>{calls.push({method:req.method,path:url.pathname,status:502});if(!res.headersSent)reply(502,'Local backend connection failed');else res.destroy();});
      req.on('aborted',()=>outgoing.destroy());res.on('close',()=>{if(!res.writableEnded)outgoing.destroy();});req.pipe(outgoing);return;
    }
    if(req.method!=='GET'&&req.method!=='HEAD')return reply(405,'Read-only static host');
    const asset=assets.get(url.pathname==='/customer-workbench/'?'/customer-workbench/index.html':url.pathname);
    if(!asset)return reply(404,'Local route not mounted');
    res.writeHead(200,{'Content-Type':asset.type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(req.method==='HEAD'?undefined:asset.bytes);
  });
  try{await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});origin=`https://127.0.0.1:${server.address().port}`;}catch(error){if(ownedTls)await tls.cleanup();throw error;}
  return {origin,backendOrigin:upstream.origin,spki:tls.spki,manifest,calls,async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});if(ownedTls)await tls.cleanup();}};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const host=await startLocalBackendHost({backendOrigin:process.env.UI12_BACKEND_ORIGIN,port:Number(process.env.UI12_PORT||0)});
  console.log(JSON.stringify({origin:host.origin,backendOrigin:host.backendOrigin,buildCommit:host.manifest.upstreamCommit,sourceTreeClean:host.manifest.sourceTreeClean,certificateSpki:host.spki,notice:'Local host only; backend integration not yet verified'},null,2));
  for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{await host.close();process.exit(0);});
}
