export function handleUi13({url,req,res,send,body,state,tenant,site,advisor}){
  const kind=url.pathname.includes('/qa/facts')?'facts':url.pathname.includes('/keywords')?'keywords':null;
  if(!kind)return false;
  const rows=state[kind].get(tenant),match=url.pathname.match(/\/(\d+)$/),id=match?Number(match[1]):null;
  if(req.method==='GET'&&kind==='keywords'&&!id){const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||50),q=url.searchParams.get('q')||'';const items=rows.filter(v=>v.keyword.includes(q));send(200,{items:items.slice((page-1)*size,page*size),total:items.length,page,page_size:size,engine:url.searchParams.get('engine')||'baidu'});return true;}
  if(req.method==='DELETE'&&kind==='keywords'&&id){
    if(!advisor||state.keywordLevel!=='edit'||state.planDenied){send(403,{detail:'Fixture deletion denied'});return true;}
    const index=rows.findIndex(v=>v.id===id&&v.site_id===Number(url.searchParams.get('site_id')));
    if(index<0){send(404,{detail:'Unknown scoped keyword'});return true;}
    rows.splice(index,1);
    if(state.keywordDeleteDropOnce){state.keywordDeleteDropOnce=false;res.writeHead(200,{'Content-Type':'application/json'});res.end('{');return true;}
    send(200,{deleted:true,keyword_id:id});return true;
  }
  if(!['POST','PATCH'].includes(req.method))return false;
  if(!advisor||state.planDenied){send(403,{detail:'Fixture maintenance denied'});return true;}
  if(req.method==='POST'){const value={...body,id:Math.max(100,...rows.map(v=>v.id))+1,...(kind==='facts'?{version:1,current:body.status==='active'}:{status:'active'})};rows.unshift(value);send(200,value);return true;}
  const row=rows.find(v=>v.id===id);if(!row){send(404,{detail:'Unknown row'});return true;}
  if(kind==='facts'&&row.version!==body.version){send(409,{detail:{code:'fact_version_conflict'}});return true;}
  Object.assign(row,body,...(kind==='facts'?[{version:row.version+1,current:body.status==='active'}]:[]));send(200,row);return true;
}
