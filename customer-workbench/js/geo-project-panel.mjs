import {createGeoProjectClient} from './geo-project-client.mjs';
import {geoTabs,geoHome,geoResource,geoExecutions,geoStatus} from './geo-project-view.mjs';
import {escapeText as esc} from './customer-display.mjs';
export function createGeoProjectPanel({host,onNavigate=()=>{},canNavigate=()=>true}){
  const client=createGeoProjectClient({transport:host.transport,getContext:host.getContext});
  let node=null,epoch=0,disposed=false,tab='home',slots={},week=null,requestedWeek=null,active=null,history=[];
  const available=key=>!!slots[key]?.value;
  function tabs(){return geoTabs.filter(([key])=>key===tab||['home','onsite'].includes(key)||key==='work'&&(slots.questions?.value?.data.items.length>0||slots.content?.value?.data.items.length>0)||key==='content'&&slots.content?.value?.data.items.length>0||key==='deliveries'&&slots.deliveries?.value?.data.items.length>0||['progress','plan'].includes(key)&&available('executions')||key==='data'&&(available('visibility')||slots.questions?.value?.data.items.length>0));}
  function paint(){
    if(!node)return;
    const slot=active?.slot;
    let body=tab==='home'?geoHome(slots):tab==='onsite'?'<h2>站内优化</h2><p>月度站内计划与原有任务操作见下方。</p>':tab==='progress'||tab==='plan'?(slots.executions?.value?geoExecutions(slots.executions.value,tab==='plan'):`<h2>${tab==='plan'?'服务计划':'项目进度'}</h2><p>${geoStatus(slots.executions)}</p><button data-geo="refresh-executions">重新读取</button>`):active?(slot?.value?geoResource(active.resource,slot.value):`<p role="status">${geoStatus(slot)}</p>${slot?.loading?'':'<button data-geo="retry">重新读取</button>'}`):'<p>暂未开放</p>';
    if(tab==='work')body='<h2>GEO工作</h2><p>项目问题与内容任务；官网与知识建设见下方。</p><button data-geo="read" data-resource="questions">项目问题</button><button data-geo="read" data-resource="content">内容任务</button>'+body;
    const weekForm=tab==='data'?`<form data-geo-week><label>完整周结束日（上海周一） <input name="week_end" type="date" value="${esc(week||'')}" required></label><button>查看该周</button></form><p>正式指标来自已保存检测结果，历史按当前项目归属重算。</p><button data-geo="read" data-resource="visibility">AI 可见度概览</button><button data-geo="read" data-resource="questions">问题监测</button><button data-geo="read" data-resource="answers">回答证据</button>`:'';
    node.innerHTML=`<nav class="geo-tabs" aria-label="GEO 工作台">${tabs().map(([key,name])=>`<button data-geo="tab" data-tab="${key}" ${key===tab?'aria-current="page"':''}>${name}</button>`).join('')}</nav><section class="page-card geo-workspace">${tab==='home'?'<button data-geo="refresh">重新读取概览</button>':''}${weekForm}${history.length?'<button data-geo="back">返回上一层</button>':''}${body}${slot?.value&&slot.loading?'<p role="status">正在读取下一页…</p>':''}${slot?.value&&slot.error?`<p role="status">${geoStatus(slot)}</p><button data-geo="retry">重新读取</button>`:''}</section>`;
  }
  const weekly=resource=>['overview','visibility','questions','answers'].includes(resource.split('/')[0]);
  function paramsFor(resource,params){return {...params,...(weekly(resource)&&week?{week_end:week}:{})};}
  async function readSlot(resource,params={},target=null){
    const stamp=epoch,slot={loading:true,value:null,error:null};
    if(target)target.slot=slot;else slots[resource]=slot;
    paint();
    try{const value=await client.read(resource,params);if(disposed||stamp!==epoch)return;
      slot.value=value;if(weekly(resource)&&!week)week=value.basis.period.week_end;
    }catch(e){if(disposed||stamp!==epoch)return;slot.error=e.code||'GEO_READ_FAILED';}
    finally{if(!disposed&&stamp===epoch){slot.loading=false;paint();}}
    return slot;
  }
  async function refresh(){
    const stamp=++epoch;client.invalidate();slots={};active=null;history=[];week=requestedWeek;paint();
    await Promise.allSettled([readSlot('overview',week?{week_end:week}:{}),readSlot('executions')]);
    if(disposed||stamp!==epoch)return;
    await readSlot('visibility',week?{week_end:week}:{});
    if(disposed||stamp!==epoch)return;
    await Promise.allSettled(['questions','content','deliveries'].map(r=>readSlot(r,paramsFor(r,{}))));
    if(disposed||stamp!==epoch)return;
    if(tab!=='home'&&tab!=='onsite'&&tab!=='plan'&&tab!=='progress')await selectTab(tab);
  }
  function reset(){epoch++;client.invalidate();slots={};active=null;history=[];week=null;requestedWeek=null;tab='home';paint();}
  async function open(resource,params={},keepTab=false){
    if(active)history.push({tab,resource:active.resource,params:active.params,slot:active.slot});
    const next=resource.startsWith('content')?'content':resource==='deliveries'?'deliveries':'data';
    if(!keepTab&&tab!==next){tab=next;onNavigate(tab);}
    const target={resource,params:paramsFor(resource,params),slot:null};active=target;paint();
    await readSlot(resource,target.params,target);
  }
  async function selectTab(next){
    if(!geoTabs.some(([key])=>key===next))return;
    tab=next;active=null;history=[];onNavigate(tab);
    const resource={content:'content',work:'questions',data:'visibility',deliveries:'deliveries'}[tab];
    if(resource){active={resource,params:paramsFor(resource,{}),slot:slots[resource]||null};paint();if(!active.slot?.value)await readSlot(resource,active.params,active);}else paint();
  }
  async function more(){
    const target=active,p=target?.slot?.value?.data.pagination;if(!p?.has_more||target.slot.loading)return;
    const stamp=epoch,slot=target.slot;slot.loading=true;slot.error=null;paint();
    try{
      const value=await client.read(target.resource,{...target.params,cursor:p.next_cursor});if(disposed||stamp!==epoch||active!==target)return;
      const items=[...slot.value.data.items,...value.data.items];slot.value={...value,data:{...value.data,items}};
    }catch(e){if(disposed||stamp!==epoch||active!==target)return;
      if(['GEO_SCOPE_CHANGED','GEO_CURSOR_INVALID','GEO_NOT_OPEN'].includes(e.code)){
        target.slot={error:e.code,loading:false,value:null};history=[];
        if(e.code!=='GEO_NOT_OPEN')await readSlot(target.resource,target.params,target);
      }else slot.error=e.code||'GEO_READ_FAILED';
    }finally{if(!disposed&&stamp===epoch){slot.loading=false;paint();}}
  }
  async function click(event){
    const el=event.target.closest('[data-geo]');if(!el||el.disabled||!canNavigate())return;
    const action=el.dataset.geo;
    if(action==='tab')await selectTab(el.dataset.tab);
    if(action==='read'){let params={};try{params=JSON.parse(el.dataset.params||'{}');}catch{return;}await open(el.dataset.resource,params,tab==='work');}
    if(action==='back'){active=history.pop()||null;if(active?.tab&&tab!==active.tab){tab=active.tab;onNavigate(tab);}paint();}
    if(action==='refresh')await refresh();
    if(action==='refresh-executions')await readSlot('executions');
    if(action==='retry'&&active)await readSlot(active.resource,active.params,active);
    if(action==='more')await more();
  }
  async function submit(event){if(!event.target.matches('[data-geo-week]'))return;event.preventDefault();if(!canNavigate())return;requestedWeek=event.target.elements.week_end.value;await refresh();}
  return {refresh,reset,getTab:()=>tab,renderInto(element){node=element;node.onclick=click;node.onsubmit=submit;paint();},dispose(){disposed=true;reset();node=null;}};
}
