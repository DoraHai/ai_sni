import {escapeText as esc} from './customer-display.mjs';
export const visibilityNotice='这是 DeepSeek 搜索引擎能不能搜到你，不等于 DeepSeek 回答里会提到你';
export function visibilityTime(value){
  if(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(value||''))return value;
  if(!value)return '正在记录';
  const date=new Date(value);if(!Number.isFinite(date.getTime()))return '时间待核对';
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date).map(p=>[p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}
const number=n=>Number.isFinite(Number(n))?Math.max(0,Number(n)):0;
export function visibilityLink(value,label){
  try{const url=new URL(value);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return esc(label||'链接不可用');
    return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label||url.hostname)} ↗</a>`;
  }catch{return esc(label||'链接不可用');}
}
const control=(action,label,disabled=false)=>`<button type="button" data-sv="${action}" ${disabled?'disabled':''}>${label}</button>`;
function trend(weeks){
  const rows=(weeks||[]).slice(-8),value=row=>number(row.summary?.brand_hit)+number(row.summary?.core_hit);
  if(!rows.length)return '<p class="sv-muted">积累检查记录后，这里会显示最近 8 周的趋势。</p>';
  const max=Math.max(1,...rows.map(value)),x=i=>20+i*50,y=row=>75-value(row)/max*50;
  const dots=rows.map((r,i)=>r.status==='succeeded'?`<circle cx="${x(i)}" cy="${y(r)}" r="4"><title>${esc(r.week)}：${value(r)} 个词搜到你</title></circle>`:'').join('');
  const lines=rows.slice(1).map((r,i)=>r.status==='succeeded'&&rows[i].status==='succeeded'?`<line x1="${x(i)}" y1="${y(rows[i])}" x2="${x(i+1)}" y2="${y(r)}"/>`:'').join('');
  return `<div class="sv-trend"><svg viewBox="0 0 400 100" role="img" aria-label="最近八周前二十名命中词数，未完成检查不连线">${lines}${dots}</svg><div>${rows.map(r=>`<span>${esc(String(r.week||'').slice(5))}<b>${r.status==='succeeded'?value(r)+' 个':'未完成'}</b></span>`).join('')}</div></div>`;
}
function configForm(state){
  if(!state.configOpen)return '';
  if(!state.draft)return '<p>设置正在读取，请稍后刷新。</p>';
  const d=state.draft,textarea=(key,label,max,hint)=>`<label>${label}<small>${hint}，最多 ${max} 条，每行一条</small><textarea data-sv-field="${key}" rows="${key==='extra_article_urls'?3:2}">${esc(Array.isArray(d[key])?d[key].join('\n'):d[key]||'')}</textarea></label>`;
  return `<form class="sv-form"><h3>GEO 项目设置 · DeepSeek 搜索可见度</h3>
    <label class="sv-check"><input type="checkbox" data-sv-field="enabled" ${d.enabled?'checked':''}>每周核对这个项目</label>
    <p class="sv-muted">每周一北京时间 06:00 检查；没有配置服务密钥时显示“待启用”。密钥由服务器管理。</p>
    ${textarea('domains','网站域名',3,'例如 example.com，不带协议或路径')}
    <label>中文首页地址<small>填写中文页面的完整链接，减少被跳到外语版的情况</small><input data-sv-field="zh_url" type="url" maxlength="2048" value="${esc(d.zh_url||'')}"></label>
    ${textarea('brand_terms','品牌词',5,'填写客户品牌或常用叫法，每个词最多 128 字')}
    ${textarea('core_terms','核心词',20,'填写客户希望被搜到的词，每个词最多 128 字')}
    ${state.suggestions?.length?`<div class="sv-suggestions"><small>同一客户的优化单元推荐词，点击加入当前项目：</small>${state.suggestions.map((s,i)=>control('suggest-'+i,esc(s),state.busy)).join('')}</div>`:''}
    ${textarea('extra_article_urls','补充文章链接',20,'已回填的发稿链接会自动带入，这里只填补充链接')}
    <label class="sv-check"><input type="checkbox" data-sv-field="customer_visible" ${d.customer_visible?'checked':''}>允许客户看到检查结果</label>
    <p class="sv-muted">默认关闭。前 4 周先由顾问核对，确认数字可靠后再开放给客户。</p>
    <button type="submit" ${state.busy?'disabled':''}>保存项目设置</button></form>`;
}
export function renderSearchVisibility(state,{advisor=false}={}){
  const data=state.data;
  if(!advisor&&(!data||data.state==='not_open'))return '';
  const job=data?.latest,summary=job?.result?.summary,waiting=['pending','running'].includes(job?.status);
  const buttons=`${control('refresh','刷新',state.busy)}${advisor?control('config',state.configOpen?'收起项目设置':'项目设置',state.busy):''}`;
  const header=`<header><div><small>每周核对 · 搜索引擎证据</small><h2>DeepSeek 搜索可见度</h2></div><div class="sv-actions">${buttons}</div></header><p class="sv-notice">${visibilityNotice}</p>`;
  const form=advisor?configForm(state):'';
  const feedback=state.message?`<p role="status" class="sv-feedback">${esc(state.message)}</p>`:'';
  if(!data)return `<section class="sv-card">${header}<p class="sv-empty">${state.message?'检查结果暂时无法读取，请刷新核对。':'正在读取检查结果…'}</p>${feedback}${form}</section>`;
  if(data.state==='not_enabled')return `<section class="sv-card">${header}<p class="sv-empty"><span class="pending-badge">待启用</span> ${advisor?'开启项目开关并开通搜索服务后，这里会显示检查结果。':'顾问开通后，这里会显示检查结果。'}</p>${feedback}${form}</section>`;
  if(!job)return `<section class="sv-card">${header}<p class="sv-empty">还没有检查记录。${advisor?'保存设置后，可以立即跑一次。':'顾问完成首次检查后，结果会显示在这里。'}</p>${feedback}${advisor?control('run','立即跑一次',state.busy):''}${form}</section>`;
  const metric=(label,value,explain)=>`<div><small>${label}</small><strong>${waiting?'检查中':value}</strong><p>${explain}</p></div>`;
  const items=job.result?.items||[],wordRows=items.filter(i=>['brand','core'].includes(i.kind)),pages=items.filter(i=>['homepage','article'].includes(i.kind));
  const total=number(summary?.brand_total)+number(summary?.core_total),hit=number(summary?.brand_hit)+number(summary?.core_hit);
  const indexed=summary?.indexed===true?`是 · 约 ${number(summary.indexed_count)} 页`:summary?.indexed===false?'暂未找到':'尚未确认';
  const wordsValue=job.status==='failed'&&!wordRows.length?'尚未确认':total?`${hit} / ${total} 个`:'尚未设置';
  const pagesValue=job.status==='failed'&&!pages.some(i=>typeof i.alive==='boolean')?'尚未确认':`${number(summary?.articles_alive)} / ${number(summary?.articles_total)} 篇`;
  const cards=`<div class="sv-metrics">${metric('DeepSeek 已收录你的网站',indexed,'用网站域名搜索，确认有没有找到你的页面。')}${metric('你的词能搜到你',wordsValue,'品牌词和核心词中，前 20 名能找到官网或已发文章的词数。')}${metric('已发文章还在',pagesValue,'核对已发文章是否仍可访问；暂不能核对的链接不会记为存活。')}</div>`;
  const table=wordRows.length?`<div class="sv-table"><table><caption>搜索词明细</caption><thead><tr><th>搜索词</th><th>你的最好名次</th><th>排在前面的是谁</th></tr></thead><tbody>${wordRows.map(item=>{
    const rank=Number(item.best_rank),ahead=(item.results||[]).filter(r=>!rank||number(r.rank)<rank);
    const position=item.error||!rank&&job.status==='failed'?'本次未确认':rank?'第 '+rank+' 名':'前 20 名没有';
    return `<tr><td><b>${esc(item.query)}</b><small>${item.kind==='brand'?'品牌词':'核心词'}</small></td><td>${position}${advisor&&item.error?`<small>${esc(item.error)}</small>`:''}</td><td>${ahead.length?ahead.map(r=>`<div>${number(r.rank)}. ${visibilityLink(r.url,r.site_name||r.title||'查看页面')}</div>`).join(''):'前面没有其他结果'}${rank?`<small>你的页面：${visibilityLink(item.results?.find(r=>r.rank===rank)?.url,'打开原始链接')}</small>`:''}</td></tr>`;
  }).join('')}</tbody></table></div>`:'';
  const articles=pages.length?`<details class="sv-pages"><summary>首页与文章核对（${pages.length} 条）</summary>${pages.map(i=>`<div><b>${i.kind==='homepage'?'中文首页':'已发文章'}</b> ${visibilityLink(i.url,i.effective_title||i.title||'查看原始链接')}<span>${i.alive===true?'可访问':i.alive===false?'无法访问':'暂未核对'}</span>${advisor?`<small>${esc(i.error||i.warning||'')}${i.source?.includes('local_safe_fetch')?' · 含本机兜底证据':''}${i.effective_foreign_language===true?' · 兜底仍为外语页面':''}</small>`:''}</div>`).join('')}</details>`:'';
  return `<section class="sv-card">${header}<p class="sv-muted">最近检查：${esc(visibilityTime(job.finished_at||job.created_at))}（北京时间）${waiting?' · 正在检查，只会自动读取进度':''}</p>${job.status==='failed'?`<p class="sv-feedback">本次检查未完成，以下为已取得的结果。${advisor?esc(job.error||summary?.stopped_reason||'请查看明细并联系管理员。'):''}</p>`:''}${advisor&&summary?.index_query_ok===false?'<p class="sv-feedback">部分域名本次未查完，收录页数可能不完整。</p>':''}${feedback}${cards}<h3>最近 8 周 · 能搜到你的词</h3>${trend(data.weeks)}${table}${articles}<div class="sv-actions">${advisor?control('run','立即跑一次',state.busy||waiting):''}${control('csv','下载表格（CSV）',state.busy||waiting||!job.id)}</div>${advisor?'<p class="sv-muted">每个项目每天最多立即运行一次，运行后可刷新查看进度。</p>':''}${form}</section>`;
}
