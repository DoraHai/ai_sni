import {escapeText} from './customer-display.mjs';

// Parse in a detached template. Build fresh elements; copy no source attributes.
// No resources, styles, scriptable links, forms, SVG or embedded content survive.
export function contentPreview(body) {
  const text=String(body??'');
  let imageIndex=0;
  const picture=(src,alt)=>`<span class="preview-media" data-preview-index="${++imageIndex}" data-preview-src="${escapeText(src)}" data-preview-alt="${escapeText(alt)}"><span>图片 ${imageIndex} · ${escapeText(alt||'未填写图片说明')} · 等待加载</span></span>`;
  const markdown=value=>{let result='',last=0;for(const m of value.matchAll(/!\[([^\]]*)\]\(<?([^\s<>]+?)>?(?:\s+"[^"]*")?\)/g)){result+=escapeText(value.slice(last,m.index))+picture(m[2],m[1]);last=m.index+m[0].length;}return result+escapeText(value.slice(last));};
  if(!/<\/?[a-z][^>]*>/i.test(text))return text.split(/\n\s*\n/).map(p=>`<p>${markdown(p).replaceAll('\n','<br>')}</p>`).join('');
  const template=document.createElement('template');template.innerHTML=text;
  const output=document.createElement('div');
  const allowed=new Set(['P','BR','H1','H2','H3','H4','H5','H6','STRONG','B','EM','I','U','S','UL','OL','LI','BLOCKQUOTE','PRE','CODE','HR','TABLE','THEAD','TBODY','TR','TH','TD','CAPTION','A','DIV','SPAN','FIGURE','FIGCAPTION']);
  const discard=new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','FORM','INPUT','BUTTON','TEXTAREA','SELECT','VIDEO','AUDIO','IMG','LINK','META','BASE','TEMPLATE']);
  function copy(source,target){for(const node of source.childNodes){if(node.nodeType===3){const part=document.createElement('template');part.innerHTML=markdown(node.textContent);target.append(part.content);continue;}if(node.nodeType!==1)continue;if(node.tagName==='IMG'){const part=document.createElement('template');part.innerHTML=picture(node.getAttribute('src')||'',node.getAttribute('alt')||'');target.append(part.content);continue;}if(discard.has(node.tagName))continue;if(!allowed.has(node.tagName)){copy(node,target);continue;}const fresh=document.createElement(node.tagName.toLowerCase());if(node.tagName==='A'){try{const url=new URL(node.getAttribute('href'));if(['https:','http:'].includes(url.protocol)){fresh.href=url.href;fresh.rel='noopener noreferrer';fresh.target='_blank';}}catch{}}copy(node,fresh);target.append(fresh);}}
  copy(template.content,output);
  // Preserve the existence of unsupported media without fetching third-party resources.
  if(imageIndex){const note=document.createElement('p');note.className='preview-limitation';note.textContent=`原稿含 ${imageIndex} 张图片，请逐张核对加载状态与说明。`;output.prepend(note);}
  if(template.content.querySelector('iframe,object,embed,video,audio,svg,math')){const note=document.createElement('p');note.className='preview-limitation';note.textContent='原稿含嵌入内容，当前安全预览仅显示支持的文字与排版，请与顾问核对未显示内容。';output.prepend(note);}
  return output.innerHTML;
}
