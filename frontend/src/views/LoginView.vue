<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, fetchTenants } from '../api/auth'
import { session } from '../store/session'

const router = useRouter()
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
      router.push('/')
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
  <!-- 整页背景＝渲染图（frontend/public/login-bg.jpg）；图缺失时回退 cream 渐变。
       图里左侧场景由图本身呈现，右侧叠一个功能登录卡盖住图里的静态卡位。 -->
  <div class="login-page">
    <!-- 右：功能登录卡（盖在背景图的卡位上） -->
    <div class="panel-wrap">
      <div class="panel">
        <div class="logo-row">
          <svg width="40" height="40" viewBox="0 0 40 40">
            <path d="M20 2 L35 11 L35 29 L20 38 L5 29 L5 11 Z" fill="#c79a3e" />
            <text x="20" y="27" text-anchor="middle" font-size="20" font-weight="800" fill="#fff">S</text>
          </svg>
          <span class="brand">Snipers</span>
        </div>
        <h1 class="title">AI 获客指挥台</h1>
        <p class="subtitle">汇聚 SEM、SEO、GEO 信号，持续发现高意向客户</p>

        <el-form class="login-form" @submit.prevent="submit">
          <div class="field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M10 10a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0z" fill="none" stroke="currentColor" stroke-width="1.6" /></svg>
            <input v-model="form.username" class="inp" placeholder="手机号 / 邮箱" autocomplete="username" />
          </div>
          <div class="field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M5 9V7a5 5 0 0110 0v2M4 9h12v8H4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" /></svg>
            <el-input v-model="form.password" type="password" show-password placeholder="密码" class="inp-pwd" autocomplete="current-password" @keydown.enter.prevent="submitOnEnter" />
          </div>
          <div class="field captcha-field">
            <svg class="fi" viewBox="0 0 20 20"><path d="M4 4h12v12H4z M7 13l2.5-3 2 2.5L14 9l1 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" /></svg>
            <input v-model="form.captcha" class="inp" placeholder="图形验证码" maxlength="4" @keydown.enter.prevent="submitOnEnter" />
            <div class="captcha-box" @click="genCaptcha" title="点击刷新">
              <span v-for="(c, i) in captchaCode" :key="i" :style="{ transform: `rotate(${(i % 2 ? 1 : -1) * (4 + i)}deg)` }">{{ c }}</span>
            </div>
            <svg class="refresh" viewBox="0 0 20 20" @click="genCaptcha" title="换一张"><path d="M16 5a7 7 0 10.8 7M16 5V2M16 5h-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" /></svg>
          </div>

          <div class="row-between">
            <el-checkbox v-model="remember" size="small">记住我</el-checkbox>
            <span class="forgot" @click="forgotPwd">忘记密码？</span>
          </div>

          <button type="button" class="login-btn" :disabled="loading" @click="submit">
            {{ loading ? '登录中…' : '登录' }}
          </button>
        </el-form>
      </div>
      <div class="copyright">© Snipers · AI 获客指挥台</div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: flex-end;
  /* 整页背景＝渲染图；图缺失时回退 cream 渐变 */
  background:
    url('/login-bg.jpg') center / cover no-repeat,
    linear-gradient(135deg, #f6f2ea 0%, #efe7d9 100%);
}

/* 功能登录卡：右侧定位，盖住背景图里的静态卡位 */
.panel-wrap { display: flex; flex-direction: column; align-items: center; margin-right: 5vw; padding: 20px; }
.panel {
  width: 392px; background: rgba(255, 255, 255, 0.94); backdrop-filter: blur(6px);
  border: 1px solid rgba(214, 198, 160, 0.6); border-radius: 18px; padding: 36px 34px;
  box-shadow: 0 18px 50px rgba(120, 95, 50, 0.18);
}
.logo-row { display: flex; align-items: center; gap: 12px; }
.brand { font-size: 26px; font-weight: 700; color: #2f2b26; letter-spacing: 0.5px; }
.title { font-size: 30px; font-weight: 800; color: #2b2720; margin: 28px 0 10px; }
.subtitle { font-size: 13px; color: #8a7f6a; margin: 0 0 26px; line-height: 1.6; }

.login-form { display: flex; flex-direction: column; gap: 16px; }
.field {
  display: flex; align-items: center; gap: 10px; height: 50px; padding: 0 14px;
  background: #fff; border: 1px solid #e6ddc8; border-radius: 10px; transition: border-color 0.15s;
}
.field:focus-within { border-color: #c79a3e; }
.fi { width: 19px; height: 19px; color: #b9ab8c; flex-shrink: 0; }
.inp { flex: 1; border: none; outline: none; background: transparent; font-size: 14px; color: #2f2b26; height: 100%; }
.inp::placeholder { color: #b3a98f; }
.inp-pwd { flex: 1; }
.inp-pwd :deep(.el-input__wrapper) { box-shadow: none !important; padding: 0; background: transparent; }
.inp-pwd :deep(.el-input__inner) { height: 48px; font-size: 14px; color: #2f2b26; }

.captcha-field { padding-right: 6px; }
.captcha-box {
  display: flex; gap: 2px; align-items: center; justify-content: center; width: 92px; height: 38px;
  background: #f0ece2; border-radius: 7px; cursor: pointer; user-select: none; flex-shrink: 0;
  font-family: 'Courier New', monospace; font-size: 21px; font-weight: 700; color: #6b5d3c; letter-spacing: 2px;
}
.captcha-box span { display: inline-block; }
.refresh { width: 20px; height: 20px; color: #b9ab8c; cursor: pointer; flex-shrink: 0; }
.refresh:hover { color: #c79a3e; }

.row-between { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; }
.forgot { font-size: 13px; color: #c08f38; cursor: pointer; }
.forgot:hover { text-decoration: underline; }

.login-btn {
  height: 52px; border: none; border-radius: 10px; cursor: pointer; margin-top: 8px;
  font-size: 16px; font-weight: 600; color: #fff; letter-spacing: 2px;
  background: linear-gradient(90deg, #d0a64a 0%, #bd8b34 100%);
  transition: filter 0.15s;
}
.login-btn:hover { filter: brightness(1.06); }
.login-btn:disabled { opacity: 0.7; cursor: not-allowed; }

.copyright { margin-top: 22px; font-size: 11px; color: #a99e86; }

@media (max-width: 720px) {
  .login-page { justify-content: center; }
  .panel-wrap { margin-right: 0; }
}
:deep(.el-checkbox__label) { color: #6b6250; font-size: 13px; }
</style>
