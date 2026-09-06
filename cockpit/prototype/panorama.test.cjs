// Run: node cockpit/prototype/panorama.test.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const read = file => fs.readFileSync(path.join(__dirname,file),'utf8');
const sandbox = vm.createContext({});
vm.runInContext(read('cockpit.js').split('const samples=')[0]+read('panorama-data.js')+read('panorama.js').split('const panoPage=')[0],sandbox);
const run = expression => vm.runInContext(expression,sandbox);
assert.equal(run('panoramaData.all.length'),99);
assert.equal(run('new Set(panoramaData.all.map(r=>r.id)).size'),99);
assert.equal(run('pStats().cost'),42110);
assert.equal(run('pStats().organic'),840);
assert.equal(run('pStats().mentions'),24);
assert.equal(run('panoramaData.answers.every(r=>r.simulated)'),true);
assert.equal(run("pStats({topic:'智能仓储',start:2,end:4}).cost"),6120);
assert.equal(run("pStats({topic:'智能仓储',start:2,end:4}).clicks"),367);
assert.equal(run("pStats({topic:'智能仓储',start:2,end:4}).conv"),2);
assert.equal(run("pRows('keywords',{topic:'all',start:0,end:5}).length"),0);
assert.equal(run("pRows('keywords',{topic:'all',start:6,end:6}).length"),24);
// Reconciliation holds for every contiguous date window, including one-day scopes.
for(let start=0;start<7;start++)for(let end=start;end<7;end++){
  assert.equal(run(`pStats({topic:'all',start:${start},end:${end}}).cost`),run(`weekly.spend.slice(${start},${end+1}).reduce((a,b)=>a+b,0)`));
  assert.equal(run(`pStats({topic:'智能仓储',start:${start},end:${end}}).organic`),null);
  assert.equal(run(`panoramaData.topics.reduce((n,topic)=>n+pStats({topic,start:${start},end:${end}}).clicks,0)`),run(`pStats({topic:'all',start:${start},end:${end}}).clicks`));
}
console.log('Panorama scenario: record identity, mock provenance, scoped totals and all 28 date windows passed.');
vm.runInContext(read('sem-depth.js').split('panoCards.semkeywords=')[0],sandbox);
assert.equal(run('semKeywordRows.length'),63);
for(const topic of ['all','智能仓储','品牌解决方案','工业自动化'])for(let start=0;start<7;start++)for(let end=start;end<7;end++){
  const scope=JSON.stringify({topic,start,end});
  for(const field of ['cost','clicks','impressions','conversions']){
    assert.equal(run(`Math.round(pSum(semDepthKeywords(${scope}),'${field}')*100)`),run(`Math.round(pSum(pRows('paid',${scope}),'${field}')*100)`));
  }
}
vm.runInContext(read('sem-depth.js').split('function semPartition')[1].split('function semDepthBars')[0].replace(/^/, 'function semPartition'),sandbox);
for(const weights of [[.7,.3],[.6,.4],[.2,.5,.3]])for(const field of ['cost','clicks','conversions']){
  assert.equal(run(`Math.round(pSum(semPartition(semKeywordRows,['a','b','c'].slice(0,${weights.length}),${JSON.stringify(weights)}),'${field}')*100)`),run(`Math.round(pSum(semKeywordRows,'${field}')*100)`));
}
console.log('SEM drill-down: all 112 scopes and dimensional partitions reconcile with paid source totals.');
// Reopening an object must retain its discussion, while a different scope must not.
vm.runInContext("let guideObject=null;function guideRender(){};"+read('object-guidance.js').split('function guideSet')[1].split('function guideRender')[0].replace(/^/,'function guideSet'),sandbox);
run("guideSet('SEM','SK-11','test',{topic:'all',start:0,end:6});guideObject.discussion='saved evidence';guideSet('SEM','SK-11','test',{topic:'all',start:0,end:6})");
assert.equal(run('guideObject.discussion'),'saved evidence');
run("guideSet('SEM','SK-11','test',{topic:'all',start:2,end:4})");
assert.equal(run('guideObject.discussion'),'');
vm.runInContext(read('seo-depth.js').split('const seoDetails=')[0],sandbox);
run("seoList({topic:'all',start:0,end:6});seoListState.get(JSON.stringify({topic:'all',start:0,end:6})).query='CT-16'");
assert.equal(run("seoList({topic:'all',start:0,end:6}).includes('value=\"CT-16\"')"),true);
assert.equal(run("(seoList({topic:'all',start:0,end:6}).match(/<button hidden data-seo-open/g)||[]).length"),17);
assert.equal(run("seoList({topic:'智能仓储',start:0,end:6}).includes('value=\"\"')"),true);
console.log('Acceptance regressions: object discussion retention and scoped article search restoration passed.');
// Confirm the interface never assigns site/topic clicks to an individual article.
vm.runInContext(read('seo-depth.js').split('let seoView=null;')[1].split('function seoOpen')[0].replace(/^/,'let seoView=null;'),sandbox);
run("seoView={id:'CT-11',scope:{topic:'all',start:0,end:6},tab:'search'}");
const articleSearch=run('seoBody()');
assert.match(articleSearch,/本篇搜索点击 · 未接入/);
assert.match(articleSearch,/业务每日点击 · 暂不支持/);
assert.doesNotMatch(articleSearch,/data-seo-day|<svg/);
assert.equal(run("seoNext({status:'已审核待发布'})"),'确认发布安排');
// A ready article must be counted separately, not moved into published totals.
run("panoramaData.content.push({...panoramaData.content[0],id:'TEST-READY',status:'已审核待发布'})");
const readyList=run("seoList({topic:'all',start:0,end:6})");
assert.match(readyList,/<b>1<\/b><span>已审核待发布<\/span>/);
assert.match(readyList,/<b>9<\/b><span>已发布<\/span>/);
run('panoramaData.content.pop()');
console.log('SEO boundary regressions: ready is distinct from published; article click attribution stays unavailable.');

assert.equal(run("pRows('search',{topic:'智能仓储',start:0,end:6}).length"),0);
assert.match(run("pCardBody('organic',{topic:'智能仓储',start:0,end:6})"),/当前不支持按业务主题统计/);
assert.doesNotMatch(run("pCardBody('organic',{topic:'all',start:0,end:6})"),/<svg/);
assert.equal(run('pOrganic(null)'), '未提供');

// Unsupported legacy search partitions must not be exposed through object search or drill-down.
assert.equal(run("panoramaData.all.some(r=>r.id.startsWith('SC-'))"),false);
assert.equal(run("panoramaData.all.filter(r=>r.id.startsWith('CT-')).length"),18);
