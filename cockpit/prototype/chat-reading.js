/* Preserve reading position; long answers start expanded so evidence stays visible. */
const chatReadingStream=$('#chatStream');
chatReadingStream.tabIndex=0;
const chatLatest=document.createElement('button');
chatLatest.className='chat-latest';
chatLatest.type='button';
chatLatest.hidden=true;
chatLatest.textContent='↓ 回到最新消息';
chatLatest.setAttribute('aria-label','回到最新消息');
chatReadingStream.after(chatLatest);
let chatUnread=0;
function chatNearBottom(){return chatReadingStream.scrollHeight-chatReadingStream.scrollTop-chatReadingStream.clientHeight<64;}
function chatReadingStatus(){const near=chatNearBottom();if(near)chatUnread=0;chatLatest.hidden=near;chatLatest.textContent=chatUnread?'↓ 查看最新回复':'↓ 回到最新消息';}
chatReadingStream.addEventListener('scroll',chatReadingStatus,{passive:true});
chatLatest.addEventListener('click',()=>{chatReadingStream.scrollTo({top:chatReadingStream.scrollHeight,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});
function chatMakeFoldable(item){
  if(!item.classList.contains('assistant-message'))return;
  const body=item.children[1];
  if(!body||body.innerText.length<240||body.querySelector('form,input,textarea'))return;
  const fold=document.createElement('details');fold.className='chat-answer';fold.open=true;
  const summary=document.createElement('summary');
  const title=body.querySelector('h2,h3,p')?.textContent.trim()||'完整回答';
  const label=document.createElement('span');label.textContent=title.length>64?title.slice(0,64)+'…':title;
  const hint=document.createElement('small');hint.textContent='收起回答';
  summary.append(label,hint);fold.append(summary);body.before(fold);fold.append(body);
  const actions=item.querySelector(':scope > .message-actions');if(actions)fold.append(actions);
  fold.addEventListener('toggle',()=>{hint.textContent=fold.open?'收起回答':'展开回答与操作';chatReadingStatus();});
}
const chatReadingAdd=addMessage;
addMessage=function(role,html,actions=[]){
  const top=chatReadingStream.scrollTop;
  const follow=chatNearBottom()||role==='user';
  chatReadingAdd(role,html,actions);
  chatMakeFoldable(chatReadingStream.lastElementChild);
  if(follow){chatReadingStream.scrollTop=chatReadingStream.scrollHeight;chatUnread=0;}
  else{chatReadingStream.scrollTop=top;chatUnread++;}
  chatReadingStatus();
};
new ResizeObserver(chatReadingStatus).observe(chatReadingStream);

// Search stays local to this conversation and does not alter message content.
const chatFindToggle=document.createElement('button');
chatFindToggle.type='button';chatFindToggle.className='icon-button chat-find-toggle';
chatFindToggle.textContent='⌕';chatFindToggle.setAttribute('aria-label','查找对话');
chatFindToggle.setAttribute('title','查找本次对话');
chatFindToggle.setAttribute('aria-expanded','false');chatFindToggle.setAttribute('aria-controls','chatFind');
$('.assistant-head [data-action="newChat"]').before(chatFindToggle);
const chatFind=document.createElement('div');chatFind.id='chatFind';chatFind.className='chat-find';chatFind.hidden=true;
chatFind.setAttribute('role','search');chatFind.setAttribute('aria-label','查找本次对话');
chatFind.innerHTML='<input type="search" aria-label="对话关键词" placeholder="查找本次对话…" maxlength="100"><span class="chat-find-count" role="status" aria-live="polite">输入关键词</span><button type="button" data-find="prev" aria-label="上一个匹配消息">↑</button><button type="button" data-find="next" aria-label="下一个匹配消息">↓</button><button type="button" data-find="close" aria-label="关闭对话查找">×</button>';
$('.chat-context').after(chatFind);
let chatFindMatches=[],chatFindIndex=-1;
const chatFindInput=chatFind.querySelector('input');
function chatFindRefresh(jump=false){
  const previous=chatFindMatches[chatFindIndex];
  const query=chatFindInput.value.trim().toLocaleLowerCase();
  chatReadingStream.querySelectorAll('.chat-search-hit').forEach(el=>el.classList.remove('chat-search-hit'));
  chatFindMatches=query?[...chatReadingStream.querySelectorAll('.message')].filter(el=>el.textContent.toLocaleLowerCase().includes(query)):[];
  chatFindIndex=chatFindMatches.length?Math.max(0,chatFindMatches.indexOf(previous)):-1;
  chatFindUpdate(jump);
}
function chatFindUpdate(jump){
  chatReadingStream.querySelectorAll('.chat-search-hit').forEach(el=>el.classList.remove('chat-search-hit'));
  const current=chatFindMatches[chatFindIndex];
  chatFind.querySelector('.chat-find-count').textContent=current?`${chatFindIndex+1}/${chatFindMatches.length} 条`:chatFindInput.value.trim()?'无匹配':'输入关键词';
  chatFind.querySelectorAll('[data-find="prev"],[data-find="next"]').forEach(el=>el.disabled=!current);
  if(current&&!chatFind.hidden){current.classList.add('chat-search-hit');if(jump){const fold=current.querySelector('.chat-answer');if(fold)fold.open=true;const target=current.getBoundingClientRect().top-chatReadingStream.getBoundingClientRect().top+chatReadingStream.scrollTop-16;chatReadingStream.scrollTo({top:target,behavior:'instant'});}}
}
function chatFindClose(){chatFind.hidden=true;chatFindToggle.setAttribute('aria-expanded','false');chatReadingStream.querySelectorAll('.chat-search-hit').forEach(el=>el.classList.remove('chat-search-hit'));chatFindToggle.focus();}
function chatFindStep(delta){if(!chatFindMatches.length)return;chatFindIndex=(chatFindIndex+delta+chatFindMatches.length)%chatFindMatches.length;chatFindUpdate(true);}
chatFindToggle.addEventListener('click',()=>{if(!chatFind.hidden){chatFindClose();return;}chatFind.hidden=false;chatFindToggle.setAttribute('aria-expanded','true');chatFindRefresh(false);chatFindInput.focus();});
chatFindInput.addEventListener('input',()=>chatFindRefresh(true));
chatFind.addEventListener('click',e=>{const action=e.target.closest('[data-find]')?.dataset.find;if(action==='close')chatFindClose();if(action==='prev')chatFindStep(-1);if(action==='next')chatFindStep(1);});
chatFind.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();chatFindClose();}if(e.key==='Enter'){e.preventDefault();chatFindStep(e.shiftKey?-1:1);}});
new MutationObserver(()=>{if(!chatFind.hidden)chatFindRefresh(false);}).observe(chatReadingStream,{childList:true});

