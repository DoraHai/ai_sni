<script setup>
defineProps({ channel: { type: Object, required: true } })
</script>

<template>
  <section class="channel-reservation" aria-labelledby="channel-title">
    <p class="eyebrow">SEM · 广告渠道</p>
    <div class="channel-heading">
      <h1 id="channel-title">{{ channel.name }}</h1>
      <span class="status">待开放</span>
    </div>
    <p class="subtitle">{{ channel.subtitle }}</p>
    <p>{{ channel.description }}</p>
    <div class="notice" role="note">
      这里仅预留入口，尚未连接此平台。不会展示百度数据，不会发起授权、同步或真实资金回写。
      当前客户的百度业务仍通过原有菜单操作。
    </div>
    <h2>计划接入范围（均未开放）</h2>
    <ul class="capabilities">
      <li v-for="item in ['账户授权', '只读报表', '计划与关键词管理', '受控回写与台账']" :key="item">
        <span>{{ item }}</span><span class="pending">待开放</span>
      </li>
    </ul>
    <p class="footnote">开放时间待定；不会自动继承百度账户授权或真实回写权限。</p>
  </section>
</template>

<style scoped>
.channel-reservation { max-width: 900px; margin: 12px auto; padding: 28px; color: var(--el-text-color-primary); background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 16px; }
.eyebrow, .subtitle, .footnote { color: var(--el-text-color-secondary); }
.eyebrow { font-size: 13px; letter-spacing: .08em; }
.channel-heading { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
h1 { margin: 4px 0; font-size: 30px; }
h2 { margin-top: 28px; font-size: 17px; }
p, .notice { line-height: 1.8; }
.status { padding: 4px 12px; border-radius: 20px; background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); }
.notice { margin-top: 24px; padding: 16px; border-left: 3px solid var(--el-color-warning); background: var(--el-fill-color-light); }
.capabilities { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; list-style: none; padding: 0; }
.capabilities li { display: flex; justify-content: space-between; gap: 12px; padding: 16px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.pending { color: var(--el-text-color-secondary); white-space: nowrap; }
.footnote { font-size: 13px; }
@media (max-width: 600px) { .capabilities { grid-template-columns: 1fr; } .channel-reservation { padding: 18px; } }
</style>
