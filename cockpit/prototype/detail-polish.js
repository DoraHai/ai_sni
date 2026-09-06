/* Shared detail controls; navigation preserves the captured business scope. */
let detailSequence=null;
const polishDialog=showDialog;showDialog=function(...args){const d=$('#detailDialog');d.querySelector('.detail-fixed-actions')?.remove();d.classList.remove('unified-detail');detailSequence=null;polishDialog(...args);};
function polishDetail(kind,keys,current,scope,open){
 const d=$('#detailDialog'),body=$('#dialogBody'),actions=body.querySelector('.sem-depth-actions,.seo-actions');
 detailSequence={kind,keys,current,scope:{...scope},open};const index=keys.indexOf(current);
 const nav=document.createElement('nav');nav.className='detail-sequence';nav.setAttribute('aria-label','详情浏览');nav.innerHTML=`<span>${kind} · ${index+1} / ${keys.length}</span><div><button data-detail-step="-1" ${index<=0?'disabled':''} aria-label="查看上一个对象">← 上一个</button><button data-detail-step="1" ${index>=keys.length-1?'disabled':''} aria-label="查看下一个对象">下一个 →</button></div>`;body.prepend(nav);
 if(actions){actions.classList.add('detail-fixed-actions');d.append(actions);}d.classList.add('unified-detail');
 body.scrollTop=0;
}
const polishSem=semDepthOpen;semDepthOpen=function(id,scope=pSnapshot(),tab='summary'){polishSem(id,scope,tab);if(!$('#dialogBody .sem-depth'))return;polishDetail('SEM 关键词',semDepthKeywords(scope).map(x=>x.id),id,scope,(key,s)=>semDepthOpen(key,s));const footer=$('#detailDialog .detail-fixed-actions');footer.insertAdjacentHTML('beforeend','<button data-detail-sem-list>返回关键词列表</button>');};
const polishSeo=seoOpen;seoOpen=function(id,scope=pSnapshot(),tab='overview'){polishSeo(id,scope,tab);if(!$('#dialogBody .seo-depth'))return;const keys=pRows('content',scope).map(x=>x.id);if(!keys.includes(id))keys.push(id);polishDetail('SEO 文章',keys,id,scope,(key,s)=>seoOpen(key,s));};
const polishGeo=geoOpen;geoOpen=function(q,engine,scope=pSnapshot()){polishGeo(q,engine,scope);if(!$('#dialogBody .geo-depth'))return;const keys=geoQuestions.filter(x=>scope.topic==='all'||x.startsWith(scope.topic+'：'));polishDetail('GEO 问题',keys,q,scope,(key,s)=>geoOpen(key,engine,s));};
window.addEventListener('click',e=>{const b=e.target.closest('[data-detail-step],[data-detail-sem-list]');if(!b||!detailSequence)return;e.preventDefault();e.stopImmediatePropagation();const {keys,current,scope,open}=detailSequence;if(b.hasAttribute('data-detail-sem-list')){showDialog('SEM / 关键词列表',`<h2>哪些广告关键词值得关注</h2><p>${pScope(scope)} · 当前查看范围</p>${semDepthList(scope)}`);return;}const next=keys[keys.indexOf(current)+Number(b.dataset.detailStep)];if(next!==undefined)open(next,scope);},true);
