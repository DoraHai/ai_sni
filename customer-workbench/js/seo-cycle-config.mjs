export const cycleFields={content_cycle_enabled:false,content_interval_days:7,website_cycle_enabled:false,website_incremental_enabled:false,website_interval_days:7,website_max_pages:5,monitoring_cycle_enabled:false,monitoring_interval_days:1,report_cycle_enabled:false,analytics_cycle_enabled:false};
export function readCycles(plan){return Object.fromEntries(Object.entries(cycleFields).map(([k,v])=>[k,plan[k]??v]));}
export function validateCycles(input){
  if(!input||Object.keys(input).some(k=>!(k in cycleFields)))throw Error('INVALID_CYCLE_CONFIG');
  for(const [k,value] of Object.entries(input)){
    const max=k==='website_max_pages'?10:k==='monitoring_interval_days'?30:90;
    if(k.endsWith('_enabled')?typeof value!=='boolean':!Number.isSafeInteger(value)||value<1||value>max)throw Error('INVALID_CYCLE_CONFIG');
  }
  return input;
}
export function cycleForm(values,disabled,keywordEdit){
  const check=(key,label,extra=false)=>`<label><input type="checkbox" data-cycle="${key}" ${values[key]===true?'checked':''} ${disabled||extra?'disabled':''}>${label}</label>`;
  const number=(key,label,max,extra=false)=>`<label>${label}<input type="number" data-cycle="${key}" min="1" max="${max}" value="${Number.isSafeInteger(values[key])?values[key]:cycleFields[key]}" ${disabled||extra?'disabled':''}></label>`;
  return `<fieldset><legend>服务周期 · 默认关闭</legend><p>仅显式保存才更新配置；进入页面不会开启周期或采集。关闭只停止新任务，不取消现有任务；暂停停止新动作；统计取数返回后会再次检查权限和范围。</p>${check('content_cycle_enabled','内容周期')}${number('content_interval_days','内容间隔（天，1–90）',90)}<p>自动建立选题与任务；按已保存AI授权或由顾问制作；顾问内审、选择渠道和发布/回填，客户或顾问确认准确稿件。</p>${check('website_cycle_enabled','网站诊断周期')}${check('website_incremental_enabled','自动发现页面与增量检查')}${number('website_interval_days','网站间隔（天，1–90）',90)}${number('website_max_pages','每轮最多检查页面（1–10）',10)}<p>开启增量检查后，通过本站站点地图与已检查页面的内链自动登记新页面，优先检查未检查页面并轮流复查旧页面，比较历史快照。仅授权域名及www入口，遵守robots和现有配额（站点地图读取也计入）；每轮最多发现200条、清单最多5000页，达到上限会显示。诊断完成不代表整改完成，网站修改仍由人工实施；发现或检查失败由顾问明确接续/重试。未开启时只检查已登记页面。</p>${check('monitoring_cycle_enabled','监测异常周期',!keywordEdit)}${number('monitoring_interval_days','监测间隔（天，1–30）',30,!keywordEdit)}<p>只评估已有排名观测，最多200个active关键词；不新发付费排名请求。开启需关键词编辑权限，异常要靠新观测解决。</p>${check('analytics_cycle_enabled','周期统计取数')}<p>使用本站已授权的数据源，每日更新本月、补齐上月。授权异常进入顾问待办；不把缺数写成0。</p>${check('report_cycle_enabled','周期月报')}<p>开启月报也会取数。先准备上一个已结束的北京时间自然月数据，再冻结HTML和哈希；授权失败由顾问重试，或明确生成注明缺项的报告。顾问补说明，不生成/发送PDF，不要求客户签收。</p></fieldset>`;
}
