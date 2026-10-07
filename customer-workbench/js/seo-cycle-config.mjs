export const cycleFields={content_cycle_enabled:false,content_interval_days:7,website_cycle_enabled:false,website_interval_days:7,website_max_pages:5,monitoring_cycle_enabled:false,monitoring_interval_days:1,report_cycle_enabled:false};
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
  return `<fieldset><legend>服务周期 · 默认关闭</legend><p>仅显式保存才更新配置；进入页面不会开启周期或采集。关闭只停止新任务，不取消现有任务；暂停停止新动作，已开始请求仍可保存事实。</p>${check('content_cycle_enabled','内容周期')}${number('content_interval_days','内容间隔（天，1–90）',90)}<p>自动建立选题与任务；顾问制作、内审、选择渠道和发布/回填，客户或顾问确认准确稿件。</p>${check('website_cycle_enabled','网站诊断周期')}${number('website_interval_days','网站间隔（天，1–90）',90)}${number('website_max_pages','每轮最多已登记页面（1–10）',10)}<p>仅本站已登记页面，逐个诊断并占用现有配额；网站修改由人工实施，真实复检后接续，失败单页需顾问显式重试。</p>${check('monitoring_cycle_enabled','监测异常周期',!keywordEdit)}${number('monitoring_interval_days','监测间隔（天，1–30）',30,!keywordEdit)}<p>只评估已有排名观测，最多200个active关键词；不新发付费排名请求。开启需关键词编辑权限，异常要靠新观测解决。</p>${check('report_cycle_enabled','周期月报')}<p>上一个已结束北京时间自然月，冻结HTML和哈希；顾问补说明，不生成/发送PDF，不要求客户签收。缺数保留缺数。</p></fieldset>`;
}
