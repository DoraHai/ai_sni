<script setup>
import { computed, ref, watch } from 'vue'
import BrandProfileEditor from './BrandProfileEditor.vue'
import { splitLines } from '../brandProfileFields'
const props = defineProps({ draft:Object, missing:Array, editAll:Boolean })
defineEmits(['confirm','edit','field','back'])
// Keep initially missing inputs mounted while the user completes them.
const missingInputs = ref([...props.missing])
watch(() => props.missing, values => { for (const f of values) if (!missingInputs.value.some(x=>x.key===f.key)) missingInputs.value.push(f) })
const products = computed(() => splitLines(props.draft.core_products))
const host = computed(() => { try { return new URL(props.draft.website).hostname } catch { return props.draft.website } })
</script>
<template>
  <section class="fd-confirm" aria-labelledby="brand-confirm-title">
    <header class="bc-heading">
      <p class="bc-status" :class="{ 'bc-pending': missing.length }">
        <span aria-hidden="true">{{ missing.length ? '!' : '✓' }}</span>
        {{ missing.length ? '企业信息待补充' : '企业识别完成' }}
      </p>
      <h1 id="brand-confirm-title">{{ draft.name ? `我们找到「${draft.name}」了` : '确认你的企业信息' }}</h1>
      <p class="fd-intro">根据官网公开信息，我们识别到以下品牌与业务信息。<br>确认无误后即可开始诊断。</p>
    </header>

    <div class="bc-columns">
      <article class="fd-brand-summary" aria-label="企业识别结果">
        <div class="bc-identity">
          <div class="bc-avatar" aria-hidden="true">{{ Array.from((draft.name || '').trim())[0]?.toUpperCase() || '—' }}</div>
          <div class="bc-name">
            <h2>{{ draft.name || '品牌名称待补充' }}</h2>
            <span class="bc-identified">{{ draft.name ? '✓ 已识别' : '待补充' }}</span>
          </div>
        </div>
        <dl>
          <div><dt>行业</dt><dd>{{ draft.industry || '所属行业待补充' }}</dd></div>
          <div><dt>主要产品</dt><dd><ul v-if="products.length" class="bc-products"><li v-for="(product, index) in products" :key="index">{{ product }}</li></ul><span v-else>核心产品 / 服务待补充</span></dd></div>
          <div><dt>官网</dt><dd class="bc-website">{{ host }}</dd></div>
        </dl>
        <p class="bc-source">根据官网公开信息自动识别</p>
      </article>

      <aside class="bc-next" aria-labelledby="brand-next-title">
        <h2 id="brand-next-title">接下来，我们将检查</h2>
        <ul>
          <li><span class="bc-check" aria-hidden="true">✓</span><div><h3>SEO 搜索基础</h3><p>搜索发现、索引与基础优化问题</p></div></li>
          <li><span class="bc-check" aria-hidden="true">✓</span><div><h3>GEO / AI 理解能力</h3><p>检查 AI 是否容易理解企业和产品</p></div></li>
          <li><span class="bc-check" aria-hidden="true">✓</span><div><h3>AI 品牌可见性</h3><p>测试 AI 回答是否会提及该品牌</p></div></li>
          <li><span class="bc-check" aria-hidden="true">✓</span><div><h3>网站基础</h3><p>检查抓取、结构和页面性能</p></div></li>
        </ul>
      </aside>
    </div>

    <div v-if="editAll || missingInputs.length" id="brand-confirm-editor" class="bc-edit-panel">
      <p v-if="missing.length" class="fd-warning">还需要补充 {{ missing.length }} 项信息才能开始诊断</p>
      <BrandProfileEditor v-if="editAll" :draft="draft" @field="(...args)=>$emit('field',...args)" />
      <BrandProfileEditor v-else-if="missingInputs.length" :draft="draft" :fields="missingInputs" @field="(...args)=>$emit('field',...args)" />
    </div>

    <div class="fd-actions">
      <button class="fd-primary" :disabled="missing.length > 0" @click="$emit('confirm')">开始免费网站诊断 <span aria-hidden="true">→</span></button>
      <p class="bc-edit-prompt">信息不准确？ <button class="fd-secondary" :aria-expanded="editAll" :aria-controls="editAll || missingInputs.length ? 'brand-confirm-editor' : undefined" @click="$emit('edit')">{{ editAll ? '收起完整信息' : '修改企业信息' }}</button></p>
      <button class="fd-link bc-back" @click="$emit('back')">← 修改官网，重新识别</button>
    </div>
  </section>
</template>

