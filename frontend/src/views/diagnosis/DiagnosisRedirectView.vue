<script setup>
import { onMounted } from 'vue'

onMounted(() => {
  window.location.replace('/diagnostic-center/')
})
</script>

<template>
  <main class="diagnosis-redirect" aria-live="polite">正在进入诊断中心…</main>
</template>

<style scoped>
.diagnosis-redirect {
  min-height: 100vh;
  display: grid;
  place-items: center;
  color: #5f7478;
  background: #f4f7f6;
  font: 600 14px "Avenir Next", "PingFang SC", sans-serif;
}
</style>
