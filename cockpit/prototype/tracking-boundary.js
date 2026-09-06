/* Observable channel results are not a cross-channel lead attribution model. */
function trackingStrip(){return `<section class="tracking-boundary" aria-label="效果如何统计"><span>效果追踪</span><button data-tracking="sem"><b>SEM</b> 部分转化可记录 <small>是否有效待确认 ↗</small></button><button data-tracking="seo"><b>SEO</b> 搜索与内容表现 <small>客户来源待确认 ↗</small></button><button data-tracking="geo"><b>GEO</b> 回答提及与引用 <small>客户来源待确认 ↗</small></button></section>`;}
const trackingRender=renderPanorama;renderPanorama=function(){trackingRender();panoPage.querySelector('.p-kpis')?.insertAdjacentHTML('afterend',trackingStrip());};
function trackingDetails(module){
  const names={sem:'SEM · 投放与报表转化',seo:'SEO · 搜索与内容',geo:'GEO · 品牌回答'};
  const observed={sem:'花费、展现、点击，以及已记录的报表转化。报表转化可能重复或不具备业务价值，追踪覆盖率未知。',seo:'抓取与修复进度、内容发布、收录与排名、可获取的自然搜索流量。当前原型展示其中已有演示记录的项目。',geo:'受测问题、回答引擎、品牌提及、引用来源与竞品出现。当前回答全部为模拟样本，正式指标仍为空。'};
  const missing={sem:'完整线索量、核实后的有效线索、成交金额与真实获客成本。',seo:'搜索点击或文章发布带来了多少咨询、有效线索与成交。',geo:'AI 回答中的提及或引用带来了多少访问、咨询与成交。'};
  showDialog('效果追踪 / 数字说明',`<h2>${names[module]}</h2><h3>可以观察</h3><p>${observed[module]}</p><h3>尚不能确认</h3><p>${missing[module]}</p><div class="evidence-note">尚未追踪 ≠ 没有效果。当前不计算各渠道合计的客户咨询数、获客贡献占比或整体投入回报。</div><h3>分两步检查</h3>${table(['步骤','检查什么'],[['工作完成','核对执行记录与复查证据，例如发布成功、修复通过、观测已采集。'],['指标变化','比较统计方法和日期范围相同的的点击、排名或回答覆盖；缺少可比数据时保留为空。']])}<p>指标改善不自动等于获客或成交改善。后续需补充咨询事件、来源标识、去重与业务核实，才能讨论确认咨询来自哪个渠道。</p><div class="dialog-footer"><span class="footnote">演示说明 · 尚未连接真实业务数据</span><button data-tracking-talk="${module}" class="secondary-button">结合当前数据讨论</button></div>`);
}
function trackingReply(question){const topic=panoramaData.topics.find(t=>question.includes(t));if(topic)pChange({topic});const scope=pSnapshot(),v=pStats(scope);const snapshotKey='tracking_'+panoSnapshots.size;panoSnapshots.set(snapshotKey,{...scope,card:'funnel'});showChat();addMessage('user',question);addMessage('assistant',`<p><strong>目前不能可靠给出各渠道合计的客户咨询数或整体投入回报。</strong></p><p>${pScope(scope)}：SEM 有 <strong>${v.conv} 次报表转化</strong>待核实；SEO 有 <strong>${pOrganic(v.organic)} 次搜索点击</strong>；GEO 有 <strong>${v.mentions}/${v.a.length} 条模拟回答提及品牌</strong>。</p><p>这三项分别是转化记录、访问表现和回答覆盖，不能相加为线索，也不能据此分配获客贡献。尚未追踪不代表没有效果。</p><p>建议先核实 SEM 已记录的转化；SEO、GEO 先检查工作有没有完成和可比较的指标变化，咨询来自哪里，还要补充记录。</p>`,[{label:'查看 SEM 转化记录',action:'panoTalk',key:'evidence~'+snapshotKey}]);
  chatReplyScope(snapshotKey);
}
const trackingBaseReply=reply;reply=function(question){if(/线索|商机|成交|ROI|投资回报|获客成本|获客贡献/i.test(question)){trackingReply(question);return;}trackingBaseReply(question);};
window.addEventListener('click',e=>{const button=e.target.closest('[data-tracking],[data-tracking-talk]');if(!button)return;e.preventDefault();e.stopImmediatePropagation();if(button.dataset.tracking)trackingDetails(button.dataset.tracking);else{closeDialog();trackingReply('这些渠道表现，能确认带来多少线索吗？');}},true);
renderPanorama();
