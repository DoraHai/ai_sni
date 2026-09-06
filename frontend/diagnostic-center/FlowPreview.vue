<script setup>
import { nextTick, onMounted, ref } from 'vue'
import FreeDiagnosisFlow from '../src/views/diagnosis/flow/FreeDiagnosisFlow.vue'
import { useFreeDiagnosisFlow } from '../src/views/diagnosis/useFreeDiagnosisFlow'
const audit=ref(null), pageSpeed=ref(null)
const brand={name:'诺德 NORD（测试样例）',industry:'工业驱动技术',website:'https://www.nord.cn/cn/home-cn.jsp',core_products:['减速机','减速电机','变频器','分布式驱动系统']}
const params = new URLSearchParams(location.search)
const screen=params.get('screen') || 'entry'
const calls={discover:0,save:0,audit:0,sample:0,performance:0}
const api={
  async discoverGeoBrand(){calls.discover++;return {brand}},
  async fetchGeoAssetProfile(){return {brand:{...brand,competitors:[{name:'已有竞品',confirmed:true}],proof_points:['已有证明']}}},
  async saveGeoBrand(payload){calls.save++;return {brand:payload}},
  async runGeoAudit(){calls.audit++;if(screen==='progress')return new Promise(()=>{});return {id:1,score:67,ai_enabled:true,url:brand.website,final_url:brand.website,problems:[{severity:'high'},{severity:'high'},...Array.from({length:5},()=>({severity:'medium'}))],snapshot:{}}},
  async runDeepSeekSample(){calls.sample++;return new Promise(()=>{})},
  async fetchPageSpeedInsights(){calls.performance++;return {status:'unavailable',reason:'本地样例未运行性能检测'}},
}
const flow=useFreeDiagnosisFlow({tenantId:ref(1),audit,pageSpeed,brandProfile:ref({}),brandReady:ref(false),url:ref(''),samplingLoading:ref(false),pageSpeedLoading:ref(false),sampleQuestions:ref(['','','']),ensureTenant:async()=>true,api,search:''})
const checks=ref('')
onMounted(async()=>{
  if(screen!=='entry'){flow.website.value=brand.website;await flow.discover();if(['progress','complete'].includes(screen))void flow.confirm()}
  if(params.has('check')){
    const passed=[];const check=(v,s)=>{if(!v)throw Error(s);passed.push(s)}
    try{
      await nextTick();check(calls.discover===0,'初始化不调用识别');
      const input=document.querySelector('#free-website');input.value=brand.website;input.dispatchEvent(new Event('input',{bubbles:true}));
      document.querySelector('.fd-url').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
      await new Promise(r=>setTimeout(r,50));await nextTick();
      check(!!document.querySelector('.fd-brand-summary'),'识别后显示品牌摘要');
      check(!document.querySelector('.fd-editor'),'完整表单默认折叠');
      document.querySelector('.fd-secondary').click();await nextTick();check(document.querySelectorAll('.fd-editor label').length===7,'完整七项字段可编辑');
      document.querySelector('.fd-secondary').click();await nextTick();
      document.querySelector('.fd-actions .fd-primary').click();await new Promise(r=>setTimeout(r,50));await nextTick();
      check(flow.stage.value==='report','诊断成功直接进入报告');check(calls.sample===1,'自动抽样只执行一次');
      check(!document.querySelector('.fd-complete'),'不显示完成中间页');
      check(document.documentElement.scrollWidth<=innerWidth,'无横向溢出');
      checks.value='PASS '+passed.join('；')
    }catch(e){checks.value='FAIL '+e.message}
  }
})
</script>
<template><output v-if="checks" id="ui-check-results">{{ checks }}</output><FreeDiagnosisFlow v-if="flow.stage.value!=='report'" :flow="flow" :audit="audit" @report="flow.showReport()"/><p v-else>本地样例已进入报告状态。正式环境此处恢复原报告和导航。</p></template>
