import {servicePlanView} from './seo-contract-view.mjs';

// Connected-page state only. No development role, fallback fixtures or credentials.
export function createServicePlanController(client) {
  const initial=()=>({phase:'idle',view:null,canSave:false,saved:false,error:null,message:'尚未连接或读取服务计划'});
  let state=initial(),generation=0;
  function errorState(error) {
    const message=error.code==='service_plan_version_conflict'?'版本已变化，请重新读取后再保存'
      :error.status===403?'顾问资格或权限已变化，请重新读取'
      :error.code==='NOT_CONNECTED'?'未连接宿主身份'
      :error.code==='WRITE_OUTCOME_UNKNOWN'?'保存结果未知，请重新读取核对，不自动重试'
      :error.status===503?'服务能力尚未启用，请联系管理员'
      :'未取得可核实的保存结果，请重新读取';
    return {phase:error.code==='NOT_CONNECTED'?'disconnected':'error',view:null,canSave:false,saved:false,error:{code:error.code,status:error.status},message};
  }
  async function run(phase,action) {
    if(['loading','saving'].includes(state.phase))throw Error('OPERATION_IN_PROGRESS');
    const operation=++generation;
    state={...state,phase,canSave:false,saved:false,error:null,message:phase==='saving'?'正在保存，等待服务器结果':'正在读取'};
    try {
      const data=await action();
      if(operation!==generation)throw Error('VIEW_INVALIDATED');
      const view=servicePlanView(data);
      state={phase:phase==='saving'?'saved':'ready',view,canSave:phase!=='saving'&&view.canUpdate,saved:phase==='saving',error:null,
        message:phase==='saving'?'服务计划已由服务器保存；再次编辑前需重新读取资格':view.disabledMessage??'服务计划已读取'};
      return data;
    } catch(error) {if(operation===generation)state=errorState(error);throw error;}
  }
  return {
    getState(){return structuredClone(state);},
    invalidate(){generation++;client.invalidate();state=initial();},
    load(){return run('loading',()=>client.servicePlan());},
    async save(input){
      if(!state.canSave){const error=Error('PLAN_UPDATE_NOT_ALLOWED');error.code='PLAN_UPDATE_NOT_ALLOWED';throw error;}
      return run('saving',()=>client.saveServicePlan(input));
    },
  };
}