<style scoped>
/* Only the confirmation stage receives the wider, more compact page frame. */
:global(.free-diagnosis:has(.fd-confirm) .fd-body) { max-width: 1140px; padding-top: 36px; padding-bottom: 24px; }
.free-diagnosis .fd-confirm { max-width: 1060px; }
.bc-heading { text-align: center; margin-bottom: 28px; }
.bc-status { display: flex; align-items: center; justify-content: center; gap: 8px; color: #267659; font-size: 13px; font-weight: 600; margin: 0 0 14px; animation: bc-reveal 220ms both; }
.bc-status > span { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: #e8f5ef; }
.bc-status.bc-pending { color: #936015; }
.bc-pending > span { background: #fff5df; }
.free-diagnosis .bc-heading h1 { font-size: clamp(28px, 3vw, 40px); line-height: 1.35; letter-spacing: -.035em; margin: 0 0 14px; overflow-wrap: anywhere; animation: bc-reveal 280ms 70ms both; }
.free-diagnosis .bc-heading .fd-intro { font-size: 14px; line-height: 1.8; margin: 0; }
.bc-columns { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 24px; align-items: stretch; animation: bc-reveal 350ms 140ms both; }
.free-diagnosis .fd-confirm .fd-brand-summary { margin: 0; padding: 28px 32px 20px; border: 1px solid var(--fd-line); border-radius: 14px; background: #fff; display: flex; flex-direction: column; }
.bc-identity { display: flex; align-items: center; gap: 16px; }
.bc-avatar { width: 58px; height: 58px; flex: 0 0 58px; display: grid; place-items: center; border-radius: 12px; background: #f0eaf8; color: #7033c5; font-size: 28px; font-weight: 600; }
.bc-name { min-width: 0; }
.free-diagnosis .fd-confirm .bc-name h2 { font-size: 24px; line-height: 1.4; margin: 0 0 6px; font-weight: 650; overflow-wrap: anywhere; }
.bc-identified { font-size: 12px; color: #267659; }
.free-diagnosis .fd-confirm dl { gap: 20px; margin: 26px 0 24px; }
.free-diagnosis .fd-confirm dl > div { grid-template-columns: 66px minmax(0, 1fr); gap: 18px; align-items: baseline; }
.free-diagnosis .fd-confirm dt { font-size: 13px; }
.free-diagnosis .fd-confirm dd { font-size: 14px; }
.bc-products { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.bc-products li { padding: 4px 10px; border-radius: 5px; background: #f6f5f8; border: 1px solid #eeebf1; font-size: 13px; overflow-wrap: anywhere; max-width: 100%; }
.bc-website { font-weight: 500; }
.free-diagnosis .fd-confirm .bc-source { margin: auto 0 0; padding-top: 16px; border-top: 1px solid #efecf2; font-size: 11px; color: var(--fd-muted); }
.bc-next { background: #f3f1f7; border-radius: 14px; padding: 28px; }
.bc-next h2 { font-size: 17px; line-height: 1.5; font-weight: 650; margin: 0 0 24px; }
.bc-next ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 21px; }
.bc-next li { display: flex; align-items: flex-start; gap: 12px; }
.bc-check { color: #847298; font-size: 14px; line-height: 24px; }
.bc-next h3 { font-size: 14px; font-weight: 600; margin: 0 0 4px; line-height: 1.7; }
.bc-next p { font-size: 12px; color: var(--fd-muted); margin: 0; line-height: 1.7; }
.bc-edit-panel { margin-top: 24px; padding: 4px 24px; border: 1px solid var(--fd-line); border-radius: 12px; background: #fff; }
.free-diagnosis .fd-confirm .fd-actions { display: flex; flex-direction: column; align-items: center; gap: 0; margin: 28px 0 0; }
.free-diagnosis .fd-confirm .fd-primary { min-width: 320px; min-height: 52px; font-size: 15px; border-radius: 8px; }
.bc-edit-prompt { color: var(--fd-muted); font-size: 12px; margin: 8px 0 0; }
.free-diagnosis .fd-confirm .fd-secondary { background: transparent; border: 0; padding: 10px 2px; min-height: 40px; border-radius: 3px; font-size: 12px; color: var(--fd-purple); }
.free-diagnosis .fd-confirm .fd-secondary:hover { text-decoration: underline; text-underline-offset: 4px; }
.free-diagnosis .fd-confirm .bc-back { color: var(--fd-muted); font-size: 12px; padding: 8px 0; min-height: 36px; }
.free-diagnosis .fd-confirm .bc-back:hover { color: var(--fd-ink); }
@keyframes bc-reveal { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 700px) {
  :global(.free-diagnosis:has(.fd-confirm) .fd-body) { padding: 28px 20px 16px; }
  .bc-heading { margin-bottom: 24px; }
  .free-diagnosis .bc-heading h1 { font-size: 28px; }
  .free-diagnosis .bc-heading .fd-intro { font-size: 13px; }
  .bc-columns { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .free-diagnosis .fd-confirm .fd-brand-summary { padding: 22px; }
  .free-diagnosis .fd-confirm .bc-name h2 { font-size: 22px; }
  .free-diagnosis .fd-confirm dl > div { gap: 12px; grid-template-columns: 58px minmax(0, 1fr); }
  .bc-avatar { width: 50px; height: 50px; flex-basis: 50px; font-size: 25px; }
  .bc-next { padding: 24px; }
  .bc-next h2 { margin-bottom: 18px; }
  .bc-next ul { gap: 16px; }
  .free-diagnosis .fd-confirm .fd-primary { min-width: 0; width: 100%; }
  .bc-edit-prompt, .free-diagnosis .fd-confirm .bc-back { text-align: center; }
  .bc-edit-panel { padding-inline: 16px; }
}
@media (prefers-reduced-motion: reduce) { .bc-status, .bc-heading h1, .bc-columns { animation: none; } }
</style>