function chatReplyScope(snapshotKey){
  const snapshot=panoSnapshots.get(snapshotKey),item=chatReadingStream.lastElementChild;
  if(!snapshot||!item?.classList.contains('assistant-message'))return;
  const follow=chatNearBottom();item.dataset.replySnapshot=snapshotKey;
  const strip=document.createElement('div');strip.className='chat-reply-scope';
  const label=document.createElement('span');label.textContent='回答范围 · '+pScope(snapshot);
  const restore=document.createElement('button');restore.type='button';restore.dataset.restoreReply=snapshotKey;restore.textContent='恢复这个范围';
  strip.append(label,restore);item.querySelector('.speaker').after(strip);
  if(follow)chatReadingStream.scrollTop=chatReadingStream.scrollHeight;
}
function chatRestoreScope(snapshot){
  pChange({topic:snapshot.topic,start:snapshot.start,end:snapshot.end});
  pano.focus=snapshot.card;navigate('panorama');
  // Keep the existing conversation visible while restoring the supporting data.
  if(innerWidth>620&&state.mode==='fullscreen')setMode('split');
  commandFeedback('已恢复回答范围：'+pScope(snapshot));
}
window.addEventListener('click',e=>{
  const restore=e.target.closest('[data-restore-reply]');
  if(restore){e.preventDefault();e.stopImmediatePropagation();const snapshot=panoSnapshots.get(restore.dataset.restoreReply);if(snapshot)chatRestoreScope(snapshot);return;}
  // Follow-up questions and plans from an old answer inherit that answer's scope.
  const button=e.target.closest('[data-action="panoTalk"],[data-pano="plan"],[data-pano="budget"]');
  const item=button?.closest('[data-reply-snapshot]');
  if(!item)return;
  const snapshot=panoSnapshots.get(item.dataset.replySnapshot);
  if(!snapshot)return;
  if(button.dataset.key?.startsWith('evidence~')||button.dataset.key==='tasks')return;
  chatRestoreScope(snapshot);
},true);
