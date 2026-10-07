import {readCycles} from './seo-cycle-config.mjs';
// Exact-contract display mapping. Independent of development role switch.
export function contentDeliveryView(delivery) {
  const content=delivery.content,latest=delivery.confirmation.latest;
  const unavailable=delivery.confirmation.status==='unavailable'||delivery.workflow_status==='confirmation_unavailable';
  return {
    id:content.id,version:content.version_count,hash:content.payload_hash,body:content.body,
    workflowStatus:delivery.workflow_status,confirmationStatus:delivery.confirmation.status,
    actions:Object.entries(delivery.allowed_actions).filter(([key,allowed])=>allowed===true&&!(unavailable&&/^(confirm_|reject_|start_publication)/.test(key))).map(([key])=>key),
    confirmation:latest?{actorId:latest.actor_user_id,actorName:latest.actor_name||`用户${latest.actor_user_id}`,actorRoleName:latest.actor_role_name,
      mode:latest.actor_mode,label:latest.actor_mode==='advisor_proxy'?'顾问代确认':'客户本人确认',version:latest.content_version,at:latest.created_at}:null,
    resultBasis:delivery.result_basis,
    // Keep publication, capture and effect facts separate; confirmation does not set them.
    approvalIsPublication:false,
    capabilityMessage:unavailable?'确认接口不可用：数据库迁移/服务启用待管理员处理':null,
  };
}
export function serviceStatusView(status) {
  const labels={ready:'事实就绪',needs_attention:'存在缺项，需处理',not_ready:'尚未就绪',no_data:'暂无数据'};
  return Object.entries(status.phases).map(([id,phase])=>({id,state:phase.state,label:labels[phase.state],blockers:phase.blockers,facts:phase.facts,
    asOf:phase.as_of??null,readAt:status.read_at??null,evidenceEndpoints:status.evidence_endpoints??{},semantics:status.semantics??null,
    workflowStatus:null,waitingFor:null,history:null,completionEvidence:null,
  }));
}

export function servicePlanView(plan) {
  const denialMessages={
    advisor_assignment_schema_unavailable:'顾问分配能力尚未启用',
    authenticated_user_required:'需要实名登录',
    content_and_site_edit_permissions_required:'需要内容与网站编辑权限',
    active_site_advisor_assignment_required:'当前账号未分配为该站点顾问',
  };
  const canUpdate=plan.allowed_actions?.update_service_plan===true;
  const denialReason=plan.permission_basis?.update_denial_reason??null;
  return {
    tenantId:plan.tenant_id,siteId:plan.site_id,revision:plan.revision,status:plan.status,
    optimizationDirections:plan.optimization_directions??[],contentTopics:plan.content_topics??[],serviceNote:plan.service_note??null,
    updatedBy:plan.updated_by??null,updatedAt:plan.updated_at??null,cycles:readCycles(plan),
    canUpdate,permissionBasis:plan.permission_basis??null,denialReason,
    disabledMessage:canUpdate?null:denialMessages[denialReason]??'服务端尚未提供编辑资格，请重新读取服务计划',
  };
}
