// Offline fixed-path transport proof. No credentials in stdin, argv or output.
import {readFile} from 'node:fs/promises';
import https from 'node:https';
const chunks=[];let size=0;for await(const part of process.stdin){size+=part.length;if(size>16384)throw Error('INPUT_TOO_LARGE');chunks.push(part);}
try {
 const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
 if(Object.keys(input).sort().join(',')!=='bindingIds,deviceId,expectedRevision,expiresAt,origin,requestId')throw Error('INVALID_INPUT');
 const origin=new URL(input.origin);if(origin.protocol!=='https:'||origin.hostname!=='127.0.0.1'||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)throw Error('LOOPBACK_ONLY');
 const credential=process.env.MHT_DISTRIBUTION_DEVICE_TOKEN;if(!credential||/[\r\n]/.test(credential))throw Error('CREDENTIAL_REQUIRED');
 const fixture=JSON.parse(await readFile(new URL('../docs/fixtures/distribution-capability-registration-v1.json',import.meta.url),'utf8'));
 const body=JSON.stringify({...fixture.request,deviceId:input.deviceId,bindingIds:input.bindingIds,expectedRevision:input.expectedRevision,expiresAt:input.expiresAt,requestId:input.requestId});
 const result=await new Promise((resolve,reject)=>{const req=https.request(new URL(fixture.registerPath,origin),{method:'POST',headers:{Authorization:'Bearer '+credential,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)},timeout:10000},res=>{const data=[];let n=0;res.on('data',chunk=>{n+=chunk.length;if(n>65536){req.destroy();reject(Error('RESPONSE_TOO_LARGE'));}else data.push(chunk);});res.on('end',()=>{if(res.statusCode!==200)return reject(Error('REGISTRATION_REJECTED'));try{resolve(JSON.parse(Buffer.concat(data).toString('utf8')));}catch{reject(Error('INVALID_RESPONSE'));}});});req.on('error',reject);req.on('timeout',()=>req.destroy(Error('TIMEOUT')));req.end(body);});
 if(result.capabilityVersion!==1||result.deviceId!==input.deviceId||result.automaticSubmit!==false||result.publicationVerified!==false||!result.active||result.allowedBindings.some(b=>b.stages.join(',')!=='preflight,handoff'))throw Error('INVALID_RESPONSE');
 process.stdout.write(JSON.stringify(result)+'\n');
} catch {process.stdout.write(JSON.stringify({phase:'registration-failed'})+'\n');process.exitCode=1;}
