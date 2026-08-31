<template>
  <section class="geo-prototype-toolbar" aria-label="页面工具栏">
    <div class="geo-prototype-toolbar__filters">
      <slot name="filters" />
    </div>
    <div class="geo-prototype-toolbar__actions">
      <slot />
      <slot name="actions" />
    </div>
  </section>
</template>

<style scoped>
.geo-prototype-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.geo-prototype-toolbar__filters,
.geo-prototype-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
