<script setup>
defineProps({
  icon: { type: String, default: '◌' },
  title: { type: String, required: true },
  desc: { type: String, default: '' },
})
</script>

<template>
  <div class="geo-empty" role="status">
    <div class="geo-empty-icon" aria-hidden="true">{{ icon }}</div>
    <div class="geo-empty-title">{{ title }}</div>
    <p v-if="desc" class="geo-empty-desc">{{ desc }}</p>
    <div v-if="$slots.action" class="geo-empty-action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.geo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 20px;
  text-align: center;
  border: 1px dashed #e2e8f0;
  border-radius: 12px;
  background: #fafbfc;
}
.geo-empty-icon {
  font-size: 28px;
  color: #94a3b8;
  margin-bottom: 10px;
  line-height: 1;
}
.geo-empty-title {
  font-size: 15px;
  font-weight: 650;
  color: #334155;
}
.geo-empty-desc {
  margin: 8px 0 0;
  max-width: 28rem;
  font-size: 13px;
  color: #64748b;
  line-height: 1.55;
}
.geo-empty-action {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 14px;
}
</style>
