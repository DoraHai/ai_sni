import {createHostSessionAdapter} from './host-session-adapter.mjs';
import {mountConnectedWorkbench} from './connected-workbench.mjs';
const root=document.querySelector('#app'),config=window.CUSTOMER_WORKBENCH_HOST;
if(!config){
  root.innerHTML='<div class="connected-state"><h2>客户工作台 · 未连接宿主身份</h2><p>此入口只使用真实契约，不加载演示数据。请由现有登录宿主注入会话与已选择的客户、站点。</p><a href="index.html">打开独立演示模式</a></div>';
}else{
  const host=createHostSessionAdapter({...config,origin:location.origin,returnPath:location.pathname+location.search+location.hash});
  window.WORKBENCH_CONNECTED=mountConnectedWorkbench({root,host,environmentLabel:config.environmentLabel||'同源契约模式',demoHref:config.demoHref});
}
