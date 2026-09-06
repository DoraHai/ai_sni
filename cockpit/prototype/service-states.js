/* Isolated UX state preview: never calls services or changes business records. */
let servicePreview={module:'sem',state:'loading',note:''};
const serviceLabels={sem:'广告投放',seo:'内容与搜索',geo:'AI 品牌表现'};
const serviceStateLabels={loading:'加载中',connection:'连接失败',empty:'暂无数据',permission:'权限不足',operation:'操作失败'};
function servicePreviewBody(){const s=servicePreview.state,button=(label,next)=>`<button class="seo-entry" data-service-next="${next}">${label}</button>`;
 if(s==='loading')return `<div class="service-placeholder" aria-hidden="true"><i></i><i></i><i></i></div><h3>正在获取数据</h3><p>这里演示等待状态，还没有返回可用数据。不会把等待显示成 0。</p>${button('模拟收到数据','success')}${button('取消等待','cancelled')}`;
 if(s==='connection')return `<h3>暂时连不上数据服务</h3><p>现在无法确认最新数据。当前也没有可展示的历史记录，请稍后再试。</p>${button('重试连接（演示）','loading')}`;
 if(s==='empty')return `<h3>这个范围内暂时没有记录</h3><p>没有记录不代表没有效果，也不等于结果为 0。可以换一个日期范围再查看。</p>${button('模拟查看更大日期范围','loading')}`;
 if(s==='permission')return `<h3>当前账号还不能查看这些数据</h3><p>请让管理这个客户的管理员检查账号权限。重复刷新不会解决权限问题。</p><details><summary>需要请管理员确认什么？</summary><p>客户：诺德新材料；模块：${serviceLabels[servicePreview.module]}。请确认账号是否已加入该客户，并开通相应数据的查看权限。本演示不会发送申请或修改权限。</p></details>`;
 if(s==='operation')return `<h3>这次操作没有完成</h3><p>你填写的说明已保留。实际接入后，系统应先查明上次是否已执行，避免重复提交。</p><label>补充说明<textarea id="serviceNote" rows="3" placeholder="例如：请先检查这批记录">${esc(servicePreview.note)}</textarea></label>${button('查看重试确认','confirm')}`;
 if(s==='confirm')return `<h3>确认重试这项演示操作？</h3><p>对象：${serviceLabels[servicePreview.module]} / 示例检查任务。</p><p>已填写：${esc(servicePreview.note||'未补充说明')}</p><p>本演示设定上次未执行。确认后只展示成功页面，不提交真实任务。</p>${button('确认模拟重试','done')}${button('返回修改','operation')}`;
 if(s==='done')return '<h3>模拟操作已完成</h3><p>说明已保留；这只是操作结果演示，不表示推广效果已提升，也没有新建真实待办。</p>';
 if(s==='cancelled')return `<h3>已取消等待</h3><p>没有修改数据，也没有继续尝试连接。</p>${button('重新开始加载演示','loading')}`;
 const stats=pStats(),value=servicePreview.module==='sem'?money(stats.cost):servicePreview.module==='seo'?pOrganic(stats.organic):`${stats.mentions}/${stats.a.length}`,label=servicePreview.module==='sem'?'投放花费':servicePreview.module==='seo'?'搜索点击':'模拟回答提到品牌';
 return `<h3>已显示演示数据</h3><div class="service-value"><b>${value}</b><span>${label}</span></div><p>${pScope()} · 来自当前原型记录，没有连接真实服务。</p>`;
}
function servicePreviewRender(){showDialog('使用状态演示 / 不影响当前数据',`<div class="service-preview"><h2>遇到这些情况时，怎么继续？</h2><p>这是独立演示窗口，不代表当前服务真的发生故障。</p><div class="service-controls"><label>模块<select id="serviceModule">${Object.entries(serviceLabels).map(([k,v])=>`<option value="${k}" ${k===servicePreview.module?'selected':''}>${v}</option>`).join('')}</select></label><label>查看情况<select id="serviceState">${Object.entries(serviceStateLabels).map(([k,v])=>`<option value="${k}" ${k===servicePreview.state?'selected':''}>${v}</option>`).join('')}${!serviceStateLabels[servicePreview.state]?`<option selected value="${servicePreview.state}">当前演示结果</option>`:''}</select></label></div><section class="service-status" role="status">${servicePreviewBody()}</section><button class="seo-entry" data-action="closeDialog">结束演示，返回工作台</button></div>`);}
const serviceRender=renderPanorama;renderPanorama=function(){serviceRender();panoPage.querySelector('.p-controls')?.insertAdjacentHTML('beforeend','<button data-service-preview>使用状态演示</button>');};
document.addEventListener('input',e=>{if(e.target.id==='serviceNote')servicePreview.note=e.target.value;});
document.addEventListener('change',e=>{if(e.target.id==='serviceModule'){servicePreview.module=e.target.value;servicePreviewRender();}if(e.target.id==='serviceState'){servicePreview.state=e.target.value;servicePreviewRender();}});
window.addEventListener('click',e=>{const b=e.target.closest('[data-service-preview],[data-service-next]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();if(b.hasAttribute('data-service-preview'))servicePreview={module:'sem',state:'loading',note:''};else servicePreview.state=b.dataset.serviceNext;servicePreviewRender();},true);
renderPanorama();
