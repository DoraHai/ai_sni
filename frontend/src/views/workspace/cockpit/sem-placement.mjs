const integer = n => Number.isSafeInteger(n) && n >= 0
export function allocateClicks(total, weights) {
  const sum = weights.reduce((s,w)=>s+w,0)
  const exact = weights.map(w=>total*w/sum), result=exact.map(Math.floor)
  const order=exact.map((v,i)=>({i,f:v-result[i]})).sort((a,b)=>b.f-a.f||a.i-b.i)
  for(let left=total-result.reduce((s,v)=>s+v,0),i=0;i<left;i++) result[order[i].i]++
  return result
}
const provinceCodes=['110000','120000','130000','140000','150000','210000','220000','230000','310000','320000','330000','340000','350000','360000','370000','410000','420000','430000','440000','450000','460000','500000','510000','520000','530000','540000','610000','620000','630000','640000','650000','710000','810000','820000']
const provinceWeights=[8,3,5,2,1,3,1,1,12,18,16,7,9,4,11,6,8,5,22,3,1,6,10,2,3,0,5,1,0,1,1,0,1,0]
const hourWeights=[1,1,1,1,1,2,4,8,16,24,28,25,16,18,25,30,28,22,13,10,9,7,4,2]
export function demoSemPlacement(days) {
  const total=days.reduce((s,d)=>s+d.click,0)
  const regions=allocateClicks(total,provinceWeights).map((clicks,i)=>({code:provinceCodes[i],clicks}))
  const cells=Array.from({length:168},(_,i)=>({weekday:Math.floor(i/24),hour:i%24,clicks:null}))
  for(const d of days){
    const weekday=(new Date(`${d.date}T00:00:00Z`).getUTCDay()+6)%7
    allocateClicks(d.click,hourWeights).forEach((v,h)=>{const cell=cells[weekday*24+h];cell.clicks=(cell.clicks??0)+v})
  }
  return {state:'available',demo:true,metric:'click',total,regions,cells,
    period:`${days[0].date} 至 ${days.at(-1).date}`,source:'TIGER 驾驶舱模拟数据 v1',timezone:'Asia/Shanghai'}
}
export function validSemPlacement(data) {
  return data?.state==='available' && data.metric==='click' && integer(data.total)
    && Array.isArray(data.regions) && data.regions.every(r=>provinceCodes.includes(r.code)&&integer(r.clicks))
    && new Set(data.regions.map(r=>r.code)).size===data.regions.length
    && data.regions.reduce((s,r)=>s+r.clicks,0)===data.total
    && Array.isArray(data.cells)&&data.cells.length===168
    && data.cells.every((c,i)=>c.weekday===Math.floor(i/24)&&c.hour===i%24&&(c.clicks===null||integer(c.clicks)))
    && data.cells.reduce((s,c)=>s+(c.clicks??0),0)===data.total
}
export function clickColor(value,max) {
  if(value===null || value===undefined) return '#163142'
  const t=max>0?Math.sqrt(value/max):0
  const light=[190,230,247],dark=[22,86,161]
  return `rgb(${light.map((a,i)=>Math.round(a+(dark[i]-a)*t)).join(',')})`
}
