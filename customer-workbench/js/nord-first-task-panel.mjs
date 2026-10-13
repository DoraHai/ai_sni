import {escapeText as esc} from './customer-display.mjs';
import {createDistributionClient} from './distribution-client.mjs';
const scope={module:'seo',tenant_id:1,scope_id:1},base='/api/distribution/nord/v1/first-task';
const uuid=v=>typeof v==='string'&&/^[a-f0-9-]{36}$/.test(v),sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v),positive=v=>Number.isSafeInteger(v)&&v>0;
export function createNordFirstTaskPanel({session,fetchImpl,browser,onChange}){
  const broker=createDistributionClient({session,fetchImpl});
  let binding=null,draft=null,source=null,busy=false,notice='',disposed=false,epoch=0,unknown=false,unknownStage='',coverUrl=null,tasks=[];
  const key=()=>JSON.stringify([session.token,session.user?.id,session.user?.tenant_id,session.authRevision,session.user?.permissions]);let stamp=key();
  function reset(){epoch++;draft=null;source=null;binding=null;tasks=[];unknown=false;busy=false;if(coverUrl)browser.URL.revokeObjectURL(coverUrl);coverUrl=null;}
  const identity=()=>({device_id:binding.device_id,external_account_id:binding.external_account_id});
  async function request(path,{body,binary=false}={}){
    const g=epoch,k=key();if(!session.token||session.user?.tenant_id!==null||!['settings.accounts','settings.customers','seo.content','seo.site'].every(p=>session.user?.permissions?.[p]==='edit'))throw Error('PERMISSION_DENIED');
    const method=body?'POST':'GET';
    let r;try{r=await fetchImpl(path,{method,headers:{Authorization:'Bearer '+session.token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),credentials:'omit',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000)});}catch{throw Error(body?'WRITE_OUTCOME_UNKNOWN':'READ_FAILED');}
    if(g!==epoch||k!==key())throw Error(body?'WRITE_OUTCOME_UNKNOWN':'CONTEXT_CHANGED');
    if(!r.ok){const e=Error(body&&r.status>=500?'WRITE_OUTCOME_UNKNOWN':'REQUEST_FAILED');e.status=r.status;throw e;}
    const v=binary?await r.blob():await r.json();if(g!==epoch||k!==key())throw Error(body?'WRITE_OUTCOME_UNKNOWN':'CONTEXT_CHANGED');return v;
  }
  function validate(v){
    if(v.schema!==1||typeof v.prepared!=='boolean'||v.automatic_publish!==false||v.published!==false)throw Error('CONTRACT_MISMATCH');
    if(v.prepared&&(!positive(v.content_id)||!positive(v.variant_id)||!uuid(v.binding_id)||typeof v.title!=='string'||typeof v.body!=='string'||v.body.length>100000||!positive(v.master_version)||!sha(v.master_hash)||typeof v.master_confirmed!=='boolean'||!v.preview||v.preview.variant_id!==v.variant_id||v.preview.platform!=='wechat-article'||!sha(v.preview.edit_token)||!Array.isArray(v.preview.assets)||v.preview.assets.length>1))throw Error('CONTRACT_MISMATCH');
    return v;
  }
  async function read(){
    if(!binding)return;draft=validate(await request(base+'?'+new URLSearchParams(identity())));source=null;
    if(coverUrl)browser.URL.revokeObjectURL(coverUrl);coverUrl=null;
    if(draft.prepared){
      const a=draft.preview.assets[0];if(a){
        if(!uuid(a.id)||!sha(a.sha256)||!positive(a.bytes)||a.bytes>20000000||!['image/png','image/jpeg'].includes(a.mediaType))throw Error('CONTRACT_MISMATCH');
        const blob=await request('/api/seo/distribution-media/variants/'+draft.variant_id+'/assets/'+a.id+'?tenant_id=1&site_id=1',{binary:true});
        const hash=[...new Uint8Array(await browser.crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('');
        if(blob.size!==a.bytes||blob.type!==a.mediaType||hash!==a.sha256)throw Error('ASSET_MISMATCH');coverUrl=browser.URL.createObjectURL(blob);
      }
      if(draft.master_confirmed&&draft.preview.status==='approved')source=await broker.preview(scope,draft.variant_id,'wechat-article');
      tasks=(await broker.tasks(scope)).items.filter(t=>t.binding_id===binding.id&&t.variant_id===draft.variant_id);
    }
  }
  async function work(fn){if(busy||disposed)return;const g=epoch;busy=true;onChange();try{await fn();if(g!==epoch||disposed)return;await read();notice='已读取当前任务状态。';}catch(e){if(g!==epoch||disposed)return;if(e.message==='WRITE_OUTCOME_UNKNOWN')unknown=true;notice=unknown?'写入结果待核对，请只刷新状态；不要重复下发。':'当前步骤未完成，请刷新核对账号接入或稿件门禁。';}finally{if(g===epoch){busy=false;onChange();}}}
  return {
    html(){
      if(key()!==stamp){stamp=key();reset();}if(!binding)return '';
      const current=tasks.find(t=>t.action==='publish'&&!t.revoked);
      return `<section><h3>诺德首条完整任务</h3><p role="status">${esc(notice)}</p><button type="button" data-nord-task="refresh" ${busy?'disabled':''}>刷新接入与任务状态</button>${!draft?.prepared?`<p>选型稿和封面已准备，点击后保存为待审稿。</p><button type="button" data-nord-task="prepare" ${busy||unknown?'disabled':''}>准备诺德待审稿与封面</button>`:`<h4>${esc(draft.title)}</h4><pre style="white-space:pre-wrap;line-height:1.8">${esc(draft.body)}</pre>${coverUrl?`<img src="${esc(coverUrl)}" alt="当前待审核封面" style="max-width:100%;height:auto">`:''}<p>母稿：${esc({drafting:'待审核',review:'待审核',ready:'已审核',published:'已发布'}[draft.master_status]||draft.master_status)} · 顾问代确认：${draft.master_confirmed?'已确认':'待确认'} · 正文与封面：${draft.preview.status==='approved'?'已由独立顾问审核冻结':'待另一位顾问审核'}</p>${!draft.master_confirmed?`<button type="button" data-nord-task="master-review" ${busy||unknown?'disabled':''}>已核对全文，确认母稿审核并完成顾问代确认</button>`:''}<p><a href="/api/seo/distribution-media/workspace?tenant_id=1&site_id=1&variant_id=${draft.variant_id}">请另一位已分配顾问打开正文与封面审核</a></p>${source&&!current?`<button type="button" data-nord-task="dispatch" ${busy||unknown?'disabled':''}>确认允许本机人工发表，并下发这一条任务</button>`:''}${current?`<p>任务：${esc(current.id)} · ${esc({queued:'已下发，等待电脑领取',leased:'电脑已领取',running:'执行中','awaiting-human':'等待人工发表',succeeded:'已有执行回执，仍需核验发布事实',unknown:'结果待核对',failed:'执行失败',canceled:'已取消'}[current.status]||current.status)}</p><p>公开链接与原模块回写状态请在顾问分发记录中核验。</p>`:''}`}</section>`;
    },
    updateBindings(rows){
      if(key()!==stamp){stamp=key();reset();}
      const matches=rows.filter(v=>v.active&&v.device_active&&v.module==='seo'&&v.tenant_id===1&&v.scope_id===1&&v.platform==='wechat-article'&&/^gh_[a-f0-9]{12}$/.test(v.external_account_id));
      const next=matches.length===1?matches[0]:null;if(next?.id===binding?.id)return;reset();binding=next;if(binding)void work(async()=>{});
    },
    click(event){
      const b=event.target.closest('[data-nord-task]');if(!b||b.disabled)return false;const action=b.dataset.nordTask;
      if(action==='refresh')void work(async()=>{await read();if(unknownStage==='prepare'&&draft.prepared||unknownStage==='master-review'&&draft.master_confirmed||unknownStage==='dispatch'&&tasks.some(t=>t.action==='publish'&&!t.revoked))unknown=false;});
      if(action==='prepare'&&!unknown){unknownStage=action;void work(async()=>{draft=validate(await request(base+'/prepare',{body:{...identity(),prepare_unreviewed_draft:true}}));});}
      if(action==='master-review'&&draft?.prepared&&!unknown){unknownStage=action;void work(async()=>{draft=validate(await request(base+'/master-review',{body:{...identity(),content_id:draft.content_id,expected_version:draft.master_version,expected_hash:draft.master_hash,confirm_full_content:true,confirm_advisor_proxy:true}}));});}
      if(action==='dispatch'&&source&&!unknown){unknownStage=action;void work(async()=>{
        const preview=source,project=(await broker.scope(scope)).project;
        if(project.state==='paused')await broker.control(scope,project.revision?'resume':'start',project.revision,browser.crypto.randomUUID());
        await broker.enqueue(scope,{bindingId:binding.id,preview,action:'publish',confirmManual:true,requestId:browser.crypto.randomUUID()});
      });}return true;
    },
    invalidate:reset,
    dispose(){disposed=true;reset();broker.dispose();},
  };
}
