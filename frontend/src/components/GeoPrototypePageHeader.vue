<script setup>
defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
})
</script>

<template>
  <header class="geo-topbar">
    <div class="geo-topbar-copy">
      <h1>{{ title }}</h1>
      <div v-if="sub" class="sub">{{ sub }}</div>
      <slot />
    </div>
    <div class="right">
      <slot name="actions" />
    </div>
  </header>
</template>
