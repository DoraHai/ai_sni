import {escapeText} from './customer-display.mjs';

// Parse in a detached template. Build fresh elements; copy no source attributes.
// No resources, styles, scriptable links, forms, SVG or embedded content survive.
export function contentPreview(body) {
  const text=String(body??'');
  if(!/<\/?[a-z][^>]*>/i.test(text))return text.split(/\n\s*\n/).map(p=>`<p>${escapeText(p).replaceAll('\n','<br>')}</p>`).join('');
  const template=document.createElement('template');template.innerHTML=text;
  const output=document.createElement('div');
  const allowed=new Set(['P','BR','H1','H2','H3','H4','H5','H6','STRONG','B','EM','I','U','S','UL','OL','LI','BLOCKQUOTE','PRE','CODE','HR','TABLE','THEAD','TBODY','TR','TH','TD','CAPTION','A','DIV','SPAN']);
  const discard=new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','FORM','INPUT','BUTTON','TEXTAREA','SELECT','VIDEO','AUDIO','IMG','LINK','META','BASE','TEMPLATE']);
  function copy(source,target){for(const node of source.childNodes){if(node.nodeType===3){target.append(document.createTextNode(node.textContent));continue;}if(node.nodeType!==1||discard.has(node.tagName))continue;if(!allowed.has(node.tagName)){copy(node,target);continue;}const fresh=document.createElement(node.tagName.toLowerCase());if(node.tagName==='A'){try{const url=new URL(node.getAttribute('href'));if(['https:','http:'].includes(url.protocol)){fresh.href=url.href;fresh.rel='noopener noreferrer';fresh.target='_blank';}}catch{}}copy(node,fresh);target.append(fresh);}}
  copy(template.content,output);
  // Preserve the existence of unsupported media without fetching third-party resources.
  const images=template.content.querySelectorAll('img');
  if(images.length){const note=document.createElement('p');note.className='preview-limitation';note.textContent=`原稿含 ${images.length} 张图片，当前安全预览未加载图片。确认前请与顾问核对图片内容。`;output.prepend(note);}
  if(template.content.querySelector('iframe,object,embed,video,audio,svg,math')){const note=document.createElement('p');note.className='preview-limitation';note.textContent='原稿含嵌入内容，当前安全预览仅显示支持的文字与排版，请与顾问核对未显示内容。';output.prepend(note);}
  return output.innerHTML;
}
