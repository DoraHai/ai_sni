/* Group existing views without changing their data or hiding capabilities. */
const dashboardGroups=[
  {id:'performance',label:'趋势与投入',note:'看变化，核对投放与搜索表现',cards:['trend','organic','mix','funnel','device']},
  {id:'presence',label:'内容与品牌',note:'看产出，追查排名与回答依据',cards:['content','ranking','heatmap','citations','competition','journey']},
  {id:'delivery',label:'待办与结果',note:'看进度，确认剩余工作与证据',cards:['execution','health']}
];
function dashboardArrange(){
  const grid=panoPage.querySelector('.p-grid');if(!grid)return;
  grid.querySelectorAll('.dashboard-group').forEach(el=>el.remove());
  const nav=document.createElement('nav');nav.className='dashboard-jumps';nav.setAttribute('aria-label','定位看板分区');
  panoPage.querySelector('.dashboard-jumps')?.remove();
  for(const group of dashboardGroups){
    const cards=group.cards.map(key=>grid.querySelector(`[data-card="${key}"]`)).filter(Boolean);
    const visible=cards.filter(card=>!card.hidden);if(!visible.length)continue;
    const heading=document.createElement('div');heading.className='dashboard-group';heading.id='group-'+group.id;
    heading.innerHTML=`<div><span>${String(dashboardGroups.indexOf(group)+1).padStart(2,'0')}</span><h2>${group.label}</h2><small>${group.note}</small></div><button data-dashboard-jump="top" aria-label="返回经营总览">回到总览 ↑</button>`;
    grid.append(heading);cards.forEach(card=>{grid.append(card);card.tabIndex=0;card.setAttribute('aria-label',panoCards[card.dataset.card][1]+'，按回车展开分析');});
    const jump=document.createElement('button');jump.dataset.dashboardJump=group.id;jump.innerHTML=`${group.label}<small>${visible.length}</small>`;nav.append(jump);
  }
  grid.before(nav);
}
const hierarchyRender=renderPanorama;renderPanorama=function(){hierarchyRender();dashboardArrange();};
// Decision views can update the visible cards without rendering the whole page.
const hierarchyDecision=dRender;dRender=function(){hierarchyDecision();dashboardArrange();};
window.addEventListener('click',e=>{
  const button=e.target.closest('[data-dashboard-jump]');if(!button)return;
  e.preventDefault();e.stopImmediatePropagation();
  const key=button.dataset.dashboardJump,page=$('#pageScroll');
  if(key==='top'){page.scrollTo({top:0,behavior:fluidReduced()?'instant':'smooth'});return;}
  const heading=panoPage.querySelector('#group-'+key);if(!heading)return;
  const offset=panoPage.querySelector('.command-strip')?.getBoundingClientRect().height||0;
  page.scrollTo({top:page.scrollTop+heading.getBoundingClientRect().top-page.getBoundingClientRect().top-offset-36,behavior:fluidReduced()?'instant':'smooth'});
},true);
window.addEventListener('keydown',e=>{
  const card=e.target.closest('.p-card');if(!card||e.target!==card)return;
  if(e.key==='Enter'){e.preventDefault();fluidToggle(card.dataset.card);}
  if(e.key===' '){e.preventDefault();pano.focus=card.dataset.card;panoPage.querySelectorAll('.p-card').forEach(el=>el.classList.toggle('is-focused',el===card));pContext();const label=$('#commandTarget');if(label)label.textContent=panoCards[pano.focus][1];}
});
renderPanorama();
