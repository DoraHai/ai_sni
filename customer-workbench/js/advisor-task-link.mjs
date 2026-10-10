export function onsiteTaskFromSearch(search){
  const p=new URLSearchParams(search),value=p.get('onsite_task_id');
  return p.getAll('onsite_task_id').length===1&&/^[1-9]\d*$/.test(value||'')&&Number.isSafeInteger(Number(value))&&Number(value)<Number.MAX_SAFE_INTEGER?Number(value):null;
}
// A deep link is only a selection hint. The original scoped client re-reads the row.
export async function readOnsiteDeepLink(client,taskId){
  const data=await client.list(taskId+1),selected=data.items.find(t=>t.id===taskId);
  if(!selected)throw Error('指定任务当前不可见，请返回顾问列表重新读取。');
  return {data,selected,before:taskId+1};
}
