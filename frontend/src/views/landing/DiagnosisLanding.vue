<script setup>
import { ref } from 'vue'
import { session } from '../../store/session'
import { loginUrl } from '../../auth/loginRedirect'
import { initialWebsite, diagnosisDestination } from '../diagnosis/diagnosisWebsite'
import WebsiteEntry from '../diagnosis/flow/WebsiteEntry.vue'
import '../diagnosis/flow/free-diagnosis.css'
import logo from '../../assets/g-snipers-purple-logo.png'
const initial = initialWebsite(window.location.search)
const website = ref(initial.website)
const error = ref(initial.error)
function startDiagnosis() {
  try {
    const target = diagnosisDestination(website.value)
    window.location.assign(session.isLoggedIn ? target : loginUrl(target))
  } catch {
    error.value = '请输入有效的公司官网地址，例如 https://example.com'
  }
}
</script>
<template>
  <main class="free-diagnosis">
    <header class="fd-header"><a href="/growth-sniper" class="fd-brand"><img :src="logo" alt=""><span>获客狙击手<small>G-SNIPERS</small></span></a><span>免费网站诊断</span></header>
    <div class="fd-body"><p v-if="error" class="fd-error" role="alert">{{ error }}</p><WebsiteEntry v-model:website="website" @start="startDiagnosis" /><p class="fd-note" style="text-align:center">继续后按当前账号体系登录，官网地址会自动保留。</p></div>
    <footer class="fd-footer">公开信息 · 真实检测 · 由你确认</footer>
  </main>
</template>
