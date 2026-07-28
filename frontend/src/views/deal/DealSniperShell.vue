<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const prototypeSrc = computed(() => {
  if (route.path === '/deal-sniper/portal') return '/deal-sniper-prototype/index.html'
  const { section, page } = route.params
  if (section && page) return `/deal-sniper-prototype/${section}/${page}.html`
  return '/deal-sniper-prototype/index.html'
})
</script>

<template>
  <main class="prototype-wrap">
    <iframe
      class="prototype-frame"
      :src="prototypeSrc"
      title="Growth Sniper 产品原型"
    />
  </main>
</template>

<style scoped>
.prototype-wrap {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: #f6f7fb;
}

.prototype-frame {
  width: 100%;
  height: 100%;
  display: block;
  border: 0;
  background: #fff;
}
</style>
