import {createSearchVisibilityClient,visibilityAdvisor} from './search-visibility-client.mjs';
import {renderSearchVisibility} from './search-visibility-view.mjs';
export function createSearchVisibilityPanel({host,getUser,document=globalThis.document}){
  const client=createSearchVisibilityClient({transport:host.transport,getContext:host.getContext});
  let node=null,epoch=0,disposed=false,timer=null;
  const empty=()=>({data:null,draft:null,suggestions:[],configOpen:false,busy:false,message:''});
  let state=empty();
  const advisor=()=>visibilityAdvisor(getUser());
  const errorText=e=>({AUTH_EXPIRED:'登录已过期，请重新登录。',PERMISSION_DENIED:'权限已变化，请重新核验客户与项目。',CONTEXT_CHANGED:'身份或项目已变化，请重新核验。'}[e.code]||e.message||'暂时无法完成，请刷新核对。');
  const cancel=()=>{clearTimeout(timer);timer=null;};
  function paint(){if(node)node.innerHTML=renderSearchVisibility(state,{advisor:advisor()});}
  function poll(){cancel();if(['pending','running'].includes(state.data?.latest?.status))timer=setTimeout(()=>{
    if(!disposed&&!state.configOpen&&document.visibilityState!=='hidden')void refresh(false);else poll();
  },3000);}
  async function refresh(config=false){
    const started=++epoch;cancel();state.busy=true;state.message='';paint();
    try{
      const data=await client.overview();if(disposed||started!==epoch)return;state.data=data;
      if(advisor()&&(config||!state.draft)){
        try{
          const result=await client.config();if(disposed||started!==epoch)return;
          state.draft=result.config;state.suggestions=result.suggested_core_terms||[];
        }catch(e){if(disposed||started!==epoch)return;state.draft=null;state.suggestions=[];
          state.message='检查结果已读取，项目设置暂时打不开。'+errorText(e);}
      }
    }catch(e){if(disposed||started!==epoch)return;state.data=null;state.message=errorText(e);}
    finally{if(!disposed&&started===epoch){state.busy=false;paint();poll();}}
  }
  async function action(event){
    const button=event.target.closest('[data-sv]');if(!button||button.disabled||state.busy)return;
    const a=button.dataset.sv;
    if(a==='config'){state.configOpen=!state.configOpen;paint();return;}
    if(a.startsWith('suggest-')){const word=state.suggestions[Number(a.slice(8))];
      if(word){const rows=Array.isArray(state.draft.core_terms)?state.draft.core_terms:String(state.draft.core_terms||'').split('\n');state.draft.core_terms=[...new Set([...rows.filter(Boolean),word])];paint();}return;}
    if(a==='refresh'){await refresh(false);return;}
    const started=epoch;state.busy=true;state.message='';paint();
    try{
      if(a==='run'){
        const result=await client.run();if(disposed||started!==epoch)return;
        if(result.state==='not_enabled')state.message='待启用，请先核对项目开关和搜索服务。';
        else {state.data={...(state.data||{}),state:'ready',latest:result.job,weeks:state.data?.weeks||[]};state.message='已排队，正在读取检查进度。';}
      }else if(a==='csv'){
        const blob=await client.csv(state.data.latest.id);if(disposed||started!==epoch)return;
        const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='DeepSeek搜索可见度.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }
    }catch(e){if(!disposed&&started===epoch)state.message=errorText(e);}
    finally{if(!disposed&&started===epoch){state.busy=false;paint();poll();}}
  }
  function input(event){const field=event.target.dataset.svField;if(!state.draft||!field)return;
    state.draft[field]=event.target.type==='checkbox'?event.target.checked:event.target.value;
  }
  async function submit(event){event.preventDefault();if(!advisor()||state.busy)return;
    const started=epoch;state.busy=true;state.message='';paint();
    try{const result=await client.save(state.draft);if(disposed||started!==epoch)return;state.draft=result.config;state.message='项目设置已保存。';
      const data=await client.overview();if(disposed||started!==epoch)return;state.data=data;
    }catch(e){if(!disposed&&started===epoch)state.message=errorText(e);}
    finally{if(!disposed&&started===epoch){state.busy=false;paint();poll();}}
  }
  return {
    renderInto(element){node=element;if(node){node.onclick=action;node.oninput=input;node.onchange=input;node.onsubmit=submit;paint();}},
    refresh,
    reset(){epoch++;cancel();state=empty();paint();},
    dispose(){disposed=true;epoch++;cancel();node=null;},
  };
}
