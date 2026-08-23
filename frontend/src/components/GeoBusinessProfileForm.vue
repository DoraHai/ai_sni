<script setup>
/**
 * 业务线画像：Brief / 母稿 / 报告统一读取的上下文字段。
 */
defineProps({
  disabled: { type: Boolean, default: false },
})

const form = defineModel({ type: Object, required: true })

const fields = [
  { key: 'product_name', label: '品牌/产品名', placeholder: '本条业务对外使用的产品名，不要填租户总品牌（除非就是同一产品）' },
  { key: 'website', label: '品牌网站', placeholder: 'https:// 官网结构优化会用这个地址扫描' },
  { key: 'summary', label: '产品简介', type: 'textarea', rows: 2, placeholder: '一句话说明卖什么、解决什么问题' },
  { key: 'capabilities', label: '核心能力', type: 'textarea', rows: 2, placeholder: '逗号或换行分隔' },
  { key: 'audience', label: '目标客户', placeholder: '如：中大型企业客服负责人' },
  { key: 'scenarios', label: '典型场景', type: 'textarea', rows: 2, placeholder: '逗号或换行分隔' },
  { key: 'geo_scope', label: '地域范围', placeholder: '如：中国大陆 / 华东制造业' },
  { key: 'industry', label: '行业', placeholder: '如：智能客服 / B2B SaaS' },
  { key: 'competitors', label: '主要竞品', placeholder: '逗号分隔，如：七鱼, Udesk' },
  { key: 'recommend_reasons', label: '推荐理由', type: 'textarea', rows: 2, placeholder: '可核验的推荐点，逗号或换行分隔' },
  { key: 'banned_claims', label: '禁止表述', placeholder: '如：第一名, 保证被 AI 收录' },
  { key: 'cta', label: 'CTA', placeholder: '如：预约演示 / 下载方案' },
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
