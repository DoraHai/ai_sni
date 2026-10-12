// Loopback integration harness imports the owner's frozen artifacts unchanged.
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
try{
 const p=JSON.parse(Buffer.concat(chunks).toString());
 if(new URL(p.origin).hostname!=='127.0.0.1')throw Error('LOOPBACK_REQUIRED');
 const snapshot=JSON.parse(await readFile(join(p.snapshot,'snapshot.json'),'utf8'));
 if(snapshot.source_commit!==p.sourceCommit)throw Error('SOURCE_MISMATCH');
 for(const a of snapshot.artifacts){const bytes=await readFile(join(p.snapshot,a.name));if(createHash('sha256').update(bytes).digest('hex')!==a.sha256)throw Error('ARTIFACT_MISMATCH');}
 const {CapabilityClient}=await import(pathToFileURL(join(p.snapshot,'capability-client.mjs')).href);
 const credential=()=>process.env.MHT_DISTRIBUTION_DEVICE_TOKEN;
 const capability=new CapabilityClient(join(p.root,'capability.db'),p.origin,p.deviceId,credential);
 let agent;
 try{
  let result;
  if(p.phase==='register')result=await capability.register(p.registration);
  else if(p.phase==='renew')result=await capability.renew();
  else if(p.phase==='revoke')result=await capability.revoke();
  else{
   const {DistributionAgent,HttpsDistributionTransport,HumanHandoffExecutor}=await import(pathToFileURL(join(p.snapshot,'agent.mjs')).href);
   const human=new HumanHandoffExecutor();
   // Deliberate offline executor fault exercises the actual durable unknown path.
   const executor=p.phase==='unknown'?{execute:async()=>{throw Error('SYNTHETIC_EXECUTOR_FAILURE')}}:human;
   agent=new DistributionAgent(p.deviceId,join(p.root,'agent.db'),new HttpsDistributionTransport(p.origin,credential),executor);
   agent.start();
   if(p.phase==='complete')await agent.resolveHuman(p.task.grantId,p.task.id,p.task.content.version,p.task.contentDigest,'handoff-complete',null);
   for(let i=0;i<3;i++)await agent.tick();
   result=agent.tasks().map(t=>({id:t.id,task:t,outboxPayload:agent.db.prepare('SELECT payload FROM distribution_outbox WHERE receipt_id=?').get(agent.receipt(t.id).receiptId)?.payload??null,isolatedOutbox:agent.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='distribution_outbox_isolation'").get()?agent.db.prepare("SELECT i.payload,EXISTS(SELECT 1 FROM distribution_outbox o WHERE o.receipt_id=i.receipt_id AND o.payload=i.payload) AS retained FROM distribution_outbox_isolation i WHERE json_extract(i.payload,'$.taskId')=?").all(t.id):[],authorizationAllowed:agent.allowed(t),audit:agent.db.prepare('SELECT receipt FROM distribution_audit WHERE task_id=? ORDER BY id').all(t.id),resolution:agent.db.prepare('SELECT payload FROM distribution_resolutions WHERE task_id=? AND lease_id=?').get(t.id,t.leaseId)??null,outboxPending:!!agent.db.prepare('SELECT 1 FROM distribution_outbox WHERE receipt_id=?').get(agent.receipt(t.id).receiptId),receipt:agent.receipt(t.id),job:agent.jobViews(t.grantId).find(j=>j.taskId===t.id)}));
  }
  process.stdout.write(JSON.stringify(result)+'\n');
 }finally{if(agent)await agent.close();await capability.close();}
}catch{process.stdout.write(JSON.stringify({phase:'pair-failed'})+'\n');process.exitCode=1;}
