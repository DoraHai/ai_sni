<script setup>
import { reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, fetchTenants } from '../api/auth'
import { session } from '../store/session'
import loginBackground from '../assets/login-bg.jpg'

const route = useRoute()
const loading = ref(false)
const remember = ref(true)
const form = reactive({ username: '', password: '', captcha: '' })

// 图形验证码：客户端生成校验（轻量防呆，非服务端验证码）
const CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const captchaCode = ref('')
function genCaptcha() {
  captchaCode.value = Array.from({ length: 4 }, () => CHARS[Math.floor(Math.random() * CHARS.length)]).join('')
}
genCaptcha()

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  if (form.captcha.trim().toUpperCase() !== captchaCode.value) {
    ElMessage.warning('图形验证码不正确')
    form.captcha = ''
    genCaptcha()
    return
  }
  loading.value = true
  try {
    const resp = await login({ username: form.username, password: form.password })
    session.setAuth(resp.token, resp.user, remember.value)
    const t = await fetchTenants()
    session.setTenants(t.tenants)
    ElMessage.success(`欢迎，${resp.user.display_name}`)
    const redirect = String(route.query.redirect || '')
    if (redirect.startsWith('/') && !redirect.startsWith('//')) {
      window.location.assign(redirect)
    } else {
      window.location.assign('/')
    }
  } catch (e) {
    ElMessage.error(e.message)
    genCaptcha()
    form.captcha = ''
  } finally {
    loading.value = false
  }
}

function submitOnEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  submit()
}

function forgotPwd() {
  ElMessage.info('账号与密码由管理员分配，忘记密码请联系管理员重置')
}
</script>

