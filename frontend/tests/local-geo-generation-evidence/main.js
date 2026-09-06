import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Card from '../../src/components/GeoGenerationEvidence.vue'
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]})
const evidence={ok:false,bound_count:4,eligible_count:1,min_eligible:3,message:'可发布证据 1/3（未核验、缺来源、过期）',
 action:'请核验事实、补来源，并移除或更新已过期事实后再生成/发布',
 excluded:[{id:2,title:'参数手册',labels:['未核验']},{id:3,title:'产品案例',labels:['缺来源']},{id:4,title:'旧资料',labels:['已过期']}]}
createApp({render:()=>h('main',{style:'max-width:800px;margin:24px auto'},[
 h('h2','仅静态模拟，不读写客户资料'),h(Card,{evidence})])}).use(router).mount('#app')
