import {escapeText as esc} from './customer-display.mjs';
// Presentation only: callers use the same actual capability state as their existing renderer.
export const pendingBadge=()=>'<small class="pending-badge">待启用</small>';
export function pendingFeature(title,reason){return `<section class="pending-feature" data-pending-feature><h3>${esc(title)} ${pendingBadge()}</h3><p>${esc(reason)}</p></section>`;}
export function platformCard(title,body,note='',pendingReason='',informational=false){
 return `<section class="pc-card" data-capability-state="${informational?'info':pendingReason?'pending':'available'}"><div class="pc-section-head"><h2>${esc(title)}${pendingReason?' '+pendingBadge():''}</h2></div>${pendingReason?`<p class="pending-explanation">${esc(pendingReason)}</p>`:''}${note?`<p class="pc-note">${esc(note)}</p>`:''}${body}</section>`;
}
export function pendingPageNotice(content,document){
 const template=document.createElement('template');template.innerHTML=content;
 const children=[...template.content.children];
 const blocks=children.filter(e=>e.hasAttribute('data-capability-state')&&e.dataset.capabilityState!=='info');
 // No page-key list. Every substantive top-level block must actually be pending.
 return blocks.length&&children.every(e=>e.hasAttribute('data-capability-state'))&&blocks.every(e=>e.dataset.capabilityState==='pending')?'<section class="pc-card pc-pending" role="status"><b class="pending-badge">待启用</b><p>本页主体功能均未启用，启用前请联系平台维护人员。</p></section>':'';
}
