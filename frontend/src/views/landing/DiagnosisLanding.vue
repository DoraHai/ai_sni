<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const website = ref(String(route.query.url || ''))
const websiteInput = ref(null)
const modalOpen = ref(false)
const submitting = ref(false)
const error = ref('')
const countdown = ref(0)
let countdownTimer
let focusTimer

const form = reactive({
  name: '',
  email: '',
  phone: '',
  code: '',
  agreed: false,
})

const diagnostics = [
  { icon: '◎', title: 'SEM 诊断', text: '投放成本精准管控，ROI 实时优化', detail: '预算效率 · 关键词质量 · 转化链路' },
  { icon: '↗', title: 'SEO 诊断', text: '排名波动实时预警，收录效率持续提升', detail: '自然排名 · 内容质量 · 站点健康度' },
  { icon: '●', title: 'GEO 诊断', text: 'AI 搜索可见度分析，品牌引用清晰可查', detail: '模型曝光 · 信源引用 · 品牌心智' },
]

function normalizeUrl(value) {
  const raw = value.trim()
  if (!raw) return ''
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`
}

function startDiagnosis() {
  error.value = ''
  const normalized = normalizeUrl(website.value)
  try {
    const parsed = new URL(normalized)
    if (!parsed.hostname.includes('.')) throw new Error()
    website.value = normalized
    modalOpen.value = true
  } catch {
    error.value = '请输入有效的官网地址，例如 https://example.com'
  }
}

function goToStart() {
  modalOpen.value = false
  error.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
  window.clearTimeout(focusTimer)
  focusTimer = window.setTimeout(() => websiteInput.value?.focus({ preventScroll: true }), 450)
}

function sendCode() {
  error.value = ''
  if (!/^1\d{10}$/.test(form.phone)) {
    error.value = '请先输入有效手机号'
    return
  }
  if (countdown.value) return
  countdown.value = 60
  countdownTimer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      window.clearInterval(countdownTimer)
      countdownTimer = undefined
    }
  }, 1000)
}

async function submitLead() {
  error.value = ''
  if (!form.name.trim()) return void (error.value = '请填写您的称呼')
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) return void (error.value = '请填写有效邮箱')
  if (!/^1\d{10}$/.test(form.phone)) return void (error.value = '请填写有效手机号')
  if (!/^\d{4,6}$/.test(form.code)) return void (error.value = '请填写验证码')
  if (!form.agreed) return void (error.value = '请先阅读并同意隐私政策和服务条款')
  submitting.value = true
  window.setTimeout(() => {
    submitting.value = false
    router.push({ path: '/login', query: { diagnosis: 'created', website: website.value } })
  }, 700)
}

onUnmounted(() => {
  if (countdownTimer) window.clearInterval(countdownTimer)
  if (focusTimer) window.clearTimeout(focusTimer)
})
</script>

<template>
  <div class="diagnosis-site">
    <header>
      <a class="brand" href="/growth-sniper" @click.prevent="router.push('/growth-sniper')">
        <span class="mark"><img src="/landing/g-snipers-mark.png" alt="" aria-hidden="true"></span>
        <span class="brand-copy"><strong>获客狙击手</strong><em>G-Snipers · 免费诊断</em></span>
      </a>
      <nav>
        <a href="/growth-sniper" @click.prevent="router.push('/growth-sniper')">产品</a>
        <a href="#results">诊断能力</a>
        <a href="/growth-sniper#pricing" @click.prevent="router.push('/growth-sniper#pricing')">定价</a>
      </nav>
      <button type="button" @click="goToStart">免费诊断</button>
    </header>

    <main>
      <section class="diagnosis-hero">
        <div class="hero-copy">
          <span class="eyebrow">G-SNIPERS AI DIAGNOSIS</span>
          <h1>
            <span>打开你的专属诊断工作台，</span><br>
            <span>看清 <b>SEM / SEO / GEO</b></span><br>
            <span>全部数据</span>
          </h1>
          <p>3 分钟接入，AI 自动跑出你的品牌在搜索广告、自然搜索排名、AI 搜索引擎中的真实表现。</p>
          <form class="url-form" @submit.prevent="startDiagnosis">
            <input ref="websiteInput" v-model="website" type="text" inputmode="url" placeholder="请输入你的官网地址" aria-label="官网地址">
            <button type="submit">开始免费诊断</button>
          </form>
          <div class="form-error" aria-live="polite">{{ error }}</div>
          <div class="assurances"><span>✓ 首次免费</span><span>✓ 无需安装代码</span><span>✓ 诊断结果仅您可见</span></div>
        </div>

        <div class="product-window" aria-label="诊断工作台界面示意">
          <div class="browser-bar"><i /><i /><i /><span>g-snipers.com</span></div>
          <div class="app-bar"><strong><b />Growth Sniper</strong><span>概览面板　线索管理　AI 打分　数据报告</span></div>
          <div class="app-content">
            <div class="stats">
              <div><small>总线索量</small><strong>12,847</strong><em>较上周 +18.6%</em></div>
              <div><small>转化率</small><strong>3.24%</strong><em>较上周 +0.8%</em></div>
              <div><small>AI 预测得分</small><strong>87.3</strong><em>优质线索 62%</em></div>
              <div><small>渠道占比</small><strong>42.6%</strong><em>SEM 渠道领先</em></div>
            </div>
            <div class="charts">
              <article>
                <h3>线索趋势分析</h3>
                <svg viewBox="0 0 480 170" aria-hidden="true">
                  <defs><linearGradient id="diagnosisArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#64e99c" stop-opacity=".36"/><stop offset="1" stop-color="#64e99c" stop-opacity="0"/></linearGradient></defs>
                  <path d="M5 132 C60 115,105 60,155 105 S250 30,305 67 S400 105,475 31 L475 160 L5 160 Z" fill="url(#diagnosisArea)"/>
                  <path d="M5 132 C60 115,105 60,155 105 S250 30,305 67 S400 105,475 31" fill="none" stroke="#67e99c" stroke-width="4"/>
                </svg>
              </article>
              <article class="quality">
                <h3>线索质量评分</h3>
                <div class="gauge"><span>87.3<small>AI 综合打分</small></span></div>
                <ul><li><i class="a" />优质线索 62%</li><li><i class="b" />良好线索 25%</li><li><i class="c" />待培育 13%</li></ul>
              </article>
            </div>
            <div class="channels">
              <span><b>SEM 搜索营销</b><strong>42.6%</strong></span>
              <span><b>SEO 自然搜索</b><strong>31.8%</strong></span>
              <span><b>GEO AI 搜索</b><strong>25.6%</strong></span>
            </div>
          </div>
          <small class="ui-note">产品界面及数据为功能示意</small>
        </div>
      </section>

      <section id="results" class="result-section">
        <div class="section-title">
          <span>诊断结果</span>
          <h2>进去之后，你能看到什么</h2>
          <p>全链路数据诊断，每一项都清晰可查</p>
        </div>
        <div class="diagnostic-cards">
          <article v-for="item in diagnostics" :key="item.title">
            <span class="card-icon">{{ item.icon }}</span>
            <div><h3>{{ item.title }}</h3><p>{{ item.text }}</p><small>{{ item.detail }}</small></div>
          </article>
        </div>
        <button class="center-cta" type="button" @click="startDiagnosis">立即开始免费诊断</button>
      </section>
    </main>

    <footer>
      <span>© 2026 Growth Sniper</span>
      <span>隐私政策 · 服务条款 · 联系我们</span>
    </footer>

    <div v-if="modalOpen" class="modal-backdrop" role="presentation" @click.self="modalOpen = false">
      <section class="lead-modal" role="dialog" aria-modal="true" aria-labelledby="lead-title">
        <button class="close" type="button" aria-label="关闭" @click="modalOpen = false">×</button>
        <span class="modal-kicker">FINAL STEP</span>
        <h2 id="lead-title">还差一步，马上进入你的诊断工作台</h2>
        <p class="site-confirm">正在为 <strong>{{ website }}</strong> 创建诊断任务</p>
        <form @submit.prevent="submitLead">
          <label>怎么称呼您<input v-model="form.name" autocomplete="name" placeholder="请输入姓名"></label>
          <label>邮箱<input v-model="form.email" type="email" autocomplete="email" placeholder="用于接收诊断报告"></label>
          <label>电话<input v-model="form.phone" inputmode="tel" autocomplete="tel" placeholder="请输入手机号" maxlength="11"></label>
          <label>验证码
            <span class="code-row">
              <input v-model="form.code" inputmode="numeric" placeholder="请输入验证码" maxlength="6">
              <button type="button" :disabled="countdown > 0" @click="sendCode">{{ countdown ? `${countdown}s 后重试` : '获取验证码' }}</button>
            </span>
          </label>
          <label class="agreement"><input v-model="form.agreed" type="checkbox">我已阅读并同意《隐私政策》和《服务条款》</label>
          <div class="modal-error" aria-live="polite">{{ error }}</div>
          <button class="submit" type="submit" :disabled="submitting">{{ submitting ? '正在创建诊断…' : '立即进入诊断中心' }}</button>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
:global(body) { margin: 0; background: #050e15; }
* { box-sizing: border-box; }
.diagnosis-site { min-height:100vh; position:relative; isolation:isolate; overflow-x:clip; color:#f5f4f2; font-family:"PingFang SC","Microsoft YaHei",sans-serif; background:#050e15; }
.diagnosis-site:before { content:""; position:fixed; z-index:-2; inset:0; pointer-events:none; background:linear-gradient(90deg,rgba(2,9,15,.48),rgba(5,12,20,.18) 52%,rgba(5,9,18,.28)),url('/landing/stone-network.jpg') center/cover no-repeat; transform:translateZ(0); }
.diagnosis-site:after { content:""; position:fixed; z-index:-1; inset:0; pointer-events:none; background:radial-gradient(ellipse at center,transparent 38%,rgba(1,6,10,.38) 100%); }
header { position: fixed; z-index: 30; inset: 0 0 auto; height: 72px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; padding: 0 clamp(24px,6vw,110px); border-bottom: 1px solid rgba(255,255,255,.08); background: rgba(4,13,20,.72); backdrop-filter: blur(18px); }
.brand { display:flex; align-items:center; gap:9px; color:#fff; text-decoration:none; }.brand-copy{display:flex;flex-direction:column;align-items:flex-start;line-height:1.08;white-space:nowrap}.brand strong { color:#f5f2f5; font-size:20px; }.brand em { color:#b751ff;font-style:normal;font-weight:700;font-size:13px;letter-spacing:.02em }
.mark { width:60px;height:60px;flex:none }.mark img{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 0 7px rgba(183,68,255,.55))}
nav { display:flex;gap:55px; } nav a { color:#aeb6bd;text-decoration:none;font-size:14px; } nav a:hover{color:#fff}
header>button { justify-self:end;border:0;border-radius:999px;padding:12px 27px;color:#3d1753;background:linear-gradient(100deg,#f1e5fb,#ddb4f4);cursor:pointer; }
.diagnosis-hero { min-height:100svh; display:grid;grid-template-columns:.9fr 1.1fr;align-items:center;gap:65px;padding:100px clamp(26px,5vw,96px) 38px;background:rgba(3,10,16,.28); }
.hero-copy { max-width:900px; }.eyebrow,.section-title>span,.modal-kicker { color:#ce79fa;font-size:11px;letter-spacing:2.5px; }.hero-copy h1 { margin:18px 0 24px;font-size:clamp(50px,3.6vw,64px);line-height:1.16;letter-spacing:-.055em; }.hero-copy h1 span{display:inline-block;white-space:nowrap}.hero-copy h1 b { color:#f5f1f4;text-shadow:0 0 24px rgba(203,83,255,.2); }.hero-copy>p { max-width:760px;color:#b3bbc2;font-size:17px;line-height:1.75; }
.url-form { display:grid;grid-template-columns:1fr auto;min-height:63px;margin-top:31px;padding:5px;border:1px solid rgba(215,112,255,.78);border-radius:999px;background:rgba(11,23,32,.78);box-shadow:0 0 24px rgba(186,62,255,.18); }.url-form input{min-width:0;border:0;outline:0;padding:0 23px;color:#fff;background:transparent;font-size:16px}.url-form button{min-width:195px;border:0;border-radius:999px;color:#fff;background:linear-gradient(95deg,#7228e9,#c443fb 68%,#ef9be9);cursor:pointer;font-size:16px;box-shadow:0 0 20px rgba(194,70,255,.5)}
.form-error,.modal-error { min-height:21px;margin:7px 0;color:#ff9fa8;font-size:12px; }.assurances{display:flex;gap:20px;color:#7f8b94;font-size:11px}.assurances span:before{color:#c05dff}
.product-window { position:relative;overflow:hidden;padding:12px;border:1px solid rgba(187,203,214,.45);border-radius:28px;background:#08141d;box-shadow:0 32px 80px rgba(0,0,0,.55),0 0 48px rgba(132,53,219,.22);transform:perspective(1400px) rotateY(-3deg); }
.browser-bar { height:43px;display:flex;align-items:center;gap:7px;padding:0 12px;border-bottom:1px solid rgba(255,255,255,.06); }.browser-bar i{width:8px;height:8px;border-radius:50%;background:#df4b55}.browser-bar i:nth-child(2){background:#e1a52c}.browser-bar i:nth-child(3){background:#2cb763}.browser-bar span{margin:auto;width:42%;padding:6px;border-radius:999px;text-align:center;color:#89949d;font-size:10px;background:rgba(255,255,255,.06)}
.app-bar{height:51px;display:flex;align-items:center;justify-content:space-between;padding:0 15px;color:#7e8992;font-size:11px}.app-bar strong{color:#fff;font-size:14px}.app-bar strong b{display:inline-block;width:9px;height:9px;margin-right:7px;border:2px solid #b751ff;border-radius:50%;box-shadow:0 0 8px #bd59ff}
.app-content{padding:12px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stats>div{display:flex;flex-direction:column;min-height:83px;padding:12px;border:1px solid rgba(255,255,255,.1);border-radius:9px;background:rgba(32,48,60,.58)}.stats small{color:#aab3ba;font-size:9px}.stats strong{margin:6px 0;font-size:22px}.stats em{color:#b76a78;font-size:8px;font-style:normal}.stats>div:nth-child(3) em{color:#4bd396}
.charts{display:grid;grid-template-columns:1.35fr .85fr;gap:10px;margin-top:10px}.charts article{min-height:190px;padding:14px;border:1px solid rgba(255,255,255,.09);border-radius:9px;background:rgba(24,39,49,.68)}.charts h3{margin:0;font-size:12px}.charts svg{width:100%;height:140px;margin-top:8px}.quality{position:relative}.gauge{position:absolute;left:23px;top:58px;width:145px;height:74px;overflow:hidden}.gauge:before{content:"";position:absolute;inset:0;border:14px solid #293b49;border-bottom:0;border-radius:100px 100px 0 0;box-shadow:inset 31px 4px 0 -12px #329dff}.gauge span{position:absolute;inset:auto 0 0;text-align:center;font-size:25px;font-weight:700}.gauge small{display:block;color:#8c98a1;font-size:8px;font-weight:400}.quality ul{position:absolute;right:15px;top:58px;margin:0;padding:0;list-style:none;color:#aeb7be;font-size:9px}.quality li{margin:10px 0}.quality li i{display:inline-block;width:6px;height:6px;margin-right:7px;border-radius:50%}.quality .a{background:#20a7a2}.quality .b{background:#2688cd}.quality .c{background:#d39323}
.channels{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px}.channels span{display:flex;align-items:center;justify-content:space-between;padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:8px;background:rgba(20,34,45,.68);font-size:10px}.channels strong{font-size:16px}.ui-note{position:absolute;right:20px;bottom:4px;color:#65717a;font-size:8px}
.result-section { min-height:100svh;padding:95px clamp(24px,7vw,135px) 65px;background:rgba(3,10,16,.28); }.section-title{text-align:center}.section-title h2{margin:11px 0 8px;font-size:clamp(40px,4.1vw,64px);letter-spacing:-.045em}.section-title p{margin:0;color:#aeb7be;font-size:17px}.diagnostic-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:35px;max-width:1500px;margin:70px auto 45px}.diagnostic-cards article{min-height:245px;display:flex;align-items:center;gap:24px;padding:35px;border:1px solid rgba(214,113,255,.65);border-radius:15px;background:linear-gradient(145deg,rgba(33,51,64,.76),rgba(8,18,27,.8));box-shadow:0 20px 40px rgba(0,0,0,.35),0 0 20px rgba(182,68,244,.13)}.card-icon{width:68px;height:68px;display:grid;place-items:center;flex:none;border-radius:50%;font-size:30px;background:radial-gradient(circle at 35% 30%,#e4b2ff,#a041e1 48%,#31105c 72%);box-shadow:0 0 24px rgba(190,70,255,.45)}.diagnostic-cards h3{margin:0 0 12px;font-size:28px}.diagnostic-cards p{margin:0 0 14px;color:#bac1c6;line-height:1.6}.diagnostic-cards small{color:#7f8b94}.center-cta{display:block;margin:auto;border:0;border-radius:999px;padding:16px 40px;color:#fff;background:linear-gradient(95deg,#7228e9,#c443fb 68%,#ef9be9);box-shadow:0 0 24px rgba(194,70,255,.42);cursor:pointer}
footer{min-height:78px;display:flex;align-items:center;justify-content:space-between;padding:0 clamp(24px,6vw,110px);color:#68747d;font-size:11px;border-top:1px solid rgba(255,255,255,.08);background:#050d14}
.modal-backdrop{position:fixed;z-index:100;inset:0;display:grid;place-items:center;padding:20px;background:rgba(1,7,12,.72);backdrop-filter:blur(12px)}.lead-modal{position:relative;width:min(680px,100%);padding:42px 54px 48px;border:1px solid rgba(193,211,223,.45);border-radius:23px;background:linear-gradient(145deg,rgba(27,42,54,.97),rgba(9,20,30,.98));box-shadow:0 35px 100px #000,0 0 35px rgba(185,69,255,.2)}.close{position:absolute;right:17px;top:12px;border:0;color:#aab2b8;background:transparent;font-size:30px;cursor:pointer}.lead-modal h2{margin:9px 0 8px;font-size:27px}.site-confirm{margin:0 0 22px;color:#82909a;font-size:12px}.site-confirm strong{color:#c87aff}.lead-modal form{display:grid;gap:14px}.lead-modal label{display:grid;gap:7px;color:#d9dde0;font-size:13px}.lead-modal label>input,.code-row input{height:47px;padding:0 14px;border:1px solid #64717b;border-radius:10px;outline:0;color:#fff;background:rgba(13,27,37,.7)}.lead-modal input:focus{border-color:#c55cff}.code-row{display:grid;grid-template-columns:1fr 145px;gap:11px}.code-row button{border:0;border-radius:10px;color:#fff;background:linear-gradient(90deg,#7625df,#b642f0);cursor:pointer}.code-row button:disabled{opacity:.55}.lead-modal label.agreement{display:flex;align-items:center;gap:8px;color:#7f8a93;font-size:11px}.agreement input{accent-color:#a541e4}.submit{height:53px;border:0;border-radius:999px;color:#fff;font-size:16px;background:linear-gradient(90deg,#ff9a42,#c444ec 55%,#8c22fa);box-shadow:0 0 22px rgba(188,65,245,.38);cursor:pointer}.submit:disabled{opacity:.65}
@media(max-width:1080px){header{grid-template-columns:1fr auto}nav{display:none}.diagnosis-hero{grid-template-columns:1fr;padding-top:120px}.product-window{transform:none}.result-section{min-height:auto}.diagnostic-cards{grid-template-columns:1fr}.diagnostic-cards article{min-height:170px}}
@media(max-width:650px){header{height:66px;padding:0 16px}.brand strong{font-size:18px}.brand em{font-size:13px}.mark{width:48px;height:48px}header>button{padding:10px 16px}.diagnosis-hero{padding:110px 18px 65px}.hero-copy h1{font-size:42px}.hero-copy h1 span{white-space:normal}.hero-copy>p{font-size:15px}.url-form{grid-template-columns:1fr;padding:6px;border-radius:18px}.url-form input{height:49px}.url-form button{height:47px}.assurances{flex-wrap:wrap;gap:8px 15px}.product-window{padding:6px;border-radius:16px}.browser-bar,.app-bar{display:none}.app-content{padding:4px}.stats{grid-template-columns:repeat(2,1fr)}.charts{grid-template-columns:1fr}.quality{display:none}.channels{grid-template-columns:1fr}.result-section{padding:80px 18px 55px}.section-title h2{font-size:36px}.diagnostic-cards{margin-top:40px;gap:15px}.diagnostic-cards article{min-height:0;padding:24px;gap:17px}.card-icon{width:54px;height:54px;font-size:23px}.diagnostic-cards h3{font-size:23px}footer{flex-direction:column;justify-content:center;gap:7px}.lead-modal{padding:36px 22px 30px}.lead-modal h2{font-size:23px}.code-row{grid-template-columns:1fr 120px}}
</style>
