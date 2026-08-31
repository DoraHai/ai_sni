<script setup>
defineProps({
  kind: { type: String, default: 'info' },
  message: { type: String, required: true },
})

defineEmits(['retry'])
</script>

<template>
  <aside class="geo-prototype-context-notice" :data-kind="kind" role="status">
    <p>{{ message }}</p>
    <button type="button" @click="$emit('retry')">重试</button>
  </aside>
</template>
