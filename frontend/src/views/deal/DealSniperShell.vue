<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const isPortal = computed(() => route.path === '/deal-sniper/portal')
const portalState = ref('loading')
const frameVersion = ref(0)
let loadTimer
const prototypeSrc = computed(() => {
  if (route.path === '/deal-sniper/portal') return '/deal-sniper-prototype/index.html?rev=portal-20260809-v1'
  const { section, page } = route.params
  if (section && page) return `/deal-sniper-prototype/${section}/${page}.html`
  return '/deal-sniper-prototype/index.html'
})

function startLoading() {
  clearTimeout(loadTimer)
  portalState.value = 'loading'
  if (isPortal.value) {
    loadTimer = setTimeout(() => { portalState.value = 'failed' }, 10000)
  }
}

function onFrameLoad(event) {
  if (!isPortal.value) return
  clearTimeout(loadTimer)
  try {
    // load also fires for blocked frames, error pages and the empty SPA fallback.
    const doc = event.target.contentDocument
    portalState.value = doc?.querySelector('.hero h1') && doc?.querySelector('.cards a.module')
      ? 'ready' : 'failed'
  } catch {
    portalState.value = 'failed'
  }
}

function retryPortal() {
  startLoading()
  frameVersion.value += 1
}

watch(prototypeSrc, startLoading, { immediate: true })
onBeforeUnmount(() => clearTimeout(loadTimer))
</script>

<template>
  <main class="prototype-wrap">
    <section v-if="isPortal && portalState !== 'ready'" class="portal-status" aria-live="polite">
      <h1>{{ portalState === 'failed' ? '平台门户暂时无法显示' : '正在打开平台门户' }}</h1>
      <p v-if="portalState === 'failed'">请重试，或直接打开平台门户。如果仍然打不开，请联系平台管理员处理。</p>
      <p v-else>请稍候，也可以直接打开平台门户。</p>
      <div class="portal-actions">
        <button v-if="portalState === 'failed'" type="button" @click="retryPortal">重新加载</button>
        <a :href="prototypeSrc">直接打开平台门户</a>
      </div>
    </section>
    <iframe
      :key="`${prototypeSrc}:${frameVersion}`"
      class="prototype-frame"
      :class="{ 'portal-pending': isPortal && portalState !== 'ready' }"
      :src="prototypeSrc"
      title="Growth Sniper 产品原型"
      @load="onFrameLoad"
    />
  </main>
</template>

<style scoped>
.prototype-wrap {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: #f6f7fb;
}

.portal-pending {
  visibility: hidden;
}

.portal-status {
  position: absolute;
  inset: 0;
  padding: 48px 24px;
  text-align: center;
}

.portal-status h1 { font-size: 24px; }
.portal-status p { line-height: 1.7; }
.portal-actions { display: flex; justify-content: center; gap: 20px; align-items: center; }
.portal-actions a { color: #185fa5; }
.portal-actions button { padding: 8px 16px; cursor: pointer; }

.prototype-frame {
  width: 100%;
  height: 100%;
  display: block;
  border: 0;
  background: #fff;
}
</style>
