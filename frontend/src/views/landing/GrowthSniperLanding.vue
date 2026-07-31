<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'

const assetRoot = import.meta.env.BASE_URL === '/growth-sniper/' ? '/growth-sniper/landing' : '/landing'
const asset = (name) => `${assetRoot}/${name}`
const mobileOpen = ref(false)
const activeSection = ref('diagnosis')
const diagnosisUrl = ref('')
const introSlide = ref(0)
const introPaused = ref(false)
const introMoving = ref(false)
const introTarget = ref(1)
const trialModalOpen = ref(false)
const trialSubmitting = ref(false)
const trialError = ref('')
const trialCountdown = ref(0)
const trialForm = reactive({
  name: '',
  email: '',
  phone: '',
  code: '',
})

const navItems = [
  ['diagnosis', '产品'],
  ['features', '解决方案'],
  ['process', '客户案例'],
  ['pricing', '定价'],
  ['contact', '资源'],
]

const painPoints = [
  { key: 'SEM', title: 'SEM跟不上', text: '投放成本翻升，关键词溢值低效，预算浪费严重' },
  { key: 'SEO', title: 'SEO跟不上', text: '排名波动不稳定，内容无流量，收录率极低' },
  { key: 'GEO', title: 'GEO跟不上', text: '本地曝光不足，地域定位不准，线索质量极差' },
]

const channels = [
  { key: 'SEM', title: 'SEM 智能出价', text: 'AI 智能调价，实时转化优化，最大化 ROI', image: asset('channel-sem.png') },
  { key: 'SEO', title: 'SEO 全域优化', text: '全站提权，内容智能优化，排名稳步提升', image: asset('channel-seo.png') },
  { key: 'GEO', title: 'GEO AI 搜索引擎优化', text: '地域精准覆盖，本地流量劫持，线索质量翻倍', image: asset('channel-geo.png') },
]

const process = [
  { icon: '⌘', title: '1. 接入渠道', text: '全域渠道打通，数据实时归集' },
  { icon: '▣', title: '2. AI 自动诊断与优化', text: '智能分析线索质量，自动优化获客策略' },
  { icon: '♟', title: '3. 线索自动打分与分配', text: '多维评分模型，精准分配优质线索' },
  { icon: '↗', title: '4. 数据复盘', text: '全链路数据复盘，持续提升转化效率' },
]

const clientLogos = [
  { name: 'WuiXi Biologics', line1: 'WuiXi', line2: 'Biologics', className: 'logo-wuxi' },
  { name: '3M', line1: '3M', className: 'logo-3m' },
  { name: 'NORD', line1: 'NORD' },
  { name: 'TÜV NORD', line1: 'TÜV NORD' },
  { name: 'NEXANS', line1: 'NEXANS' },
]

const prices = [
  {
    icon: '✣', name: '纯工具版', price: '¥399', suffix: '/月', note: '三模块打包 ¥999/月',
    items: ['全功能工具使用', '基础 AI 分析', '标准数据报表', '在线文档支持'],
  },
  {
    icon: '◉', name: 'AI + 人工标准版', price: '¥1,999', suffix: '/月', note: '三模块打包 ¥4,999/月',
    items: ['专属客户经理', 'AI 智能诊断优化', '策略定制与落地', '深度数据分析'], featured: true,
  },
  {
    icon: '♛', name: 'AI + 人工深度版', price: '定制方案', suffix: '', note: '深度人工保姆定制',
    items: ['1 对 1 专属服务', '全链路托管运营', '定制化获客方案', '效果保障与复盘'],
  },
]

let observer
let introTimer
let trialCountdownTimer
let touchStartX = 0

function startIntroTimer() {
  window.clearInterval(introTimer)
  if (introPaused.value || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  introTimer = window.setInterval(() => {
    moveIntroTo(introSlide.value + 1)
  }, 3000)
}

function moveIntroTo(index) {
  const target = (index + 2) % 2
  if (introMoving.value || target === introSlide.value) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    introSlide.value = target
    return
  }
  window.clearInterval(introTimer)
  introTarget.value = target
  introMoving.value = true
}

function finishIntroMove() {
  if (!introMoving.value) return
  introSlide.value = introTarget.value
  introMoving.value = false
  startIntroTimer()
}

function setIntroSlide(index) {
  const target = (index + 2) % 2
  if (target === introSlide.value) {
    startIntroTimer()
    return
  }
  moveIntroTo(target)
}

function pauseIntro(paused) {
  introPaused.value = paused
  if (paused) window.clearInterval(introTimer)
  else startIntroTimer()
}

function handleIntroTouchStart(event) {
  touchStartX = event.changedTouches[0]?.clientX ?? 0
}

function handleIntroTouchEnd(event) {
  const distance = (event.changedTouches[0]?.clientX ?? touchStartX) - touchStartX
  if (Math.abs(distance) > 45) setIntroSlide(introSlide.value + (distance < 0 ? 1 : -1))
}

onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting)
    if (visible.length) activeSection.value = visible.at(-1).target.id
  }, { rootMargin: '-18% 0px -48%', threshold: 0 })
  document.querySelectorAll('.gs-section[id]').forEach((el) => observer.observe(el))
  startIntroTimer()
})
onUnmounted(() => {
  observer?.disconnect()
  window.clearInterval(introTimer)
  window.clearInterval(trialCountdownTimer)
  document.body.style.overflow = ''
})

function scrollTo(id) {
  mobileOpen.value = false
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}

function goDiagnosis() {
  const target = new URL('/diagnosis', window.location.origin)
  if (diagnosisUrl.value.trim()) target.searchParams.set('url', diagnosisUrl.value.trim())
  window.location.assign(target.href)
}

function openTrialForm() {
  mobileOpen.value = false
  trialError.value = ''
  trialModalOpen.value = true
  pauseIntro(true)
  document.body.style.overflow = 'hidden'
}

function closeTrialForm() {
  trialModalOpen.value = false
  trialError.value = ''
  document.body.style.overflow = ''
  pauseIntro(false)
}

function sendTrialCode() {
  trialError.value = ''
  if (!/^1\d{10}$/.test(trialForm.phone)) {
    trialError.value = '请先输入有效手机号'
    return
  }
  if (trialCountdown.value) return
  trialCountdown.value = 60
  window.clearInterval(trialCountdownTimer)
  trialCountdownTimer = window.setInterval(() => {
    trialCountdown.value -= 1
    if (trialCountdown.value <= 0) window.clearInterval(trialCountdownTimer)
  }, 1000)
}

function submitTrialForm() {
  trialError.value = ''
  if (!trialForm.name.trim()) return void (trialError.value = '请填写您的称呼')
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trialForm.email)) return void (trialError.value = '请填写有效邮箱')
  if (!/^1\d{10}$/.test(trialForm.phone)) return void (trialError.value = '请填写有效手机号')
  if (!/^\d{4,6}$/.test(trialForm.code)) return void (trialError.value = '请填写验证码')

  trialSubmitting.value = true
  window.sessionStorage.setItem('growth-sniper-trial', JSON.stringify({
    name: trialForm.name.trim(),
    email: trialForm.email.trim(),
    phone: trialForm.phone,
  }))
  const target = new URL('/diagnosis', window.location.origin)
  if (diagnosisUrl.value.trim()) target.searchParams.set('url', diagnosisUrl.value.trim())
  window.location.assign(target.href)
}
</script>

