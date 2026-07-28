<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <el-empty :description="`「${route.meta.title}」开发中，原型见 原型3.0claude工作流 对应页面`" />
</template>
