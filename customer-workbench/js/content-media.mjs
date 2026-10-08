import {escapeText as esc} from './customer-display.mjs';
const MAX_BYTES=10*1024*1024;
const types=new Set(['image/png','image/jpeg','image/webp','image/gif','image/avif']);
export function createContentMedia({root,host,fetchImpl=globalThis.fetch}){
  let currentKey=null,generation=0,records=new Map(),dialog=null,returnFocus=null;
  function close(){dialog?.close();dialog?.remove();dialog=null;returnFocus?.focus({preventScroll:true});returnFocus=null;}
  function clear(){generation++;close();for(const r of records.values()){r.abort?.abort();if(r.url)URL.revokeObjectURL(r.url);}records.clear();currentKey=null;}
  async function bytes(src,signal){
    const ctx=host.getContext();if(!ctx)throw Error('授权范围已变化');
    const url=new URL(src,location.origin);
    if(url.username||url.password)throw Error('图片地址包含不支持的身份信息');
    const capture=url.origin===location.origin&&url.pathname.match(/^\/api\/v1\/seo\/site\/page-captures\/([1-9]\d*)\/image$/);
    let response;
    if(capture){
      if([...url.searchParams.keys()].some(k=>k!=='tenant_id')||url.searchParams.getAll('tenant_id').length>1||(url.searchParams.has('tenant_id')&&url.searchParams.get('tenant_id')!==String(ctx.tenantId)))throw Error('图片不属于当前授权客户');
      const base=`/api/v1/seo/site/page-captures/${capture[1]}`;
      const metadata=await host.transport(`${base}?tenant_id=${ctx.tenantId}`,{method:'GET',signal});if(!metadata.ok)throw Error('图片记录暂不可读取');const row=await metadata.json();
      if(row.id!==Number(capture[1])||row.tenant_id!==ctx.tenantId||row.site_id!==ctx.siteId)throw Error('图片不属于当前网站');
      response=await host.transport(`${base}/image?tenant_id=${ctx.tenantId}`,{method:'GET',signal});
    }else{
      if(url.protocol!=='https:'||url.origin===location.origin&&url.pathname.startsWith('/api/'))throw Error('此图片地址尚无可用的安全读取路径');
      // Public media never receives the workbench token, browser cookies, or referring URL.
      response=await fetchImpl(url.href,{credentials:'omit',mode:'cors',redirect:'error',referrerPolicy:'no-referrer',signal});
    }
    if(!response.ok)throw Error('图片加载失败，可重试或请顾问核对地址');
    const type=response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();if(!types.has(type))throw Error('该文件不是支持的图片格式');
    if(Number(response.headers.get('content-length'))>MAX_BYTES)throw Error('图片超过10MB，请顾问提供适合预览的图片');
    let data;
    if(response.body?.getReader){const reader=response.body.getReader(),chunks=[];let size=0;while(true){const part=await reader.read();if(part.done)break;size+=part.value.length;if(size>MAX_BYTES){await reader.cancel();throw Error('图片超过10MB');}chunks.push(part.value);}data=new Blob(chunks,{type});}
    else{const buffer=await response.arrayBuffer();if(buffer.byteLength>MAX_BYTES)throw Error('图片超过10MB');data=new Blob([buffer],{type});}
    return data;
  }
  function paint(){
    for(const el of root.querySelectorAll('[data-preview-index]')){const r=records.get(el.dataset.previewIndex);if(!r)continue;el.dataset.mediaState=r.state;el.innerHTML=`<span class="media-caption">图片 ${r.index} · ${esc(r.alt||'未填写图片说明')}</span>${r.state==='loaded'?`<img src="${r.url}" alt="${esc(r.alt)}"><button data-media-action="open" data-index="${r.index}">查看原尺寸 (${r.width} × ${r.height})</button>`:`<span role="status">${esc(r.state==='loading'?'正在加载图片…':r.error)}</span>${r.state==='failed'?`<button data-media-action="retry" data-index="${r.index}">重试图片</button>`:''}`}`;}
    const boxes=[...root.querySelectorAll('[data-preview-index]')],missing=boxes.filter(e=>e.dataset.mediaState!=='loaded').length;
    root.querySelector('#media-summary')?.remove();if(boxes.length){const note=document.createElement('p');note.id='media-summary';note.setAttribute('role','status');note.textContent=`正文共 ${boxes.length} 张图片，已显示 ${boxes.length-missing} 张${missing?`，还有 ${missing} 张未显示，请在确认前核对。`:'，请结合图片说明核对稿件。'}`;root.querySelector('#delivery-body')?.before(note);}
  }
  async function load(r){const stamp=generation;r.state='loading';r.error='';r.abort=new AbortController();paint();const timeout=setTimeout(()=>r.abort.abort(),20000);let objectUrl;try{const blob=await bytes(r.src,r.abort.signal);if(stamp!==generation)return;objectUrl=URL.createObjectURL(blob);const image=new Image();image.src=objectUrl;await image.decode();if(stamp!==generation){URL.revokeObjectURL(objectUrl);return;}r.url=objectUrl;r.width=image.naturalWidth;r.height=image.naturalHeight;r.state='loaded';}catch(e){if(objectUrl)URL.revokeObjectURL(objectUrl);if(stamp!==generation)return;r.state='failed';r.error=e.name==='AbortError'?'加载超时，请重试':e.message==='Failed to fetch'?'图片来源不可访问或不允许跨站读取，请重试或联系顾问':e.message;}finally{clearTimeout(timeout);if(stamp===generation)paint();}}
  function click(event){const b=event.target.closest('[data-media-action]');if(!b)return;const r=records.get(b.dataset.index);if(b.dataset.mediaAction==='retry'&&r){void load(r);return;}if(b.dataset.mediaAction==='close'){close();return;}if(b.dataset.mediaAction==='open'&&r?.state==='loaded'){close();returnFocus=b;dialog=document.createElement('dialog');dialog.className='media-dialog';dialog.innerHTML=`<div class="media-dialog-head"><b>图片 ${r.index} · ${esc(r.alt||'原尺寸查看')}</b><button data-media-action="close">关闭图片</button></div><p>原尺寸 ${r.width} × ${r.height}，可滚动查看；按 Esc 关闭。</p><div class="media-original"><img src="${r.url}" alt="${esc(r.alt)}" style="width:${r.width}px;height:${r.height}px"></div>`;root.append(dialog);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.showModal();}}
  root.addEventListener('click',click);
  return {clear,render(key){if(key!==currentKey){clear();currentKey=key;}if(!key)return;for(const el of root.querySelectorAll('[data-preview-index]')){const id=el.dataset.previewIndex;if(!records.has(id)){const r={index:id,src:el.dataset.previewSrc,alt:el.dataset.previewAlt,state:'loading'};records.set(id,r);void load(r);}}paint();},unseen(){return [...root.querySelectorAll('[data-preview-index]')].filter(e=>e.dataset.mediaState!=='loaded').length;},dispose(){clear();root.removeEventListener('click',click);}};
}
