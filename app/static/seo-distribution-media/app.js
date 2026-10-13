import {selectStoredAuth} from './session.js';
const $=id=>document.getElementById(id), base='/api/seo/distribution-media';
let auth=selectStoredAuth(localStorage,sessionStorage), snapshot=null, scope=null, busy=false, imageUrls=[], allImages=false;
const statuses={draft:'待审核',pending_review:'待审核',approved:'已审核'};
function notice(message,error=false){$('notice').textContent=message;$('notice').dataset.error=String(error);}
function controls(){
  for(const id of ['tenant','site','refresh','variant']) $(id).disabled=busy||!auth;
  $('files').disabled=busy||!snapshot;
  $('upload').disabled=busy||!snapshot||!$('files').files.length;
  $('confirmed').disabled=busy||!snapshot?.set_id||!allImages||snapshot.status==='approved'||$('files').files.length>0;
  $('review').disabled=$('confirmed').disabled||!$('confirmed').checked;
}
function clearPreview(){
  snapshot=null;allImages=false;$('confirmed').checked=false;$('files').value='';$('selected').replaceChildren();
  $('title').textContent='尚未选择稿件';$('body').textContent='';$('state').textContent='';
  $('images').replaceChildren();for(const url of imageUrls)URL.revokeObjectURL(url);imageUrls=[];
}
async function api(path,options={}){
  const current=selectStoredAuth(localStorage,sessionStorage);
  if(!current||current.token!==auth?.token)throw new Error('登录身份已变化，请刷新页面重新核对。');
  const response=await fetch(base+path,{...options,credentials:'same-origin',cache:'no-store',headers:{...options.headers,Authorization:`Bearer ${current.token}`}});
  if(selectStoredAuth(localStorage,sessionStorage)?.token!==current.token)throw new Error('登录身份已变化，请刷新页面重新核对。');
  if(!response.ok){let message='请求失败，请重新读取稿件后再试。';
    try{const data=await response.json();if(typeof data.detail?.message==='string')message=data.detail.message;}catch{}
    if(response.status===401)message='登录已失效，请重新登录 SEO。';throw new Error(message);}
  return response;
}
async function perform(work){if(busy)return;const identity=auth?.token;busy=true;controls();try{await work();if(!identity||selectStoredAuth(localStorage,sessionStorage)?.token!==identity)throw new Error('登录身份已变化，请刷新页面重新核对。');}catch(error){clearPreview();notice(error.message,true);}finally{busy=false;controls();}}
const query=()=>new URLSearchParams(scope).toString();
async function show(variant){
  clearPreview();if(!variant)return;
  snapshot=await (await api(`/variants/${encodeURIComponent(variant)}?${query()}`)).json();
  $('title').textContent=snapshot.title;$('body').textContent=snapshot.body_text;
  const option=[...$('variant').options].find(item=>item.value===String(snapshot.variant_id));
  if(option)option.textContent=`${snapshot.title} · ${statuses[snapshot.status]||snapshot.status}`;
  $('state').textContent=`状态：${statuses[snapshot.status]||snapshot.status} · 图片 ${snapshot.assets.length} 张`;
  for(const [index,item] of snapshot.assets.entries()){
    const response=await api(`/variants/${snapshot.variant_id}/assets/${encodeURIComponent(item.id)}?${query()}`);
    const blob=await response.blob();
    if(blob.type!==item.mediaType||blob.size!==item.bytes)throw new Error('图片信息不一致，请重新读取。');
    const url=URL.createObjectURL(blob);imageUrls.push(url);
    const figure=document.createElement('figure'),img=document.createElement('img'),caption=document.createElement('figcaption');
    img.src=url;img.alt=`第 ${index+1} 张待审核图片`;await img.decode();
    caption.textContent=`第 ${index+1} 张 · ${item.mediaType==='image/png'?'PNG':'JPEG'}`;
    figure.append(img,caption);$('images').append(figure);
  }
  allImages=snapshot.assets.length>0;notice(snapshot.status==='approved'?'当前稿件已审核。更换图片将撤销本次审核。':'请核对正文与图片；图片上传者不能自审。');
}
$('scope').addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  clearPreview();$('variant').replaceChildren();
  const tenant=Number($('tenant').value),site=Number($('site').value);
  if(!Number.isSafeInteger(tenant)||tenant<1||!Number.isSafeInteger(site)||site<1)throw new Error('请输入有效客户和网站编号。');
  scope={tenant_id:tenant,site_id:site};
  const result=await (await api(`/variants?${query()}`)).json();
  const empty=document.createElement('option');empty.value='';empty.textContent=result.items.length?'请选择稿件':'没有可编辑的小红书渠道稿';$('variant').append(empty);
  for(const row of result.items){const option=document.createElement('option');option.value=row.variant_id;option.textContent=`${row.title} · ${statuses[row.status]||row.status}`;$('variant').append(option);}
  const requested=new URLSearchParams(location.search).get('variant_id');
  if(requested&&/^\d+$/.test(requested)&&result.items.some(row=>String(row.variant_id)===requested)){$('variant').value=requested;await show(requested);return;}
  notice(result.items.length?'请选择需要上传图片或审核的稿件。':'请先在 SEO 内容模块准备小红书渠道稿。');
});});
$('variant').addEventListener('change',()=>perform(()=>show($('variant').value)));
for(const id of ['tenant','site'])$(id).addEventListener('input',()=>{clearPreview();scope=null;$('variant').replaceChildren();controls();});
$('files').addEventListener('change',()=>{
  $('selected').replaceChildren();$('confirmed').checked=false;
  for(const [index,file] of [...$('files').files].entries()){const item=document.createElement('li');item.textContent=`${index+1}. ${file.name}`;$('selected').append(item);}
  controls();
});
$('upload').addEventListener('click',()=>perform(async()=>{
  const files=[...$('files').files];
  if(files.length<1||files.length>9||files.some(f=>f.size>20000000)||files.reduce((sum,f)=>sum+f.size,0)>40000000)throw new Error('图片数量或文件大小超出页面说明的范围。');
  const form=new FormData();for(const [key,value]of Object.entries(scope))form.set(key,value);
  form.set('expected_token',snapshot.edit_token);for(const file of files)form.append('files',file);
  const variant=snapshot.variant_id;await api(`/variants/${variant}/assets`,{method:'POST',body:form});
  await show(variant);notice('图片已保存，旧审核已撤销。请另一位顾问登录后核对并审核。');
}));
$('confirmed').addEventListener('change',controls);
$('review').addEventListener('click',()=>perform(async()=>{
  if(!$('confirmed').checked||!allImages)throw new Error('请先核对完整正文及全部图片。');
  const variant=snapshot.variant_id;
  await api(`/variants/${variant}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,set_id:snapshot.set_id,expected_token:snapshot.edit_token})});
  await show(variant);notice('审核通过，当前正文与图片已冻结。尚未发布文章。');
}));
function invalidate(){const current=selectStoredAuth(localStorage,sessionStorage);if(current?.token!==auth?.token){auth=null;clearPreview();notice('登录身份已变化，请刷新页面重新核对。',true);controls();}}
window.addEventListener('storage',invalidate);window.addEventListener('sem:auth-context-changed',invalidate);
for(const [id,key]of [['tenant','tenant_id'],['site','site_id']])$(id).value=new URLSearchParams(location.search).get(key)||'';
notice(auth?'请选择当前客户和网站，读取可编辑稿件。':'请先在同源 SEO 页面登录，再打开此页面。',!auth);controls();
if(auth&&/^\d+$/.test($('tenant').value)&&/^\d+$/.test($('site').value))$('scope').requestSubmit();
window.addEventListener('pagehide',clearPreview);
