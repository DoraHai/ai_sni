import {createOnsiteClient,onsiteTaskId} from './onsite-client.mjs';
import {onsiteView,onsiteCreateInput,onsiteActionInput,onsiteProposalMode} from './onsite-view.mjs';
import {createInputProtection} from './input-protection.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {customerOnsiteSummary} from './customer-onsite-summary.mjs';
export function mountGeoWorkbench({root,host,logout,initialOnsiteTaskId=null}){
  root.classList.add('customer-connected');let identity=null,data=null,selected=null,busy=false,message='',epoch=0,before=null;
  const protection=createInputProtection(root);
  const client=createOnsiteClient({transport:host.transport,getContext:host.getContext,module:'geo'});
  function render(){
    protection.setContext('geo-onsite:'+String(selected?.id||'list'));
    root.innerHTML=`<header><b>G-SNIPERS</b><span>客户工作台 · GEO</span><small>${identity?esc(identity.tenant.name+' / '+identity.project.name):'正在核验客户与项目'}</small><a href="/customer-workbench/">选择工作空间</a><button data-action="logout">退出登录</button></header><main class="connected-main"><p role="status">${esc(message)}</p><section id="page" class="page-card">${identity?(selected?'':customerOnsiteSummary(data,{module:'geo'}))+onsiteView(data,selected,busy,'geo'):`<h2>GEO 官网与知识建设</h2><button data-action="connect" ${busy?'disabled':''}>重新核验</button><a href="/customer-workbench/?module=geo">重新选择 GEO 项目</a>`}</section></main>`;
    protection.render();
  }
  async function run(fn){const input=protection.capture(),stamp=++epoch;busy=true;message='正在处理…';render();
    try{await fn(()=>stamp===epoch);if(stamp===epoch)message='';}
    catch(e){if(stamp===epoch){data=null;selected=null;client.invalidate();protection.recover(input);message=e.code==='WRITE_OUTCOME_UNKNOWN'?'操作结果未知，请先刷新核对。不会自动重试。':e.code==='PERMISSION_DENIED'?'权限已变化，请重新核验客户与项目。':e.message;}}
    finally{if(stamp===epoch){busy=false;render();}}
  }
  async function connect(){identity=null;data=null;selected=null;client.invalidate();protection.clear();await run(async current=>{
    const result=await host.initialize();if(current()){identity=result.identity;const focus=initialOnsiteTaskId??onsiteTaskId(globalThis.location?.search||'');
      before=focus?focus+1:null;const value=await client.list(before);if(current()){data=value;
        if(focus){selected=value.items.find(t=>t.id===focus)||null;if(!selected)throw Error('所选任务不可用，请顾问核对当前客户与项目。');}
      }
    }
  });}
  const unsubscribe=host.subscribe(()=>{epoch++;identity=null;data=null;selected=null;client.invalidate();protection.clear();busy=false;message='身份或客户范围已变化，旧数据已清除。';render();});
  async function click(event){
    const el=event.target.closest('[data-action]');if(!el||el.disabled)return;const a=el.dataset.action;
    if(a==='logout'){logout();return;}if(a==='connect'){await connect();return;}
    if(a==='restore-input'){protection.restore();return;}if(a==='discard-input'){protection.discardRecovery();render();return;}
    if(!a.startsWith('onsite-'))return;
    const action=a.slice(7);
    if(['select','refresh','next','latest'].includes(action)&&!protection.leave(action==='refresh'))return;
    if(action==='select'){selected=data?.items.find(t=>t.id===Number(el.dataset.id))||null;render();return;}
    if(['refresh','next','latest'].includes(action)){if(action==='next')before=Number(el.dataset.before);if(action==='latest')before=null;await run(async current=>{const result=await client.list(before);if(current()){data=result;selected=null;}});return;}
    let input;try{input=action==='create'?onsiteCreateInput(root,'geo'):onsiteActionInput(root,selected,action);}catch(e){message=e.message;render();return;}
    await run(async current=>{const result=action==='create'?await client.create(input):action==='ai-proposal'?await client.propose(selected.id,onsiteProposalMode(selected)):await client.act(selected.id,action,input);if(current()){selected=result;protection.saved();if(action==='create')before=null;const list=await client.list(before);if(current()){data=list;selected=list.items.find(t=>t.id===result.id)||null;}}});
  }
  root.addEventListener('click',click);void connect();
  return {dispose(){epoch++;unsubscribe();client.invalidate();protection.dispose();host.dispose();root.removeEventListener('click',click);root.replaceChildren();}};
}

