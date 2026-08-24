<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <strong>404</strong>
    <h1>页面不存在</h1>
    <p>当前地址不是有效的 SEM 功能路径，请通过左侧菜单进入对应页面。</p>
    <el-button type="primary" @click="router.push('/monitor/dashboard')">返回数据看板</el-button>
  </div>
</template>

<style scoped>
.not-found{display:grid;justify-items:center;align-content:center;min-height:60vh;text-align:center}.not-found strong{font-size:64px;color:var(--sem-primary)}.not-found h1{margin:8px 0;font-size:24px}.not-found p{margin:0 0 20px;color:var(--sem-text-sub)}
</style>
