<script setup>
import { session } from '../../store/session'
import GeoPublicationGroupsContext from '../../components/GeoPublicationGroupsContext.vue'
</script>

<template>
  <main class="geo-publications-page">
    <header><div><p class="eyebrow">GEO · 项目交付</p><h1>发布记录 · 外部回传</h1></div><router-link to="/distribution-inbox">多号通回传收件箱</router-link></header>
    <p>按文章查看系统原生登记与外部回传，也可按来源筛选。原生监测和多号通投递回执仍保留各自入口。</p>
    <GeoPublicationGroupsContext :tenant-id="session.tenantId" />
  </main>
</template>
<style scoped>.geo-publications-page{padding:28px;max-width:1260px;margin:auto;color:#1e293b}.geo-publications-page>header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}h1{font-size:28px;margin:8px 0}.eyebrow{font-size:12px;color:#6366a2;letter-spacing:.08em}.geo-publications-page>p{color:#64748b;font-size:14px;line-height:1.8}a{color:#4f46e5}@media(max-width:600px){.geo-publications-page{padding:16px}h1{font-size:24px}}</style>
