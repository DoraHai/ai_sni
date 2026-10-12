import test from 'node:test';
import assert from 'node:assert/strict';
import {verifyPairingAdmin} from './js/device-pairing-acceptance-auth.mjs';
const admin=id=>({id,tenant_id:null,permissions:{'settings.accounts':'edit','settings.customers':'edit'}});
test('late administrator response cannot validate a different token or account',async()=>{
 const session={token:'old-token',user:admin(1),authRevision:1};let resolve;
 const pending=verifyPairingAdmin({session,fetchImpl:()=>new Promise(r=>resolve=r)});
 session.token='new-token';session.user={id:2,tenant_id:15,permissions:{}};session.authRevision++;
 resolve({ok:true,json:async()=>({user:admin(1)})});
 await assert.rejects(pending,/CONTEXT_CHANGED/);assert.equal(session.user.id,2);
});
test('identity change while decoding me cannot return old administrator data',async()=>{
 const session={token:'old-token',user:admin(1),authRevision:1};let resolve,decoding;
 const decoded=new Promise(r=>decoding=r);
 const pending=verifyPairingAdmin({session,fetchImpl:async()=>({ok:true,json:()=>{decoding();return new Promise(r=>resolve=r);}})});
 await decoded;session.token='new-token';session.authRevision++;
 resolve({user:admin(1)});await assert.rejects(pending,/CONTEXT_CHANGED/);
});
test('matching token with mismatched server account cannot validate administrator state',async()=>{
 const session={token:'token',user:admin(1),authRevision:1};
 await assert.rejects(verifyPairingAdmin({session,fetchImpl:async()=>({ok:true,json:async()=>({user:admin(2)})})}),/ADMIN_REQUIRED/);
});
