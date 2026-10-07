import {escapeText as esc} from './customer-display.mjs';

// Memory belongs to this mounted, authenticated scope. Never persist text or authority.
export function createInputProtection(root) {
  let edited=new Map(),recovery=null,context='';
  const fields=()=>[...root.querySelectorAll('#page input[id],#page textarea[id],#page select[id]')].filter(e=>!e.disabled);
  const value=e=>({id:e.id,label:e.labels?.[0]?.textContent?.trim()||e.id,value:e.type==='checkbox'?e.checked:e.value,type:e.type});
  const capture=()=>edited.size?{context,fields:fields().map(value)}:null;
  const clear=()=>{edited.clear();recovery=null;};
  function input(e){if(e.target.closest('#page')&&e.target.id&&!e.target.disabled)edited.set(e.target.id,value(e.target));}
  root.addEventListener('input',input);
  const unload=e=>{if(edited.size||recovery){e.preventDefault();e.returnValue='';}};
  window.addEventListener('beforeunload',unload);
  return {
    capture,
    setContext(value){context=value;},
    recover(snapshot){if(snapshot?.fields.length)recovery=snapshot;edited.clear();},
    saved(){edited.clear();recovery=null;},
    clear,
    discardRecovery(){if(window.confirm('放弃保留的输入？'))recovery=null;},
    leave(keepRecovery=false){if(!edited.size&&(!recovery||keepRecovery))return true;if(!window.confirm('有尚未保存的输入。确定：放弃修改并离开；取消：留在此页继续编辑。'))return false;edited.clear();if(!keepRecovery)recovery=null;return true;},
    render(){
      for(const e of root.querySelectorAll('[data-cycle],[data-ai-fact],[data-ai-keyword]'))if(!e.id)e.id='draft-'+(e.dataset.cycle?'cycle-'+e.dataset.cycle:e.dataset.aiFact?'fact-'+e.dataset.aiFact:'keyword-'+e.dataset.aiKeyword);
      for(const saved of edited.values()){const e=root.querySelector('#'+saved.id);if(e&&!e.disabled){if(e.type==='checkbox')e.checked=saved.value;else e.value=saved.value;}}
      root.querySelector('#input-recovery')?.remove();
      if(!recovery)return;
      const canRestore=recovery.context===context&&recovery.fields.every(v=>{const e=root.querySelector('#'+v.id);return e&&!e.disabled;});
      const box=document.createElement('section');box.id='input-recovery';box.className='input-recovery';
      box.innerHTML=`<h3>输入已保留，尚未提交成功</h3><p>先重新读取当前稿件或计划，并打开原表单，再恢复输入。请核对新版本和服务器结果；系统不会自动重发。人工核实勾选需要重新确认。</p><button data-action="restore-input" ${canRestore?'':'disabled'}>恢复到已重新读取的表单</button><button data-action="discard-input">放弃保留的输入</button><details><summary>查看、复制保留文字</summary>${recovery.fields.filter(v=>v.type!=='checkbox').map(v=>`<label>${esc(v.label)}<textarea readonly>${esc(v.value)}</textarea></label>`).join('')}</details>`;
      root.querySelector('.connected-main')?.append(box);
    },
    restore(){
      if(!recovery||recovery.context!==context||!recovery.fields.every(v=>{const e=root.querySelector('#'+v.id);return e&&!e.disabled;}))return;
      const saved=recovery.fields;recovery=null;
      for(const v of saved){const e=root.querySelector('#'+v.id);if(e.type==='checkbox')e.checked=v.id==='manual-verified'?false:v.value;else e.value=v.value;e.dispatchEvent(new Event('input',{bubbles:true}));}
      this.render();
    },
    dispose(){clear();root.removeEventListener('input',input);window.removeEventListener('beforeunload',unload);},
  };
}
