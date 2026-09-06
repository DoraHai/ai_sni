/* Customer-facing entry hierarchy; existing charts and object workflows stay available. */
let firstScreenNotesOpen=false;
const firstTracking=trackingStrip;trackingStrip=function(){return `<details class="first-data-notes" ${firstScreenNotesOpen?'open':''}><summary><span>这些数字怎么理解？</span><small>各渠道不能直接合算成客户数量</small></summary>${firstTracking()}</details>`;};
document.addEventListener('toggle',e=>{if(e.target.matches?.('.first-data-notes'))firstScreenNotesOpen=e.target.open;},true);
const firstSuggestions=pSuggestions;pSuggestions=function(...args){firstSuggestions(...args);$('#chatSuggestions').querySelectorAll('button').forEach(b=>{if(b.textContent==='整体情况怎么样？')b.textContent='看看推广效果';if(b.textContent==='优先处理什么？')b.textContent='今天先处理什么';});};
const firstReply=reply;reply=function(q){if(q==='看看推广效果')return firstReply('整体情况怎么样？');if(q==='今天先处理什么')return firstReply('优先处理什么？');return firstReply(q);};
const firstReset=resetChat;resetChat=function(...args){firstReset(...args);$('#chatStream').replaceChildren();addMessage('assistant',`<div class="first-welcome"><small>一起看清效果，安排下一步</small><h2>今天先看什么？</h2><p>可以直接提问，也可以点开右侧数据，让我围绕它继续分析。</p><div class="first-starts"><button data-first-start="overview"><b>看看推广效果</b><span>广告、内容、AI 回答 ↗</span></button><button data-first-start="priority"><b>今天先处理什么</b><span>看看待办，安排下一步 ↗</span></button></div></div>`);pSuggestions();$('#chatStream').scrollTop=0;};
window.addEventListener('click',e=>{const b=e.target.closest('[data-first-start]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();if(b.dataset.firstStart==='overview')pTalk('overview','看看推广效果');else pTalk('plan','今天先处理什么');},true);
const firstRender=renderPanorama;renderPanorama=function(){firstRender();const heading=panoPage.querySelector('.p-heading h1');if(heading)heading.textContent='推广有进展，待办及时跟进。';};
const firstMessage=addMessage;addMessage=function(...args){firstMessage(...args);$('#assistant').classList.toggle('welcome-only',$('#chatStream').children.length===1&&!!$('#chatStream .first-welcome'));};
renderPanorama();resetChat();
