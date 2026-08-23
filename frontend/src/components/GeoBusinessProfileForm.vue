<script setup>
/**
 * 品牌信息页：仅呈现原型定义的品牌资料字段。
 */
defineProps({
  disabled: { type: Boolean, default: false },
})

const form = defineModel({ type: Object, required: true })

const fields = [
  { key: 'product_name', label: '品牌名称', placeholder: '填写对外使用的品牌或产品名称' },
  { key: 'website', label: '官网链接', placeholder: 'https://example.com' },
  { key: 'industry', label: '所属行业', placeholder: '如：智能客服 / B2B SaaS' },
  { key: 'summary', label: '品牌简介', type: 'textarea', rows: 3, placeholder: '简要说明品牌、产品和服务内容' },
  { key: 'honors', label: '品牌荣誉', type: 'textarea', rows: 2, placeholder: '逗号或换行分隔；仅记录可佐证的荣誉' },
  { key: 'qualifications', label: '资质证书', type: 'textarea', rows: 2, placeholder: '逗号或换行分隔；仅记录可佐证的资质' },
]
</script>

<template>
  <el-form label-width="96px" :disabled="disabled">
    <el-form-item
      v-for="f in fields"
      :key="f.key"
      :label="f.label"
    >
      <el-input
        v-if="f.type === 'textarea'"
        v-model="form[f.key]"
        type="textarea"
        :rows="f.rows || 2"
        :placeholder="f.placeholder"
      />
      <el-input
        v-else
        v-model="form[f.key]"
        :placeholder="f.placeholder"
      />
    </el-form-item>
  </el-form>
</template>
