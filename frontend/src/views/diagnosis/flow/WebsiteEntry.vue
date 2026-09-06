<script setup>
defineProps({ website:String })
defineEmits(['update:website','start'])
const capabilities = [ ['SEO 可见性','搜索发现与基础优化问题'], ['GEO 就绪度','AI 是否容易理解网站内容'], ['AI 品牌可见性','AI 回答是否会提及品牌'], ['网站基础','抓取、结构与页面性能'] ]
</script>
<template>
  <section class="fd-entry">
    <p class="fd-eyebrow">从一个网址，开始了解你的品牌</p>
    <h1>看看你的品牌，<br>在搜索与 AI 里<span>表现如何</span></h1>
    <p class="fd-intro">输入公司官网，免费检测 SEO、GEO、AI 品牌可见性与网站基础问题。</p>
    <form class="fd-url" @submit.prevent="$emit('start')">
      <label for="free-website" class="fd-sr">公司官网</label>
      <input id="free-website" :value="website" @input="$emit('update:website', $event.target.value)" placeholder="https://www.example.com" autocomplete="url" inputmode="url" required maxlength="2048">
      <button class="fd-primary">免费诊断 <span aria-hidden="true">→</span></button>
    </form>
    <p class="fd-note">无需复杂配置 · 使用官网公开信息完成检测</p>
    <div class="fd-capabilities"><section v-for="([title, text], index) in capabilities" :key="title"><span class="fd-number">0{{ index + 1 }}</span><h2>{{ title }}</h2><p>{{ text }}</p></section></div>
  </section>
</template>
