<script setup>
defineProps({
  tag: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  steps: { type: Array, default: () => [] },
  heroTags: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
  hideHero: { type: Boolean, default: false },
  hideAnswers: { type: Boolean, default: false },
  answer: { type: Object, default: null },
})
</script>

<template>
  <div class="geo-v2 geo-page">
    <section v-if="!hideHero" class="gv2-hero" :class="{ compact }">
      <div>
        <span v-if="tag" class="gv2-kicker">{{ tag }}</span>
        <h1>{{ title }}</h1>
        <p v-if="desc" class="gv2-desc">{{ desc }}</p>
        <div v-if="heroTags.length" class="gv2-hero-tags">
          <span v-for="t in heroTags" :key="t">{{ t }}</span>
        </div>
        <div class="gv2-hero-actions">
          <slot name="actions" />
        </div>
      </div>
      <div v-if="steps.length && !compact" class="gv2-steps">
        <div v-for="(step, i) in steps" :key="i" class="gv2-step">
          <b>{{ String(i + 1).padStart(2, '0') }}</b>
          <span>{{ Array.isArray(step) ? step[0] : step }}</span>
          <small v-if="Array.isArray(step) && step[1]">{{ step[1] }}</small>
        </div>
      </div>
    </section>

    <section v-if="!hideAnswers && answer" class="gv2-answers">
      <article v-for="key in ['now', 'why', 'next']" :key="key" class="gv2-answer">
        <div class="lbl">{{ answer[key]?.[0] }}</div>
        <strong>{{ answer[key]?.[1] }}</strong>
        <p v-if="answer[key]?.[2]">{{ answer[key][2] }}</p>
      </article>
    </section>

    <slot />
  </div>
</template>
