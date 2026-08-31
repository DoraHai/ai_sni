<script setup>
defineProps({
  title: { type: String, required: true },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
})
</script>

<template>
  <section class="geo-prototype-table-section" :aria-busy="loading">
    <h2>{{ title }}</h2>
    <div class="geo-prototype-table-section__body">
      <slot />
    </div>
    <p class="geo-prototype-table-section__empty">{{ emptyText }}</p>
    <footer class="geo-prototype-table-section__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>
