<script setup>
/**
 * 开户检查表跳过来时，落地页顶部接着说「还差什么」。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const TITLES = {
  engines: '还差监测引擎',
  engine_keys: '还差引擎真采样 Key',
  ai_key: '还差写稿用的 AI Key',
  patrol: '还没打开定时巡检',
  facts: '事实卡还不够，或还没核验',
  channel: '还没配发布渠道',
  brand_terms: '还没填品牌词',
  businesses: '还没建优化业务',
  prompts: '还没建意图词',
  gaps: '品牌没被提到，先补内容',
}

const route = useRoute()
const hint = computed(() => {
  const need = String(route.query.need || '').trim()
  const why = String(route.query.why || '').trim()
  if (!need && !why) return null
  return {
    title: TITLES[need] || '开户还差这一步',
    detail: why,
  }
})
</script>

<template>
  <el-alert
    v-if="hint"
    type="warning"
    show-icon
    class="mb"
    :title="hint.title"
    :description="hint.detail || undefined"
  />
</template>
