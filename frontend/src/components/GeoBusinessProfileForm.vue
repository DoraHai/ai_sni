<script setup>
/**
 * 品牌资料：与原型一致的 6 个字段，标签在上、控件通栏。
 */
defineProps({
  disabled: { type: Boolean, default: false },
})

const form = defineModel({ type: Object, required: true })

const fields = [
  { key: 'product_name', label: '品牌名称', placeholder: '对外使用的品牌或产品名' },
  { key: 'website', label: '官网地址', placeholder: 'https://example.com' },
  { key: 'industry', label: '所属行业', placeholder: '如：智能客服 / B2B SaaS' },
  {
    key: 'summary',
    label: '品牌简介',
    type: 'textarea',
    rows: 4,
    placeholder: '用几句话说明品牌、产品和服务',
  },
  {
    key: 'honors',
    label: '品牌口号',
    type: 'textarea',
    rows: 3,
    placeholder: '便于搜索和引用时被记住的一句话主张',
  },
  {
    key: 'qualifications',
    label: '资质证书',
    type: 'textarea',
    rows: 3,
    placeholder: '可核验的资质、认证，逗号或换行分隔',
  },
]
</script>

<template>
  <div class="brand-fields" :class="{ disabled }">
    <label v-for="f in fields" :key="f.key" class="brand-field">
      <span class="brand-label">{{ f.label }}</span>
      <el-input
        v-if="f.type === 'textarea'"
        v-model="form[f.key]"
        type="textarea"
        :rows="f.rows || 3"
        :placeholder="f.placeholder"
        :disabled="disabled"
      />
      <el-input
        v-else
        v-model="form[f.key]"
        :placeholder="f.placeholder"
        :disabled="disabled"
      />
    </label>
  </div>
</template>

<style scoped>
.brand-fields {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 760px;
}
.brand-field { display: block; }
.brand-label {
  display: block;
  margin-bottom: 8px;
  color: #374151;
  font-size: 13px;
  font-weight: 650;
}
.brand-fields :deep(.el-textarea__inner),
.brand-fields :deep(.el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e5e7eb inset;
}
.brand-fields :deep(.el-input__wrapper:hover),
.brand-fields :deep(.el-textarea__inner:hover) {
  box-shadow: 0 0 0 1px #c4b5fd inset;
}
.brand-fields :deep(.el-input__wrapper.is-focus),
.brand-fields :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px #7c3aed inset;
}
.disabled { opacity: 0.65; pointer-events: none; }
</style>