<template>
  <div
    class="login-page"
    :style="{ backgroundImage: `url(${loginBackground}), radial-gradient(circle at 32% 50%, #1b2840 0%, #071323 68%, #030a14 100%)` }"
  >
    <div class="panel-wrap">
      <div class="panel">
        <span class="panel-corner corner-tl" aria-hidden="true"></span>
        <span class="panel-corner corner-tr" aria-hidden="true"></span>
        <span class="panel-corner corner-bl" aria-hidden="true"></span>
        <span class="panel-corner corner-br" aria-hidden="true"></span>

        <div class="logo-row">
          <svg class="target-logo" viewBox="0 0 58 58" aria-hidden="true">
            <circle cx="26" cy="30" r="17"></circle>
            <circle cx="26" cy="30" r="11"></circle>
            <circle cx="26" cy="30" r="4"></circle>
            <path d="M26 7v7M26 46v7M3 30h7M42 30h7M37 18L53 2M42 18h7v7"></path>
          </svg>
          <div class="brand-lockup">
            <strong>获客狙击手</strong>
            <span>G-Snipers</span>
          </div>
        </div>
        <h1 class="title">AI 获客指挥台</h1>
        <p class="subtitle">汇聚 SEM、SEO、GEO 信号，持续发现高意向客户</p>

        <el-form class="login-form" @submit.prevent="submit">
          <div class="field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M10 10a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0z" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
            <input v-model="form.username" class="inp" placeholder="请输入账号" autocomplete="username" aria-label="账号" />
          </div>
          <div class="field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M5 9V7a5 5 0 0110 0v2M4 9h12v8H4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" /></svg>
            <el-input v-model="form.password" type="password" show-password placeholder="密码" class="inp-pwd" autocomplete="current-password" @keydown.enter.prevent="submitOnEnter" />
          </div>
          <div class="field captcha-field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M4 4h12v12H4z M7 13l2.5-3 2 2.5L14 9l1 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" /></svg>
            <input v-model="form.captcha" class="inp" placeholder="图形验证码" maxlength="4" aria-label="图形验证码" @keydown.enter.prevent="submitOnEnter" />
            <div class="captcha-box" @click="genCaptcha" title="点击刷新">
              <span v-for="(c, i) in captchaCode" :key="i" :style="{ transform: `rotate(${(i % 2 ? 1 : -1) * (4 + i)}deg)` }">{{ c }}</span>
            </div>
            <svg class="refresh" viewBox="0 0 20 20" @click="genCaptcha" title="换一张"><path d="M16 5a7 7 0 10.8 7M16 5V2M16 5h-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" /></svg>
          </div>

          <div class="row-between">
            <el-checkbox v-model="remember" size="small">记住我</el-checkbox>
            <span class="forgot" @click="forgotPwd">忘记密码？</span>
          </div>

          <button type="submit" class="login-btn" :disabled="loading">
            {{ loading ? '登录中…' : '登录' }}
          </button>
        </el-form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  --neon: #ea59ff;
  --neon-soft: #c98cff;
  --ink: #f9efff;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  overflow: hidden;
  background-color: #071323;
  background-position: center, center;
  background-size: cover, cover;
  background-repeat: no-repeat;
}
.login-page::after {
  content: '';
  position: fixed;
  z-index: 0;
  top: 0;
  right: 0;
  bottom: 0;
  width: 41%;
  pointer-events: none;
  background: linear-gradient(90deg, rgba(5, 15, 29, 0), rgba(5, 15, 29, 0.96) 15%, #05101f 30%);
}

.panel-wrap {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: min(33vw, 560px);
  margin-right: clamp(4.2vw, 5.2vw, 6vw);
  padding: 20px;
}
.panel {
  position: relative;
  width: min(100%, 430px);
  padding: 38px 34px 32px;
  color: var(--ink);
  background:
    radial-gradient(circle at 88% 12%, rgba(98, 72, 168, 0.2), transparent 28%),
    linear-gradient(145deg, rgba(10, 23, 43, 0.97), rgba(7, 18, 35, 0.97));
  border: 1px solid rgba(236, 124, 255, 0.78);
  border-radius: 18px;
  box-shadow:
    0 0 0 2px rgba(147, 76, 255, 0.18),
    0 0 18px rgba(230, 69, 255, 0.62),
    0 0 44px rgba(105, 54, 214, 0.38),
    inset 0 0 32px rgba(65, 42, 126, 0.14),
    0 30px 80px rgba(0, 0, 0, 0.42);
}
.panel::before {
  content: '';
  position: absolute;
  inset: 8px;
  pointer-events: none;
  border: 1px solid rgba(178, 110, 255, 0.2);
  border-radius: 13px;
}
.panel-corner {
  position: absolute;
  width: 42px;
  height: 18px;
  pointer-events: none;
  border-color: #ffa6ff;
  filter: drop-shadow(0 0 6px var(--neon));
}
.corner-tl { top: -3px; left: 22px; border-top: 2px solid; }
.corner-tr { top: -3px; right: 22px; border-top: 2px solid; }
.corner-bl { bottom: -3px; left: 22px; border-bottom: 2px solid; }
.corner-br { right: 22px; bottom: -3px; border-bottom: 2px solid; }

.logo-row {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 14px;
}
.target-logo {
  width: 58px;
  height: 58px;
  overflow: visible;
  fill: none;
  stroke: #f47cff;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 0 5px rgba(237, 74, 255, 0.95));
}
.brand-lockup { display: flex; flex-direction: column; line-height: 1; }
.brand-lockup strong {
  font-family: 'STKaiti', 'KaiTi', serif;
  font-size: 26px;
  font-style: italic;
  font-weight: 900;
  letter-spacing: 1px;
  text-shadow: 0 0 14px rgba(237, 123, 255, 0.3);
}
.brand-lockup span {
  margin-top: 6px;
  color: #ebaaff;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 16px;
  font-style: italic;
  font-weight: 700;
  letter-spacing: 1.4px;
}
.title {
  position: relative;
  z-index: 1;
  margin: 30px 0 8px;
  color: #fff7ff;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
  font-size: 30px;
  font-weight: 900;
  letter-spacing: 1px;
}
.subtitle {
  position: relative;
  z-index: 1;
  margin: 0 0 26px;
  color: rgba(244, 234, 255, 0.78);
  font-size: 13px;
  line-height: 1.7;
  letter-spacing: 0.3px;
}

.login-form { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 15px; }
.field {
  display: flex;
  align-items: center;
  gap: 11px;
  height: 48px;
  padding: 0 14px;
  overflow: hidden;
  background: linear-gradient(90deg, rgba(53, 43, 93, 0.72), rgba(37, 39, 75, 0.5));
  border: 1px solid rgba(225, 124, 249, 0.72);
  border-radius: 9px;
  box-shadow: inset 0 0 14px rgba(141, 84, 203, 0.1);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.field:focus-within {
  border-color: #ffb3ff;
  box-shadow: 0 0 13px rgba(230, 82, 255, 0.25), inset 0 0 18px rgba(151, 92, 224, 0.14);
  transform: translateY(-1px);
}
.fi { width: 19px; height: 19px; color: #f4b0ed; flex-shrink: 0; }
.inp {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: #fff4ff;
  font-size: 14px;
}
.inp::placeholder { color: rgba(225, 211, 237, 0.5); }
.inp:-webkit-autofill,
.inp:-webkit-autofill:hover,
.inp:-webkit-autofill:focus,
.inp-pwd :deep(input:-webkit-autofill),
.inp-pwd :deep(input:-webkit-autofill:hover),
.inp-pwd :deep(input:-webkit-autofill:focus) {
  -webkit-text-fill-color: #fff4ff !important;
  caret-color: #fff4ff;
  -webkit-box-shadow: 0 0 0 1000px #252340 inset !important;
  box-shadow: 0 0 0 1000px #252340 inset !important;
  transition: background-color 9999s ease-out 0s;
}
.inp-pwd { flex: 1; }
.inp-pwd :deep(.el-input__wrapper) { box-shadow: none !important; padding: 0; background: transparent; }
.inp-pwd :deep(.el-input__inner) { height: 46px; font-size: 14px; color: #fff4ff; }
.inp-pwd :deep(.el-input__inner::placeholder) { color: rgba(225, 211, 237, 0.5); }
.inp-pwd :deep(.el-input__suffix) { color: #f1e4f5; }

.captcha-field { padding-right: 6px; }
.captcha-box {
  display: flex;
  gap: 3px;
  align-items: center;
  justify-content: center;
  width: 92px;
  height: 36px;
  flex-shrink: 0;
  border: 1px solid rgba(218, 178, 255, 0.2);
  border-radius: 6px;
  background: linear-gradient(145deg, rgba(105, 102, 146, 0.85), rgba(50, 51, 90, 0.92));
  color: #fff1ff;
  cursor: pointer;
  user-select: none;
  font-family: 'Courier New', monospace;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 2px;
  text-shadow: 0 0 7px rgba(255, 255, 255, 0.45);
}
.captcha-box span { display: inline-block; }
.refresh { width: 20px; height: 20px; color: #f0e3f5; cursor: pointer; flex-shrink: 0; transition: transform 0.3s ease, color 0.2s ease; }
.refresh:hover { color: #ff9dff; transform: rotate(90deg); }

.row-between { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; }
.forgot { color: rgba(249, 238, 255, 0.82); font-size: 13px; cursor: pointer; transition: color 0.2s ease; }
.forgot:hover { color: #ff9cff; }

.login-btn {
  height: 50px;
  margin-top: 8px;
  border: 1px solid #ffb7ff;
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(177, 60, 233, 0.38), rgba(83, 38, 145, 0.26)),
    rgba(30, 27, 78, 0.78);
  box-shadow: 0 0 5px #fff, 0 0 13px #dc4cff, 0 0 28px rgba(168, 57, 255, 0.75), inset 0 0 15px rgba(220, 101, 255, 0.24);
  color: #fff;
  cursor: pointer;
  font-family: 'Noto Serif SC', 'Songti SC', serif;
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 6px;
  transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;
}
.login-btn:hover {
  transform: translateY(-2px);
  filter: brightness(1.14);
  box-shadow: 0 0 7px #fff, 0 0 18px #ef58ff, 0 0 36px rgba(165, 63, 255, 0.92), inset 0 0 18px rgba(229, 122, 255, 0.3);
}
.login-btn:active { transform: translateY(0); }
.login-btn:disabled { opacity: 0.7; cursor: not-allowed; }

@media (max-width: 1100px) {
  .login-page {
    justify-content: center;
    background-image:
      radial-gradient(circle at 50% 43%, rgba(154, 65, 224, 0.2), transparent 30%),
      radial-gradient(circle at 14% 12%, rgba(57, 111, 170, 0.16), transparent 34%),
      linear-gradient(145deg, #101c30 0%, #071323 58%, #030a15 100%) !important;
    background-position: center;
    background-size: cover;
  }
  .login-page::before {
    content: '';
    position: fixed;
    inset: 0;
    background: radial-gradient(circle at 50% 50%, rgba(216, 72, 255, 0.08), transparent 38%);
  }
  .login-page::after {
    width: 100%;
    opacity: 0.38;
    background:
      linear-gradient(rgba(200, 133, 255, 0.045) 1px, transparent 1px),
      linear-gradient(90deg, rgba(200, 133, 255, 0.045) 1px, transparent 1px);
    background-size: 72px 72px;
    mask-image: radial-gradient(circle at center, #000, transparent 76%);
  }
  .panel-wrap { position: relative; width: min(100%, 520px); margin-right: 0; }
}

@media (max-width: 560px) {
  .login-page { align-items: flex-start; overflow-y: auto; }
  .panel-wrap { min-height: 100dvh; padding: 18px; box-sizing: border-box; }
  .panel { width: 100%; padding: 30px 22px 26px; box-sizing: border-box; }
  .title { margin-top: 24px; font-size: 27px; }
  .subtitle { margin-bottom: 22px; font-size: 12px; }
  .brand-lockup strong { font-size: 23px; }
  .brand-lockup span { font-size: 14px; }
  .target-logo { width: 52px; height: 52px; }
}

:deep(.el-checkbox__label) { color: rgba(249, 238, 255, 0.82); font-size: 13px; }
:deep(.el-checkbox__inner) { background: rgba(137, 75, 180, 0.62); border-color: #d883ef; }
:deep(.el-checkbox__input.is-checked .el-checkbox__inner) { background: #a651cf; border-color: #dc7ff2; }
</style>
