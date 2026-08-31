<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  router.replace({ path: '/geo/visibility', query: route.query })
})
</script>

<template>
  <div class="geo-visibility-compat" aria-live="polite">
    正在进入已合并的 AI 可见度页…
  </div>
</template>