<template>
  <div class="gs-site" :style="{ '--gs-stone': `url(${asset('stone-network.jpg')})` }">
    <header class="site-header">
      <a class="brand" href="#diagnosis" aria-label="获客狙击手 G-Snipers 首页" @click.prevent="scrollTo('diagnosis')">
        <span class="brand-mark"><img :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true"></span>
        <span class="brand-copy"><strong>G-Snipers</strong><em>获客狙击手</em></span>
      </a>
      <nav :class="{ open: mobileOpen }" aria-label="主导航">
        <a
          v-for="[id, label] in navItems"
          :key="id"
          :class="{ active: activeSection === id }"
          :href="`#${id}`"
          @click.prevent="scrollTo(id)"
        >{{ label }}</a>
      </nav>
      <button class="header-cta" type="button" @click="openTrialForm">免费试用</button>
      <button class="menu-button" type="button" aria-label="切换菜单" @click="mobileOpen = !mobileOpen">
        <span /><span /><span />
      </button>
    </header>

    <main>
      <section
        id="diagnosis"
        class="intro-carousel gs-section"
        aria-roledescription="carousel"
        aria-label="产品核心能力"
        tabindex="0"
        @keydown.left.prevent="setIntroSlide(introSlide - 1)"
        @keydown.right.prevent="setIntroSlide(introSlide + 1)"
        @touchstart.passive="handleIntroTouchStart"
        @touchend.passive="handleIntroTouchEnd"
      >
        <div class="intro-stage" :class="{ moving: introMoving }" @transitionend.self="finishIntroMove">
      <section
        class="intro-slide diagnostic-teaser diagnostic-first gs-section"
        :style="{ order: introSlide === 0 ? 0 : 1 }"
        :aria-hidden="introSlide !== 0"
        :inert="introSlide !== 0"
      >
        <div class="diagnosis-copy">
          <span class="kicker">免费诊断中心</span>
          <h2>你的专属工作台</h2>
          <p>3 分钟接入，AI 自动跑出品牌在搜索广告、自然搜索排名与 AI 搜索引擎中的真实表现。</p>
          <div class="capability-list">
            <span><i>◎</i>精准获客</span>
            <span><i>◉</i>AI 智能打分</span>
            <span><i>▥</i>数据分析</span>
            <span><i>↗</i>转化提效</span>
          </div>
          <form class="diagnosis-form" @submit.prevent="goDiagnosis">
            <input
              v-model="diagnosisUrl"
              type="url"
              inputmode="url"
              placeholder="请输入你的官网地址"
              aria-label="官网地址"
              @focus="pauseIntro(true)"
              @blur="pauseIntro(false)"
            >
            <button type="submit">开始免费诊断</button>
          </form>
          <small>无需安装代码 · 首次诊断免费 · 结果仅您可见</small>
        </div>
        <div class="dashboard-shell" aria-label="Growth Sniper 产品数据看板示意">
          <div class="dashboard-top">
            <span class="dash-brand"><b class="dash-dot" />Growth Sniper</span>
            <span>概览面板　线索管理　AI 打分　数据报告</span>
          </div>
          <div class="dashboard-body">
            <div class="dash-stats">
              <div><small>总线索量</small><strong>12,847</strong><em>↑ 18.6%</em></div>
              <div><small>转化率</small><strong>3.24%</strong><em>↑ 0.8%</em></div>
              <div><small>AI 预测得分</small><strong>87.3</strong><em class="good">优质线索 62%</em></div>
              <div><small>渠道占比</small><strong>42.6%</strong><em>SEM 渠道领先</em></div>
            </div>
            <div class="dash-panels">
              <div class="trend-panel">
                <h3>线索趋势分析</h3>
                <svg viewBox="0 0 520 160" aria-hidden="true">
                  <defs><linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#65e49a" stop-opacity=".38"/><stop offset="1" stop-color="#65e49a" stop-opacity="0"/></linearGradient></defs>
                  <path d="M10 130 C80 105,110 60,175 105 S285 25,350 72 S435 104,510 28 L510 150 L10 150 Z" fill="url(#areaFill)"/>
                  <path d="M10 130 C80 105,110 60,175 105 S285 25,350 72 S435 104,510 28" fill="none" stroke="#69e89c" stroke-width="4"/>
                </svg>
              </div>
              <div class="score-panel">
                <h3>线索质量评分</h3>
                <div class="score-gauge"><span>87.3<small>AI 综合打分</small></span></div>
              </div>
            </div>
            <div class="channel-summary">
              <span><b>SEM</b><strong>42.6%</strong><small>搜索营销</small></span>
              <span><b>SEO</b><strong>31.8%</strong><small>自然搜索</small></span>
              <span><b>GEO</b><strong>25.6%</strong><small>AI 搜索优化</small></span>
            </div>
          </div>
          <span class="demo-badge">产品界面示意</span>
        </div>
      </section>

      <section
        class="intro-slide hero gs-section"
        :style="{ order: introSlide === 1 ? 0 : 1 }"
        :aria-hidden="introSlide !== 1"
        :inert="introSlide !== 1"
      >
        <div class="hero-glow" />
        <div class="hero-inner">
          <div class="hero-copy reveal">
            <div class="eyebrow"><span /> 全链路 AI 获客系统</div>
            <h1><span class="title-main">精准获客</span><br class="title-break"><span>高效增长</span></h1>
            <p>全链路智能获客系统，让每一次触达都命中目标</p>
            <div class="hero-actions">
              <button class="button primary" type="button" @click="goDiagnosis">立即试用 14 天免费</button>
              <button class="button ghost" type="button" @click="scrollTo('contact')">预约演示 <span>↗</span></button>
            </div>
            <div class="trust-row">
              <span><i>✓</i> 无需信用卡</span>
              <span><i>✓</i> 5 分钟快速接入</span>
              <span><i>✓</i> 专属顾问支持</span>
            </div>
          </div>
          <div class="hero-visual reveal delay-1" aria-hidden="true">
            <img :src="asset('hero-target.png')" alt="">
            <span class="orbit orbit-a" />
            <span class="orbit orbit-b" />
          </div>
        </div>
        <div class="metric-grid reveal delay-2">
          <article class="metric-card violet">
            <div class="metric-head"><span class="metric-icon">◎</span>线索转化率提升</div>
            <strong>↑68%</strong><small>持续增长</small>
            <svg viewBox="0 0 260 66" aria-hidden="true"><polyline points="4,56 46,51 90,31 127,43 173,10 205,28 254,2" /></svg>
          </article>
          <article class="metric-card blue">
            <div class="metric-head"><span class="metric-icon">▣</span>获客成本降低</div>
            <strong>↓42%</strong><small>持续优化</small>
            <svg viewBox="0 0 260 66" aria-hidden="true"><polyline points="4,6 50,15 94,30 133,52 166,40 204,62 254,65" /></svg>
          </article>
          <article class="metric-card green">
            <div class="metric-head"><span class="metric-icon">◇</span>客户留存率增长</div>
            <strong>↑55%</strong><small>持续提升</small>
            <svg viewBox="0 0 260 66" aria-hidden="true"><polyline points="4,60 50,43 88,54 130,24 168,40 213,10 254,22" /></svg>
          </article>
          <article class="metric-card orange">
            <div class="metric-head"><span class="metric-icon">ϟ</span>团队效率提升</div>
            <strong>↑72%</strong><small>持续突破</small>
            <svg viewBox="0 0 260 66" aria-hidden="true"><polyline points="4,60 48,42 90,25 126,44 170,12 208,33 254,4" /></svg>
          </article>
        </div>
      </section>
        </div>
        <button class="intro-arrow prev" type="button" aria-label="上一屏" @click="setIntroSlide(introSlide - 1)">‹</button>
        <button class="intro-arrow next" type="button" aria-label="下一屏" @click="setIntroSlide(introSlide + 1)">›</button>
        <div class="intro-pagination" role="tablist" aria-label="选择首屏内容">
          <button
            v-for="index in 2"
            :key="index"
            type="button"
            role="tab"
            :class="{ active: introSlide === index - 1 }"
            :aria-selected="introSlide === index - 1"
            :aria-label="`第 ${index} 屏`"
            @click="setIntroSlide(index - 1)"
          />
        </div>
      </section>

      <section id="features" class="pain gs-section">
        <div class="section-heading">
          <h2>获客难，难在三个跟不上</h2>
          <p>三大核心短板，正在拖垮你的获客效率</p>
        </div>
        <div class="pain-grid">
          <article v-for="item in painPoints" :key="item.key" class="glass-card pain-card">
            <div class="warning">
              <span>!</span>
              <img class="warning-logo" :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true">
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.text }}</p>
          </article>
        </div>
        <div class="laser-divider">
          <span class="mini-target"><img :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true"></span>
        </div>
        <div class="section-heading compact">
          <h2>一套系统，打通三条获客通路</h2>
          <p>全域获客闭环，让精准线索持续增长</p>
        </div>
        <div class="channel-grid">
          <article v-for="item in channels" :key="item.key" class="glass-card channel-card">
            <div class="channel-preview">
              <img :src="item.image" :alt="`${item.title}产品界面`">
            </div>
            <div class="channel-copy">
              <div><h3>{{ item.title }}</h3><p>{{ item.text }}</p></div>
            </div>
          </article>
        </div>
      </section>

      <section id="process" class="process gs-section">
        <div class="section-heading">
          <span class="target-logo"><img :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true"></span>
          <h2>全流程自动化获客，精准高效</h2>
          <p>从渠道接入到转化复盘，每一步都由数据驱动</p>
        </div>
        <div class="process-grid">
          <article v-for="(item, index) in process" :key="item.title" class="process-step">
            <div class="step-icon">{{ item.icon }}</div>
            <span v-if="index < process.length - 1" class="step-line"><i /></span>
            <h3>{{ item.title }}</h3>
            <p>{{ item.text }}</p>
          </article>
        </div>
        <div id="resources" class="client-proof">
          <div class="section-heading compact">
            <span class="kicker">客户见证</span>
            <h2>标杆客户信赖，实力见证</h2>
          </div>
          <div class="logo-marquee" role="region" aria-label="标杆客户">
            <div class="logo-track">
              <div class="logo-group">
                <span v-for="logo in clientLogos" :key="logo.name" :class="logo.className" :aria-label="logo.name">
                  {{ logo.line1 }}<b v-if="logo.line2">{{ logo.line2 }}</b>
                </span>
              </div>
              <div class="logo-group" aria-hidden="true">
                <span v-for="logo in clientLogos" :key="`repeat-${logo.name}`" :class="logo.className">
                  {{ logo.line1 }}<b v-if="logo.line2">{{ logo.line2 }}</b>
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="pricing" class="pricing gs-section">
        <div class="section-heading">
          <span class="kicker">灵活定价</span>
          <h2>选择适合您的获客方案</h2>
          <p>匹配不同规模企业的获客需求，助力高效增长</p>
        </div>
        <div class="price-grid">
          <article v-for="plan in prices" :key="plan.name" class="glass-card price-card" :class="{ featured: plan.featured }">
            <span v-if="plan.featured" class="popular">最受欢迎</span>
            <div class="price-icon">{{ plan.icon }}</div>
            <h3>{{ plan.name }}</h3>
            <div class="price"><strong>{{ plan.price }}</strong><span>{{ plan.suffix }}</span></div>
            <p>{{ plan.note }}</p>
            <ul><li v-for="item in plan.items" :key="item"><i>✓</i>{{ item }}</li></ul>
            <button type="button" @click="scrollTo('contact')">{{ plan.featured ? '立即开始' : '了解详情' }}</button>
          </article>
        </div>
      </section>

      <section id="contact" class="final-cta gs-section">
        <span class="target-logo large"><img :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true"></span>
        <small>让每一条线索，都成为增长的动力</small>
        <h2>精准获客，从这一次点击开始</h2>
        <div class="hero-actions">
          <button class="button primary" type="button" @click="goDiagnosis">开始免费诊断</button>
          <button class="button ghost" type="button" @click="openTrialForm">预约演示 <span>↗</span></button>
        </div>
      </section>
    </main>

    <footer>
      <div class="footer-brand">
        <span class="brand-mark small"><img :src="asset('g-snipers-mark.png')" alt="" aria-hidden="true"></span>
        <strong>G-Snipers</strong><span>获客狙击手 · 全域智能获客解决方案</span>
      </div>
      <div class="footer-links">
        <a href="#features" @click.prevent="scrollTo('features')">产品功能</a>
        <a href="#process" @click.prevent="scrollTo('process')">行业方案</a>
        <a href="#resources" @click.prevent="scrollTo('resources')">客户案例</a>
        <a href="#resources" @click.prevent="scrollTo('resources')">资源中心</a>
        <a href="#contact" @click.prevent="scrollTo('contact')">关于我们</a>
      </div>
      <div class="footer-meta">隐私政策 · 服务条款 · 联系我们</div>
    </footer>

    <div
      v-if="trialModalOpen"
      class="trial-backdrop"
      role="presentation"
      @click.self="closeTrialForm"
      @keydown.esc="closeTrialForm"
    >
      <section class="trial-modal" role="dialog" aria-modal="true" aria-labelledby="trial-title">
        <button class="trial-close" type="button" aria-label="关闭表单" @click="closeTrialForm">×</button>
        <span class="trial-kicker">FINAL STEP</span>
        <h2 id="trial-title">还差一步，马上进入你的诊断工作台</h2>
        <p>留下联系方式，我们将为你开通免费诊断。</p>
        <form @submit.prevent="submitTrialForm">
          <label>
            <span>怎么称呼您</span>
            <input v-model="trialForm.name" autocomplete="name" placeholder="请输入姓名">
          </label>
          <label>
            <span>邮箱</span>
            <input v-model="trialForm.email" type="email" autocomplete="email" placeholder="用于接收诊断报告">
          </label>
          <label>
            <span>电话</span>
            <input v-model="trialForm.phone" inputmode="tel" autocomplete="tel" placeholder="请输入手机号" maxlength="11">
          </label>
          <label>
            <span>验证码</span>
            <span class="trial-code-row">
              <input v-model="trialForm.code" inputmode="numeric" placeholder="请输入验证码" maxlength="6">
              <button type="button" :disabled="trialCountdown > 0" @click="sendTrialCode">
                {{ trialCountdown ? `${trialCountdown}s 后重试` : '获取验证码' }}
              </button>
            </span>
          </label>
          <div class="trial-error" aria-live="polite">{{ trialError }}</div>
          <button class="trial-submit" type="submit" :disabled="trialSubmitting">
            {{ trialSubmitting ? '正在进入…' : '立即进入诊断中心' }}
          </button>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
