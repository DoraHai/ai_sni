<script setup>
defineProps({ evidence: Object })
</script>
<template>
  <section class="generation-evidence" aria-label="母稿生成资料检查">
    <template v-if="evidence">
      <b>{{ evidence.message }}</b>
      <p>已绑定 {{ evidence.bound_count }} 条，可用于生成 {{ evidence.eligible_count }} 条，至少需要 {{ evidence.min_eligible }} 条。</p>
      <ul v-if="evidence.excluded?.length">
        <li v-for="row in evidence.excluded" :key="row.id">#{{ row.id }} {{ row.title }}：{{ row.labels.join('、') }}</li>
      </ul>
      <p v-if="!evidence.ok">{{ evidence.action }}。更新后回到本任务重新绑定并刷新。</p>
      <p v-else>资料条件已满足；生成质量、技术检查和客户审核仍需分别通过。</p>
    </template>
    <p v-else>资料校验状态尚未读取，请刷新任务；不能仅凭绑定条数判断可生成。</p>
    <router-link to="/geo/facts">打开知识库补充或核验资料</router-link>
  </section>
</template>
<style scoped>
.generation-evidence { margin:12px 0; padding:12px; background:#f5f8fc; border:1px solid #dbe4ee; border-radius:8px; font-size:13px; }
p, li { margin:6px 0; line-height:1.6; overflow-wrap:anywhere; }
ul { max-height:160px; overflow:auto; padding-left:20px; }
</style>
