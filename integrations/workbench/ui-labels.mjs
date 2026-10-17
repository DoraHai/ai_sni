// Presentation only: these labels must never drive access or workflow decisions.
const states={paused:'已暂停',archived:'已归档',active:'已启用',trial:'试用中',suspended:'已停用',disabled:'已停用',doing:'进行中',in_progress:'进行中',expired:'已过期',closed:'已关闭',reserved:'预留待启用'};
const codes={HUMAN_PUBLISHED:'已登记人工发布',PREFLIGHT_OK:'发布预检通过',HANDOFF_READY:'交接资料已备好',HUMAN_HANDOFF:'已交接人工处理',HANDOFF_OK:'人工交接完成',SUCCESS:'操作完成',OK:'操作完成',FAILED:'操作失败',UNKNOWN:'结果待核对',
 preflight:'发布预检',handoff:'人工交接',publish:'人工发布授权',create:'创建',update:'更新',configure:'更新配置',receipt:'登记回执',revoke:'撤销授权',resolve:'登记核查结果'};
export const stateLabel=(value,fallback='状态待核对')=>Object.hasOwn(states,value)?states[value]:fallback;
export const codeLabel=value=>Object.hasOwn(codes,value)?codes[value]:/[\u4e00-\u9fff]/.test(value||'')?value:'操作记录待核对';
export const shortIdentifier=value=>String(value??'').length>20?String(value).slice(0,8)+'…'+String(value).slice(-6):String(value??'');