:global(html) { scroll-behavior: smooth; }
:global(body) { background: #061018; }

.gs-site {
  --brand-mark-size: 84px;
  --purple: #a84eff;
  --purple-hot: #d970ff;
  --blue: #2da1ff;
  --ink: #061018;
  --muted: #a9b2bd;
  min-height: 100vh;
  overflow-x: clip;
  overflow-y: visible;
  position: relative;
  isolation: isolate;
  color: #f7f7f5;
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  background: #050d14;
}
.gs-site:before {
  content: "";
  position: fixed;
  z-index: -2;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(2, 9, 15, .48), rgba(5, 12, 20, .18) 52%, rgba(5, 9, 18, .28)),
    var(--gs-stone) center / cover no-repeat;
  transform: translateZ(0);
}
.gs-site:after {
  content: "";
  position: fixed;
  z-index: -1;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(ellipse at center, transparent 38%, rgba(1, 6, 10, .38) 100%);
}

.site-header {
  position: fixed; z-index: 50; inset: 0 0 auto; height: 104px;
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center;
  padding: 0 clamp(48px, 7vw, 140px);
  border-bottom: 1px solid rgba(205, 220, 230, .10);
  background: rgba(5, 15, 23, .8);
  backdrop-filter: blur(20px) saturate(130%);
}
.brand { display: flex; align-items: center; gap: 12px; color: white; text-decoration: none; }
.brand-mark { width: var(--brand-mark-size); height: var(--brand-mark-size); flex: none; }
.brand-mark img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 0 8px rgba(183,68,255,.55)); }
.brand-copy { display: flex; flex-direction: column; align-items: flex-start; gap: 0; white-space: nowrap; line-height: 1.05; }
.brand-copy strong { order: 2; font-size: 20px; letter-spacing: -.3px; background: linear-gradient(90deg, #a84eff, #df71ff); background-clip: text; color: transparent; }
.brand-copy em { order: 1; font-style: normal; font-weight: 700; font-size: 24px; text-shadow: 0 2px 12px #000; }

nav { display: flex; gap: clamp(30px, 4vw, 72px); }
nav a { color: #b9c0c8; font-size: 15px; text-decoration: none; transition: .25s; position: relative; }
nav a:hover, nav a.active { color: #fff; }
nav a:after { display: none; }
.header-cta { justify-self: end; border: 1px solid rgba(255,255,255,.72); border-radius: 999px; padding: 13px 28px; color: #fff; font-size: 15px; cursor: pointer; background: linear-gradient(105deg, #209eff, #7038f4 60%, #dc66eb); box-shadow: 0 0 24px rgba(111, 78, 255, .32), inset 0 1px rgba(255,255,255,.3); transition: .25s; }
.header-cta:hover { transform: translateY(-2px); box-shadow: 0 0 30px rgba(191, 91, 255, .48); }
.menu-button { display: none; }

.intro-carousel {
  position: relative;
  min-height: 100svh;
  padding: 0 !important;
  overflow: hidden;
  touch-action: pan-y;
}
.intro-stage {
  display: flex;
  width: 100%;
  min-height: 100svh;
  transform: translate3d(0, 0, 0);
}
.intro-stage.moving {
  transform: translate3d(-100%, 0, 0);
  transition: transform .72s cubic-bezier(.22, .72, .22, 1);
  will-change: transform;
}
.intro-slide {
  flex: 0 0 100%;
  width: 100%;
}
.intro-arrow {
  position: absolute;
  z-index: 12;
  top: 50%;
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(223, 185, 255, .36);
  border-radius: 50%;
  color: #f5eaff;
  font-size: 34px;
  line-height: 1;
  cursor: pointer;
  background: rgba(7, 16, 25, .66);
  box-shadow: 0 0 22px rgba(171, 67, 241, .22), inset 0 1px rgba(255,255,255,.08);
  backdrop-filter: blur(14px);
  transform: translateY(-50%);
  transition: border-color .25s, background .25s, box-shadow .25s;
}
.intro-arrow:hover {
  border-color: rgba(224, 149, 255, .8);
  background: rgba(120, 39, 184, .42);
  box-shadow: 0 0 28px rgba(189, 76, 255, .42);
}
.intro-arrow.prev { left: 24px; }
.intro-arrow.next { right: 24px; }
.intro-pagination {
  position: absolute;
  z-index: 12;
  left: 50%;
  bottom: 24px;
  display: flex;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 999px;
  background: rgba(4, 12, 19, .64);
  backdrop-filter: blur(12px);
  transform: translateX(-50%);
}
.intro-pagination button {
  width: 8px;
  height: 8px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  cursor: pointer;
  background: #77818b;
  transition: width .3s, background .3s, box-shadow .3s;
}
.intro-pagination button.active {
  width: 28px;
  background: #c15cff;
  box-shadow: 0 0 12px #b84eff;
}

.hero {
  min-height: 100svh;
  margin: 0;
  padding: 104px clamp(48px, 7vw, 140px) 22px;
  position: relative;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: linear-gradient(90deg, rgba(2,10,16,.75), rgba(4,13,21,.10) 58%, rgba(3,10,16,.28));
  box-shadow: none;
}
.hero:before { content: ""; position: absolute; inset: 0; opacity: .33; background-image: linear-gradient(115deg, transparent 0 48%, rgba(117, 177, 216, .07) 48.2%, transparent 48.5%); pointer-events: none; }
.hero-glow { position: absolute; width: 44vw; height: 44vw; border-radius: 50%; right: 2vw; top: 8vh; background: rgba(70, 97, 202, .12); filter: blur(80px); }
.hero-inner { min-height: 690px; max-width: none; margin: auto; display: grid; grid-template-columns: 1fr 1fr; align-items: center; position: relative; z-index: 1; }
.hero-copy { padding-top: 40px; z-index: 2; }
.eyebrow, .kicker { display: inline-flex; align-items: center; gap: 8px; color: #cfa4e8; text-transform: uppercase; letter-spacing: 2.5px; font-size: 12px; font-weight: 600; }
.eyebrow span { width: 26px; height: 1px; background: #bd5aff; box-shadow: 0 0 8px #bd5aff; }
.hero h1 { margin: 20px 0 24px; font-size: clamp(54px, 4vw, 76px); line-height: 1.08; letter-spacing: -.04em; font-weight: 700; white-space: nowrap; }
.hero h1 span { color: #f8f7f5; text-shadow: 0 6px 26px rgba(0, 0, 0, .45); }
.title-main { margin-right: .22em; }
.title-break { display: none; }
.hero-copy > p { margin: 0; font-size: clamp(16px, 1.15vw, 20px); color: #aeb8c1; line-height: 1.75; font-weight: 300; }
.mobile-break { display: none; }
.hero-actions { display: flex; gap: 22px; align-items: center; margin-top: 42px; }
.button { min-width: 174px; height: 52px; padding: 0 25px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; gap: 10px; font-size: 15px; color: #fff; cursor: pointer; text-decoration: none; transition: .3s; }
.button.primary { border: 1px solid rgba(255,255,255,.65); background: linear-gradient(105deg, #1b9fff, #8829ff 65%, #ef76e7); box-shadow: 0 10px 32px rgba(146, 44, 255, .38), inset 0 1px rgba(255,255,255,.34); }
.button.primary b { font-weight: 400; opacity: .85; }
.button.ghost { border: 1px solid rgba(223, 230, 236, .5); background: rgba(6, 15, 23, .35); backdrop-filter: blur(10px); }
.button:hover { transform: translateY(-3px); filter: brightness(1.12); }
.trust-row { display: flex; gap: 22px; margin-top: 28px; color: #788591; font-size: 12px; }
.trust-row i { color: #a557e7; font-style: normal; }
.hero-visual { position: absolute; z-index: 0; right: 9vw; top: 20%; width: min(45vw, 900px); transform: translateY(-45%); }
.hero-visual img { display: block; width: 100%; height: auto; filter: saturate(1.06) contrast(1.05); mask-image: radial-gradient(ellipse 58% 65% at 66% 58%, #000 0 42%, rgba(0,0,0,.9) 50%, transparent 70%); }
.orbit { position: absolute; border: 1px solid rgba(104, 102, 255, .18); border-radius: 50%; pointer-events: none; animation: orbit 14s linear infinite; }
.orbit-a { width: 55%; aspect-ratio: 1; right: 6%; top: 12%; }
.orbit-b { width: 64%; aspect-ratio: 1; right: 1%; top: 6%; animation-direction: reverse; animation-duration: 20s; }
.orbit:after { content: ""; position: absolute; width: 5px; height: 5px; border-radius: 50%; background: #cc65ff; top: 13%; left: 12%; box-shadow: 0 0 12px 4px #a74bff; }
@keyframes orbit { to { transform: rotate(360deg); } }

.metric-grid { position: relative; z-index: 3; max-width: 1600px; margin: -82px auto 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; }
.metric-card, .glass-card { background: linear-gradient(145deg, rgba(27, 45, 58, .62), rgba(7, 17, 25, .7)); border: 1px solid rgba(175, 196, 210, .24); box-shadow: inset 0 1px rgba(255,255,255,.05), 0 18px 42px rgba(0,0,0,.22); backdrop-filter: blur(16px); }
.metric-card { height: 230px; padding: 22px 24px; border-radius: 18px; overflow: hidden; position: relative; }
.metric-head { display: flex; align-items: center; gap: 9px; color: #d9dddf; font-size: 15px; font-weight: 500; }
.metric-icon { width: 30px; height: 30px; display: grid; place-items: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 22%, transparent); border-radius: 50%; }
.metric-card strong { display: block; margin-top: 15px; color: var(--accent); font-size: 48px; line-height: 1; font-weight: 650; }
.metric-card small { display: inline-block; margin-top: 13px; padding: 4px 10px; border-radius: 6px; color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent); font-size: 11px; }
.metric-card svg { position: absolute; left: 24px; right: 24px; bottom: 18px; width: calc(100% - 48px); overflow: visible; }
.metric-card polyline, .channel-preview polyline { fill: none; stroke: var(--accent); stroke-width: 2.2; filter: drop-shadow(0 0 5px var(--accent)); }
.metric-card:after { content: ""; position: absolute; inset: auto 0 0; height: 90px; opacity: .12; background: linear-gradient(transparent, var(--accent)); clip-path: polygon(0 80%, 16% 72%, 34% 45%, 51% 61%, 70% 16%, 83% 35%, 100% 0, 100% 100%, 0 100%); }
.violet { --accent: #bd59ff; }.blue { --accent: #349bff; }.green { --accent: #64e99c; }.orange { --accent: #ff9a46; }
.gs-section:not(.hero) { position: relative; padding: 115px clamp(24px, 7.5vw, 150px); }
.pain { background: rgba(3,10,16,.28); overflow: hidden; }
.section-heading { text-align: center; position: relative; z-index: 1; }
.section-heading h2 { margin: 15px 0 12px; font-size: clamp(38px, 4.2vw, 70px); line-height: 1.13; letter-spacing: -.045em; text-shadow: 0 4px 15px #000; }
.section-heading p { margin: 0; color: #aeb5bc; font-size: 18px; font-weight: 300; }
.section-heading.compact h2 { font-size: clamp(32px, 3.3vw, 56px); }
.pain-grid, .channel-grid, .price-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 40px; max-width: 1500px; margin: 65px auto 0; }
.pain-card { min-width: 0; min-height: 230px; display: flex; flex-direction: column; align-items: center; justify-content: center; border-radius: 14px; border-color: rgba(222, 147, 255, .7); background: linear-gradient(135deg,rgba(47,60,70,.68),rgba(14,24,32,.82) 56%,rgba(10,18,25,.9)); box-shadow: 0 22px 30px rgba(0,0,0,.48), 0 0 20px rgba(183,73,255,.16), inset 0 1px rgba(255,255,255,.18); }
.warning { position: relative; width: 64px; height: 56px; display: grid; place-items: center; color: white; font-size: 28px; font-weight: 800; filter: drop-shadow(0 0 12px #c05aff); }
.warning:before { content: ""; position: absolute; inset: 2px; clip-path: polygon(50% 0, 100% 100%, 0 100%); background: linear-gradient(#efb0ff, #9a34df); }
.warning:after { content: ""; position: absolute; inset: 7px; clip-path: polygon(50% 0, 100% 100%, 0 100%); background: #18222b; }
.warning span { z-index: 1; }
.warning-logo { position: absolute; z-index: 2; width: 31px; height: 31px; right: -13px; top: -9px; object-fit: contain; filter: drop-shadow(0 0 8px rgba(190, 74, 255, .86)); }
.pain-card h3 { font-size: 31px; margin: 22px 0 8px; color:#f1efeb; text-shadow:0 2px 1px rgba(0,0,0,.85),0 0 14px rgba(255,255,255,.08); }
.pain-card p { margin: 0 24px; color: #b8bec5; text-align: center; font-size: 15px; line-height: 1.8; }
.laser-divider { max-width: 1160px; height: 1px; margin: 82px auto 72px; background: linear-gradient(90deg, transparent, #9852ca 40%, #ecb1ff 50%, #9852ca 60%, transparent); box-shadow: 0 0 10px #b656ff; position: relative; }
.mini-target { position: absolute; width: var(--brand-mark-size); height: var(--brand-mark-size); left: 50%; top: 50%; transform: translate(-50%,-50%); }
.mini-target img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 0 12px rgba(183,68,255,.72)); }
.channel-card { min-width: 0; overflow: hidden; border-radius: 14px; border-color: rgba(219,125,255,.62); background: linear-gradient(180deg,rgba(21,34,44,.72),rgba(8,17,25,.88)); box-shadow: 0 20px 38px rgba(0,0,0,.4), 0 0 18px rgba(183,73,255,.16), inset 0 1px rgba(255,255,255,.1); }
.channel-preview { height: 210px; display: grid; place-items: center; padding: 18px 24px 6px; background: radial-gradient(ellipse at 50% 65%,rgba(108,54,163,.18),transparent 64%); }
.channel-preview img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 12px 18px rgba(0,0,0,.48)); }
.channel-copy { min-height: 108px; display: grid; place-items: start center; padding: 10px 22px 24px; text-align: center; }
.channel-copy h3 { margin: 0 0 8px; font-size: 25px; }.channel-copy p { margin: 0; color: #b6bdc3; font-size: 14px; line-height: 1.6; }

.diagnostic-teaser {
  display: grid;
  grid-template-columns: minmax(430px, .82fr) minmax(620px, 1.18fr);
  align-items: center;
  gap: clamp(42px, 6vw, 110px);
  background: rgba(3,10,16,.28);
}
.diagnosis-copy { position: relative; z-index: 2; }
.diagnosis-copy h2 { margin: 15px 0 20px; font-size: clamp(42px, 4.1vw, 68px); line-height: 1.16; letter-spacing: -.05em; }
.diagnosis-copy > p { max-width: 720px; color: #b5bdc5; font-size: 18px; line-height: 1.8; }
.capability-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 20px; margin: 27px 0; }
.capability-list span { display: flex; align-items: center; gap: 9px; color: #d9dde0; font-size: 14px; }
.capability-list i { width: 29px; height: 29px; display: grid; place-items: center; border-radius: 50%; color: #d98aff; font-style: normal; background: rgba(171,64,235,.18); box-shadow: inset 0 0 10px rgba(201,99,255,.22); }
.diagnosis-form { display: grid; grid-template-columns: 1fr auto; max-width: 720px; min-height: 63px; padding: 5px; border: 1px solid rgba(215,119,255,.75); border-radius: 999px; background: rgba(10,22,31,.74); box-shadow: 0 0 25px rgba(177,70,236,.15); backdrop-filter: blur(12px); }
.diagnosis-form input { min-width: 0; border: 0; outline: 0; padding: 0 23px; color: #f0f2f3; font-size: 16px; background: transparent; }
.diagnosis-form input::placeholder { color: #707c86; }
.diagnosis-form button { min-width: 190px; border: 0; border-radius: 999px; color: #fff; font-size: 16px; cursor: pointer; background: linear-gradient(100deg,#7126e8,#c342fb 68%,#f09eea); box-shadow: 0 0 22px rgba(190,72,255,.48); }
.diagnosis-copy > small { display: block; margin: 11px 0 0 20px; color: #76818b; }
.dashboard-shell { position: relative; overflow: hidden; padding: 18px; border: 1px solid rgba(181,197,208,.38); border-radius: 27px; background: linear-gradient(145deg,rgba(14,29,40,.92),rgba(5,13,20,.94)); box-shadow: 0 28px 80px rgba(0,0,0,.52),0 0 45px rgba(126,51,222,.2); transform: perspective(1300px) rotateY(-3deg); }
.dashboard-top { height: 54px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 17px; border-bottom: 1px solid rgba(255,255,255,.07); color: #87929c; font-size: 12px; }
.dash-brand { color: #fff; font-weight: 700; font-size: 16px; }.dash-dot { display: inline-block; width: 11px; height: 11px; margin-right: 8px; border: 2px solid #c25cff; border-radius: 50%; box-shadow: 0 0 8px #b551ff; }
.dashboard-body { padding: 17px; }
.dash-stats { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }
.dash-stats > div { min-height: 95px; display: flex; flex-direction: column; padding: 14px; border: 1px solid rgba(167,188,203,.15); border-radius: 11px; background: rgba(31,47,59,.56); }
.dash-stats small { color: #aeb7bd; }.dash-stats strong { margin: 7px 0 3px; font-size: 25px; }.dash-stats em { color: #cc7280; font-size: 10px; font-style: normal; }.dash-stats em.good { color: #46d08e; }
.dash-panels { display: grid; grid-template-columns: 1.35fr .85fr; gap: 12px; margin-top: 12px; }
.dash-panels > div { min-height: 210px; padding: 16px; border: 1px solid rgba(167,188,203,.15); border-radius: 11px; background: rgba(20,35,45,.68); }
.dash-panels h3 { margin: 0; color: #dfe3e5; font-size: 14px; }.trend-panel svg { width: 100%; margin-top: 13px; }
.score-gauge { width: 170px; height: 90px; overflow: hidden; margin: 35px auto 0; position: relative; }
.score-gauge:before { content:""; position:absolute; inset:0; border:16px solid #253947; border-bottom:0; border-radius:100px 100px 0 0; box-shadow: inset 30px 5px 0 -13px #319bff; }
.score-gauge span { position:absolute; inset:auto 0 0; text-align:center; font-size:30px; font-weight:700; }.score-gauge small { display:block; color:#8c99a3; font-size:10px; font-weight:400; }
.channel-summary { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; margin-top: 12px; }
.channel-summary span { display: grid; grid-template-columns: 1fr auto; gap: 3px; padding: 12px 15px; border: 1px solid rgba(167,188,203,.13); border-radius: 9px; background: rgba(18,33,44,.62); }
.channel-summary b { color: #b76aff; }.channel-summary strong { font-size: 18px; }.channel-summary small { grid-column: 1/-1; color:#75828c; }
.demo-badge { position:absolute; right:23px; bottom:20px; padding:5px 10px; border-radius:999px; color:#a8b0b6; font-size:9px; background:rgba(3,10,16,.78); }

.process { background: rgba(3,10,16,.28); }
.target-logo { width: var(--brand-mark-size); height: var(--brand-mark-size); margin: 0 auto 24px; display: block; }
.target-logo img { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 0 12px rgba(183,68,255,.72)); }
.process-grid { max-width: 1500px; margin: 70px auto 90px; display: grid; grid-template-columns: repeat(4, 1fr); }
.process-step { position: relative; text-align: center; padding: 0 28px; }
.step-icon { width: 75px; height: 75px; margin: auto; display: grid; place-items: center; font-size: 36px; color: #e9e7e8; text-shadow: 0 3px 5px #000; }
.process-step h3 { font-size: 20px; margin: 22px 0 9px; }.process-step p { color: #919ba4; font-size: 14px; margin: 0; }
.step-line { position: absolute; left: calc(50% + 62px); right: calc(-50% + 62px); top: 37px; height: 1px; background: linear-gradient(90deg, rgba(185, 80, 255, .15), rgba(185, 80, 255, .8), rgba(185, 80, 255, .15)); }
.step-line i { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: #c562ff; top: -3px; left: 50%; box-shadow: 0 0 9px #c562ff; }
.client-proof { border-top: 1px solid rgba(186, 82, 255, .22); padding-top: 70px; }
.logo-marquee {
  --logo-gap: 20px;
  position: relative;
  margin-top: 45px;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%);
  mask-image: linear-gradient(90deg, transparent 0, #000 5%, #000 95%, transparent 100%);
}
.logo-track {
  width: max-content;
  display: flex;
  gap: var(--logo-gap);
  animation: logo-marquee 28s linear infinite;
  will-change: transform;
}
.logo-marquee:hover .logo-track { animation-play-state: paused; }
.logo-group { display: flex; gap: var(--logo-gap); }
.logo-group span {
  width: clamp(230px, 17vw, 310px);
  min-height: 120px;
  border: 1px solid rgba(172,190,203,.22);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #e2e2e0;
  font-size: 33px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
  background: linear-gradient(145deg, rgba(38,52,63,.72), rgba(15,24,31,.72));
  box-shadow: inset 0 1px rgba(255,255,255,.04);
  filter: grayscale(1);
  transition: border-color .25s, background .25s, transform .25s;
}
.logo-group span:hover {
  border-color: rgba(207,118,255,.5);
  background: linear-gradient(145deg, rgba(49,59,73,.82), rgba(19,25,36,.84));
  transform: translateY(-3px);
}
.logo-group span b { margin-top: 12px; font-size: 24px; }
.logo-group .logo-3m { font-size: 54px; }
@keyframes logo-marquee {
  to { transform: translateX(calc(-50% - var(--logo-gap) / 2)); }
}

.pricing { background: rgba(3,10,16,.28); }
.price-grid { max-width: 1260px; align-items: stretch; gap: 40px; }
.price-card { border-radius: 17px; padding: 38px 42px 34px; min-height: 510px; position: relative; text-align: center; transition: .3s; }
.price-card:hover { transform: translateY(-7px); }
.price-card.featured { border-color: #ca67ff; box-shadow: 0 0 26px rgba(183, 74, 255, .32), inset 0 1px rgba(255,255,255,.1); transform: scale(1.035); }
.price-card.featured:hover { transform: scale(1.035) translateY(-7px); }
.popular { position: absolute; top: -15px; left: 50%; transform: translateX(-50%); padding: 6px 18px; border-radius: 999px; background: linear-gradient(90deg,#8428f6,#d466ff); font-size: 12px; white-space: nowrap; box-shadow: 0 0 16px #a23fff; }
.price-icon { font-size: 45px; color: #d274ff; filter: drop-shadow(0 0 10px #b14eff); }
.price-card h3 { font-size: 28px; margin: 15px 0 18px; }
.price { border-top: 1px solid rgba(255,255,255,.1); padding-top: 18px; }.price strong { font-size: 40px; }.price span { color: #aeb7bf; }
.price-card > p { color: #b8c0c7; min-height: 24px; margin: 8px 0 25px; }
.price-card ul { list-style: none; padding: 20px 0 12px; border-top: 1px solid rgba(255,255,255,.1); text-align: left; }
.price-card li { margin: 14px 0; color: #d0d5d9; }.price-card li i { color: #62dcb4; font-style: normal; margin-right: 12px; }
.price-card button { width: 100%; height: 48px; border-radius: 999px; border: 1px solid rgba(228,235,240,.5); color: #fff; background: rgba(255,255,255,.04); cursor: pointer; transition: .25s; }
.price-card.featured button, .price-card button:hover { border-color: transparent; background: linear-gradient(90deg,#6b2fe9,#d04ffc); box-shadow: 0 0 18px rgba(188,73,255,.45); }

.final-cta { padding-top: 90px !important; padding-bottom: 110px !important; text-align: center; background: rgba(3,10,16,.28); }
.target-logo.large { width: var(--brand-mark-size); height: var(--brand-mark-size); }.final-cta small { display: block; color: #858f98; font-size: 14px; letter-spacing: 2px; }
.final-cta h2 { font-size: clamp(34px, 3.6vw, 58px); margin: 10px 0 0; }.final-cta .hero-actions { justify-content: center; margin-top: 32px; }
footer { min-height: 92px; display: grid; grid-template-columns: 1.4fr 1.2fr 1fr; align-items: center; gap: 30px; padding: 20px clamp(24px, 6vw, 118px); border-top: 1px solid rgba(184,199,210,.13); background: rgba(5,13,19,.86); color: #7d8790; font-size: 12px; }
.footer-brand { display: flex; align-items: center; gap: 9px; }.footer-brand strong { color: white; font-size: 15px; }.brand-mark.small { width: var(--brand-mark-size); height: var(--brand-mark-size); margin-right: 1px; }
.footer-links { display: flex; justify-content: center; gap: 25px; }.footer-links a { color: #818b95; text-decoration: none; }.footer-links a:hover { color: #d7a2f3; }.footer-meta { text-align: right; }

.trial-backdrop {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 22px;
  background: rgba(1, 7, 12, .76);
  backdrop-filter: blur(15px);
}
.trial-modal {
  position: relative;
  width: min(660px, 100%);
  max-height: calc(100svh - 44px);
  overflow-y: auto;
  padding: 42px 54px 48px;
  border: 1px solid rgba(196, 211, 222, .48);
  border-radius: 24px;
  background:
    radial-gradient(circle at 85% 100%, rgba(138, 42, 236, .18), transparent 42%),
    linear-gradient(145deg, rgba(29, 44, 56, .98), rgba(8, 19, 28, .99));
  box-shadow: 0 38px 110px rgba(0,0,0,.72), 0 0 40px rgba(185, 69, 255, .2);
}
.trial-close {
  position: absolute;
  top: 12px;
  right: 16px;
  width: 36px;
  height: 36px;
  border: 0;
  color: #aeb6bd;
  font-size: 29px;
  line-height: 1;
  cursor: pointer;
  background: transparent;
}
.trial-kicker { color: #ce79fa; font-size: 11px; letter-spacing: 2.5px; }
.trial-modal h2 { margin: 8px 0 7px; font-size: 28px; letter-spacing: -.03em; }
.trial-modal > p { margin: 0 0 23px; color: #85919a; font-size: 13px; }
.trial-modal form { display: grid; gap: 14px; }
.trial-modal label { display: grid; gap: 7px; color: #dce0e2; font-size: 13px; }
.trial-modal label > input,
.trial-code-row input {
  min-width: 0;
  height: 48px;
  padding: 0 15px;
  border: 1px solid #65727c;
  border-radius: 10px;
  outline: 0;
  color: #fff;
  background: rgba(12, 26, 36, .72);
}
.trial-modal input:focus { border-color: #ca62ff; box-shadow: 0 0 0 3px rgba(189, 76, 255, .1); }
.trial-code-row { display: grid; grid-template-columns: 1fr 145px; gap: 11px; }
.trial-code-row button {
  border: 0;
  border-radius: 10px;
  color: #fff;
  cursor: pointer;
  background: linear-gradient(90deg, #7026dc, #b83eef);
  box-shadow: 0 0 18px rgba(183, 65, 241, .24);
}
.trial-code-row button:disabled { cursor: default; opacity: .55; }
.trial-error { min-height: 18px; margin-top: -3px; color: #ff9fa8; font-size: 12px; }
.trial-submit {
  height: 54px;
  border: 1px solid rgba(255,255,255,.55);
  border-radius: 999px;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  background: linear-gradient(92deg, #ff9a42, #c344eb 55%, #8b24fa);
  box-shadow: 0 0 26px rgba(188, 65, 245, .42);
}
.trial-submit:disabled { cursor: wait; opacity: .65; }

.reveal { animation: reveal .8s cubic-bezier(.2,.7,.2,1) both; }.delay-1 { animation-delay: .12s }.delay-2 { animation-delay: .25s }
@keyframes reveal { from { opacity:0; transform:translateY(22px) } to { opacity:1; transform:translateY(0) } }

/* 宽屏官网按“一个参考画面一个视口”控制信息密度。 */
@media (min-width: 1181px) {
  .gs-section { scroll-margin-top: 104px; }

  .hero {
    min-height: 100svh;
    padding-top: 104px;
    padding-bottom: 18px;
  }
  .hero-inner {
    height: clamp(430px, calc(100svh - 390px), 650px);
    min-height: 0;
  }
  .hero-copy { padding-top: 0; transform: translateY(-44px); }
  .hero-copy .eyebrow { display: none; }
  .hero h1 {
    margin: 0 0 22px;
    font-size: clamp(52px, 3.7vw, 72px);
  }
  .hero-copy > p { font-size: clamp(15px, 1.05vw, 19px); line-height: 1.7; }
  .hero-actions { margin-top: 34px; }
  .button { min-width: 174px; height: 52px; }
  .trust-row { display: none; }
  .hero-visual { width: min(45vw, 900px); transform: translateY(-45%); }

  .metric-grid { margin-top: -76px; gap: 28px; }
  .metric-card { height: clamp(205px, 21svh, 232px); padding: 21px 23px; border-radius: 17px; }
  .metric-head { font-size: 15px; }
  .metric-card strong { margin-top: 14px; font-size: 48px; }
  .metric-card small { margin-top: 11px; }
  .metric-card svg { bottom: 13px; }

  .gs-section:not(.hero) {
    min-height: 100svh;
    padding: 58px clamp(24px, 7.5vw, 150px) 48px;
  }
  .section-heading h2 { margin: 10px 0 8px; font-size: clamp(36px, 3vw, 52px); }
  .section-heading p { font-size: 15px; }
  .section-heading.compact h2 { font-size: clamp(31px, 2.6vw, 44px); }

  .pain {
    padding-top: 72px !important;
    padding-right: 0 !important;
    padding-bottom: 94px !important;
    padding-left: 0 !important;
  }
  .pain .section-heading h2 { margin: 0 0 11px; color:#eeeDEA; font-size: clamp(51px, 3.55vw, 76px); font-weight: 650; letter-spacing:0; text-shadow:0 2px 1px rgba(0,0,0,.9),0 5px 18px rgba(0,0,0,.7),0 1px rgba(255,255,255,.22); }
  .pain .section-heading p { font-size: 18px; }
  .pain .section-heading.compact h2 { font-size: clamp(45px, 3.1vw, 66px); }
  .pain .pain-grid,
  .pain .channel-grid {
    width: 75vw;
    max-width: 1920px;
    gap: clamp(42px, 4.1vw, 105px);
  }
  .pain .pain-grid { margin-top: 72px; }
  .pain-card {
    width: 100%;
    min-height: 230px;
    border-width: 1px;
    background:
      linear-gradient(135deg,rgba(72,82,91,.72),rgba(25,34,42,.82) 52%,rgba(12,20,27,.92)),
      radial-gradient(circle at 30% 12%,rgba(255,255,255,.12),transparent 38%);
    box-shadow:
      18px 24px 28px rgba(0,0,0,.52),
      0 0 16px rgba(190,74,255,.18),
      inset 0 1px rgba(255,255,255,.24),
      inset 0 -2px rgba(213,91,255,.36);
  }
  .warning { width: 64px; height: 56px; font-size: 28px; }
  .pain-card h3 { margin: 22px 0 8px; font-size: clamp(29px, 2vw, 43px); font-weight: 650; }
  .pain-card p { font-size: clamp(14px, 1.05vw, 23px); line-height: 1.8; white-space: normal; overflow-wrap: break-word; }
  .laser-divider { width: 75vw; max-width: 1920px; margin: 88px auto 72px; }
  .mini-target { width: var(--brand-mark-size); height: var(--brand-mark-size); }
  .channel-grid { margin-top: 58px; }
  .channel-card {
    aspect-ratio: 1.5 / 1;
    display: grid;
    grid-template-rows: 58% 42%;
    background:
      linear-gradient(135deg,rgba(48,59,68,.64),rgba(17,27,35,.86) 58%,rgba(10,18,25,.94)),
      radial-gradient(circle at 25% 8%,rgba(255,255,255,.09),transparent 42%);
    box-shadow:
      18px 24px 30px rgba(0,0,0,.5),
      0 0 16px rgba(190,74,255,.16),
      inset 0 1px rgba(255,255,255,.2),
      inset 0 -2px rgba(213,91,255,.34);
  }
  .channel-preview {
    height: auto;
    padding: 20px 28px 0;
    background: radial-gradient(ellipse at 50% 68%,rgba(108,54,163,.2),transparent 65%);
  }
  .channel-preview img { width: 92%; height: 94%; }
  .channel-copy { min-height: 0; place-items: center; padding: 8px 24px 24px; }
  .channel-copy h3 { margin-bottom: 10px; font-size: clamp(23px, 1.8vw, 36px); font-weight: 650; }
  .channel-copy p { font-size: clamp(13px, 1vw, 21px); line-height: 1.55; white-space: normal; overflow-wrap: break-word; }

  .diagnostic-first { padding-top: 138px !important; padding-bottom: 48px !important; }
  .diagnosis-copy h2 { margin: 11px 0 14px; font-size: clamp(38px,3.3vw,58px); }
  .diagnosis-copy > p { font-size: 15px; line-height: 1.65; }
  .capability-list { margin: 19px 0; }
  .diagnosis-form { min-height: 56px; }
  .dashboard-shell { max-height: calc(100svh - 145px); }
  .dash-panels > div { min-height: 172px; }
  .trend-panel svg { height: 125px; }

  .target-logo { width: var(--brand-mark-size); height: var(--brand-mark-size); margin-bottom: 13px; }
  .process-grid { margin: 35px auto 45px; }
  .step-icon { width: 58px; height: 58px; font-size: 29px; }
  .step-line { top: 29px; }
  .process-step h3 { margin: 13px 0 6px; font-size: 18px; }
  .process-step p { font-size: 12px; }
  .client-proof { padding-top: 36px; }
  .logo-marquee { margin-top: 27px; }
  .logo-group span { min-height: 86px; font-size: 27px; }
  .logo-group span b { margin-top: 9px; font-size: 19px; }
  .logo-group .logo-3m { font-size: 44px; }

  .price-grid { max-width: 1180px; margin-top: 34px; gap: 28px; }
  .price-card { min-height: 405px; padding: 25px 34px 25px; }
  .price-icon { font-size: 35px; }
  .price-card h3 { margin: 8px 0 12px; font-size: 24px; }
  .price { padding-top: 12px; }
  .price strong { font-size: 34px; }
  .price-card > p { margin: 5px 0 15px; }
  .price-card ul { padding: 11px 0 5px; }
  .price-card li { margin: 9px 0; font-size: 14px; }
  .price-card button { height: 42px; }

  .final-cta {
    min-height: auto !important;
    padding-top: 60px !important;
    padding-bottom: 65px !important;
  }
  .target-logo.large { width: var(--brand-mark-size); height: var(--brand-mark-size); }
}

@media (max-width: 1180px) {
  .site-header { position: fixed; inset: 0 0 auto; height: 72px; grid-template-columns: 1fr auto; padding: 0 clamp(24px, 6vw, 70px); }
  nav { position: fixed; left: 16px; right: 16px; top: 72px; padding: 22px; border: 1px solid rgba(255,255,255,.12); border-radius: 16px; background: rgba(5,14,21,.96); display: none; flex-direction: column; gap: 20px; box-shadow: 0 20px 50px #000; }
  nav.open { display: flex; }.header-cta { display: none; }
  .menu-button { justify-self: end; display: grid; gap: 5px; width: 40px; height: 40px; place-content: center; border: 1px solid rgba(255,255,255,.15); border-radius: 10px; background: transparent; }
  .menu-button span { width: 18px; height: 1px; background: #fff; }
  .hero { min-height: 100vh; margin: 0; padding-top: 72px; border: 0; border-radius: 0; }
  .title-break { display: block; }
  .hero h1 { white-space: normal; }
  .hero-inner { grid-template-columns: 1fr; min-height: 720px; }.hero-copy { padding-top: 0; }.hero-visual { right: -28vw; width: 100vw; opacity: .62; }
  .metric-grid { grid-template-columns: repeat(2, 1fr); margin-top: -30px; }.pain-grid, .channel-grid, .price-grid { gap: 22px; }
  .diagnostic-teaser { grid-template-columns: 1fr; }
  .dashboard-shell { transform: none; }
  .logo-group span { width: 240px; }
  footer { grid-template-columns: 1fr; text-align: center; }.footer-brand, .footer-links { justify-content: center; }.footer-meta { text-align: center; }
}

@media (max-width: 760px) {
  .gs-site { --brand-mark-size: 50px; }
  .site-header { height: 68px; padding: 0 18px; }.brand-copy strong { font-size: 16px; }.brand-copy em { font-size: 18px; }
  .intro-arrow { top: auto; bottom: 12px; width: 40px; height: 40px; font-size: 28px; transform: none; }
  .intro-arrow.prev { left: 14px; }.intro-arrow.next { right: 14px; }
  .intro-pagination { bottom: 16px; }
  .hero { padding: 68px 18px 55px; min-height: auto; }.hero-inner { min-width: 0; width: 100%; min-height: 650px; align-items: start; padding-top: 95px; }
  .hero-copy { min-width: 0; width: 100%; text-align: center; }.eyebrow { justify-content: center; }.hero h1 { width: 100%; font-size: clamp(51px, 15.5vw, 64px); margin-top: 16px; letter-spacing: -.075em; }
  .hero-copy > p { font-size: 16px; line-height: 1.7; }.mobile-break { display: block; }.hero-actions { justify-content: center; flex-direction: column; gap: 13px; margin-top: 30px; }.button { width: min(100%, 320px); height: 54px; }
  .trust-row { display: none; }.hero-visual { width: 720px; right: 50%; transform: translate(74%, -7%); top: 290px; opacity: .55; }.orbit { display: none; }
  .metric-grid { grid-template-columns: 1fr; gap: 14px; margin-top: 0; }.metric-card { height: 190px; padding: 22px; }.metric-card strong { font-size: 45px; }
  .metric-note { text-align: left; line-height: 1.6; }
  .gs-section:not(.hero) { padding: 78px 18px; }.section-heading h2 { font-size: 36px; }.section-heading p { font-size: 15px; line-height: 1.7; }
  .pain-grid, .channel-grid, .price-grid { grid-template-columns: 1fr; margin-top: 42px; }.pain-card { min-height: 210px; }.pain-card h3 { font-size: 27px; }
  .laser-divider { margin: 65px auto 58px; }.channel-preview { height: 160px; }.channel-copy h3 { font-size: 20px; }
  .diagnostic-first { padding-top: 110px !important; }.diagnosis-copy h2 { font-size: 37px; }.diagnosis-copy > p { font-size: 15px; }.capability-list { grid-template-columns: 1fr 1fr; }
  .diagnosis-form { grid-template-columns: 1fr; padding: 6px; border-radius: 18px; }.diagnosis-form input { min-height: 52px; }.diagnosis-form button { min-height: 48px; }
  .dashboard-shell { padding: 10px; border-radius: 18px; }.dashboard-top { display: none; }.dashboard-body { padding: 5px; }
  .dash-stats { grid-template-columns: repeat(2,1fr); }.dash-stats > div { min-height: 84px; }.dash-panels { grid-template-columns: 1fr; }
  .score-panel { display: none; }.channel-summary { grid-template-columns: 1fr; }
  .process-grid { grid-template-columns: 1fr; gap: 44px; margin: 48px auto 70px; }.process-step { padding: 0; }.step-line { width: 1px; height: 32px; top: auto; bottom: -38px; left: 50%; right: auto; }.step-line i { top: 50%; left: -3px; }
  .logo-marquee { margin-inline: -18px; }.price-card { min-height: 0; padding: 34px 28px; }.price-card.featured { transform: none; }.price-card.featured:hover { transform: translateY(-7px); }
  .final-cta { padding-inline: 18px !important; }.final-cta .hero-actions { flex-direction: column; }.footer-links { flex-wrap: wrap; gap: 14px 22px; }.footer-brand { flex-wrap: wrap; }
  .trial-backdrop { padding: 12px; }
  .trial-modal { padding: 36px 22px 28px; border-radius: 19px; }
  .trial-modal h2 { font-size: 23px; line-height: 1.35; }
  .trial-code-row { grid-template-columns: 1fr 118px; }
}

@media (prefers-reduced-motion: reduce) {
  *, *:before, *:after { animation-duration: .01ms !important; scroll-behavior: auto !important; }
  .intro-stage.moving { transition: none; }
  .logo-marquee { overflow-x: auto; -webkit-mask-image: none; mask-image: none; }
  .logo-track { animation: none !important; }
  .logo-group[aria-hidden="true"] { display: none; }
}
</style>
