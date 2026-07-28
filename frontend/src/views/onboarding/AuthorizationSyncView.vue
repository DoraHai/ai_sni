<script setup>
import { computed } from 'vue'
import { ElMessageBox } from 'element-plus'
import { session } from '../../store/session'

const tenantName = computed(
  () => session.tenants.find((tenant) => tenant.id === session.tenantId)?.name || '当前客户',
)

const canBind = computed(
  () => !session.isLoggedIn || session.canEdit('onboarding'),
)

async function startBaiduAuthorization() {
  if (!canBind.value) return
  await ElMessageBox.alert(
    '百度服务商应用审核通过，并完成 OAuth 回调接口配置后，这里会直接跳转到百度授权页。当前按钮用于确认入口与授权流程。',
    '百度推广授权准备中',
    {
      confirmButtonText: '我知道了',
      type: 'info',
    },
  )
}
</script>

<template>
  <section class="auth-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow">首次接入</div>
        <h1>授权与同步</h1>
        <p>连接客户的百度营销账户，授权成功后自动建立账户关系并开始同步投放数据。</p>
      </div>
      <div class="sync-policy">
        <span class="policy-dot" />
        数据每 15 分钟自动同步
      </div>
    </header>

    <div class="connect-card">
      <div class="connect-main">
        <div class="baidu-mark" aria-hidden="true">
          <span class="paw-dot dot-one" />
          <span class="paw-dot dot-two" />
          <span class="paw-dot dot-three" />
          <span class="paw-dot dot-four" />
          <b>百</b>
        </div>

        <div class="connect-copy">
          <div class="platform-line">
            <h2>百度推广</h2>
            <span class="ready-tag">服务商接入准备中</span>
          </div>
          <p>
            由客户登录百度营销账户并确认授权，无需向平台提供账户密码。
            授权后可同步计划、单元、关键词、消费与转化数据。
          </p>

          <div class="connect-actions">
            <el-tooltip
              v-if="!canBind"
              content="当前角色仅有查看权限，请联系管理员完成账户绑定"
              placement="top"
            >
              <span>
                <button class="bind-button" disabled>绑定百度推广</button>
              </span>
            </el-tooltip>
            <button v-else class="bind-button" @click="startBaiduAuthorization">
              绑定百度推广
              <span aria-hidden="true">→</span>
            </button>
            <span class="safe-note">OAuth 2.0 安全授权</span>
          </div>
        </div>
      </div>

      <div class="flow-panel">
        <div class="flow-title">授权只需三步</div>
        <ol class="flow-list">
          <li>
            <span class="step-no">1</span>
            <div>
              <b>登录百度营销</b>
              <small>进入百度官方授权页</small>
            </div>
          </li>
          <li>
            <span class="step-no">2</span>
            <div>
              <b>选择推广账户</b>
              <small>可选择普通或超管账户</small>
            </div>
          </li>
          <li>
            <span class="step-no">3</span>
            <div>
              <b>确认授权并同步</b>
              <small>返回平台后自动开始拉取</small>
            </div>
          </li>
        </ol>
      </div>
    </div>

    <div class="content-grid">
      <section class="account-panel">
        <div class="section-head">
          <div>
            <h3>已绑定账户</h3>
            <p>{{ tenantName }}名下通过服务商 OAuth 接入的推广账户</p>
          </div>
          <span class="account-count">0 个账户</span>
        </div>

        <div class="empty-account">
          <div class="empty-icon" aria-hidden="true">⌁</div>
          <div>
            <b>尚未绑定百度推广账户</b>
            <p>完成首次授权后，账户名称、授权状态和最近同步时间会显示在这里。</p>
          </div>
        </div>
      </section>

      <aside class="security-panel">
        <div class="shield" aria-hidden="true">✓</div>
        <div>
          <h3>授权信息由平台安全托管</h3>
          <ul>
            <li>无需保存客户的百度账户密码</li>
            <li>访问令牌加密保存并自动续期</li>
            <li>客户解除授权后立即停止同步</li>
          </ul>
        </div>
      </aside>
    </div>

    <div class="preflight-note">
      <span class="note-mark">i</span>
      <div>
        <b>上线前置条件</b>
        <span>需先完成百度工具服务商认证、服务商应用审核，并配置正式回调地址。</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.auth-page {
  --auth-blue: #185fa5;
  --auth-blue-dark: #124c85;
  --auth-blue-soft: #edf5fc;
  --auth-ink: #1f2937;
  --auth-muted: #667085;
  --auth-line: #e4e9f0;
  min-height: calc(100vh - 122px);
  color: var(--auth-ink);
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.eyebrow {
  margin-bottom: 6px;
  color: var(--auth-blue);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.page-heading h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.page-heading p {
  margin: 8px 0 0;
  color: var(--auth-muted);
  font-size: 13px;
}

.sync-policy {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid #cde5d9;
  border-radius: 999px;
  background: #f4fbf7;
  color: #26734d;
  font-size: 12px;
  font-weight: 600;
}

.policy-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #20a464;
  box-shadow: 0 0 0 4px rgb(32 164 100 / 12%);
}

.connect-card {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.72fr);
  overflow: hidden;
  border: 1px solid var(--auth-line);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 10px 30px rgb(28 61 92 / 6%);
}

.connect-main {
  display: flex;
  align-items: flex-start;
  gap: 22px;
  padding: 32px;
}

.baidu-mark {
  position: relative;
  width: 68px;
  height: 68px;
  flex: 0 0 auto;
  border-radius: 18px;
  background: linear-gradient(145deg, #226db3, #114b83);
  box-shadow: 0 10px 22px rgb(24 95 165 / 24%);
}

.baidu-mark b {
  position: absolute;
  right: 12px;
  bottom: 8px;
  color: #fff;
  font-size: 27px;
  font-weight: 800;
  line-height: 1;
}

.paw-dot {
  position: absolute;
  border-radius: 50%;
  background: #fff;
  opacity: 0.92;
}

.dot-one { top: 13px; left: 13px; width: 9px; height: 12px; transform: rotate(-24deg); }
.dot-two { top: 8px; left: 28px; width: 10px; height: 13px; }
.dot-three { top: 12px; left: 44px; width: 9px; height: 12px; transform: rotate(24deg); }
.dot-four { top: 26px; left: 27px; width: 18px; height: 15px; }

.connect-copy { min-width: 0; }

.platform-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.platform-line h2 {
  margin: 0;
  font-size: 21px;
  font-weight: 650;
}

.ready-tag {
  padding: 3px 8px;
  border-radius: 999px;
  background: #fff5e7;
  color: #9a5b12;
  font-size: 11px;
  font-weight: 650;
}

.connect-copy > p {
  max-width: 680px;
  margin: 11px 0 20px;
  color: var(--auth-muted);
  font-size: 13px;
  line-height: 1.75;
}

.connect-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.bind-button {
  display: inline-flex;
  align-items: center;
  gap: 18px;
  min-height: 40px;
  padding: 0 18px;
  border: 1px solid var(--auth-blue);
  border-radius: 7px;
  background: var(--auth-blue);
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  box-shadow: 0 5px 14px rgb(24 95 165 / 18%);
  transition: background 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.bind-button:hover:not(:disabled) {
  background: var(--auth-blue-dark);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgb(24 95 165 / 23%);
}

.bind-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.safe-note {
  color: #7a8492;
  font-size: 12px;
}

.flow-panel {
  padding: 26px 28px;
  border-left: 1px solid var(--auth-line);
  background:
    linear-gradient(135deg, rgb(24 95 165 / 7%), transparent 52%),
    #f8fafc;
}

.flow-title {
  margin-bottom: 18px;
  color: #344054;
  font-size: 12px;
  font-weight: 700;
}

.flow-list {
  display: grid;
  gap: 17px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.flow-list li {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-no {
  display: grid;
  width: 27px;
  height: 27px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #c5d9ec;
  border-radius: 50%;
  background: #fff;
  color: var(--auth-blue);
  font-size: 12px;
  font-weight: 750;
}

.flow-list b,
.flow-list small {
  display: block;
}

.flow-list b {
  color: #344054;
  font-size: 12px;
  font-weight: 650;
}

.flow-list small {
  margin-top: 3px;
  color: #8a94a3;
  font-size: 11px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.55fr);
  gap: 16px;
  margin-top: 16px;
}

.account-panel,
.security-panel {
  border: 1px solid var(--auth-line);
  border-radius: 12px;
  background: #fff;
}

.account-panel { padding: 22px 24px; }

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf0f4;
}

.section-head h3,
.security-panel h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.section-head p {
  margin: 6px 0 0;
  color: var(--auth-muted);
  font-size: 12px;
}

.account-count {
  flex: 0 0 auto;
  color: #7a8492;
  font-size: 12px;
}

.empty-account {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 112px;
  padding: 16px 6px 4px;
}

.empty-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  background: var(--auth-blue-soft);
  color: var(--auth-blue);
  font-size: 24px;
}

.empty-account b {
  font-size: 13px;
  font-weight: 650;
}

.empty-account p {
  margin: 6px 0 0;
  color: var(--auth-muted);
  font-size: 12px;
  line-height: 1.6;
}

.security-panel {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 22px;
  background: #fbfcfe;
}

.shield {
  display: grid;
  width: 34px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #bcdcc9;
  border-radius: 17px 17px 12px 12px;
  background: #eff9f3;
  color: #208254;
  font-size: 14px;
  font-weight: 800;
}

.security-panel ul {
  display: grid;
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
  color: var(--auth-muted);
  font-size: 12px;
  list-style: none;
}

.security-panel li::before {
  content: '·';
  margin-right: 7px;
  color: #289764;
  font-weight: 900;
}

.preflight-note {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-top: 16px;
  padding: 12px 15px;
  border: 1px solid #d9e5f1;
  border-radius: 9px;
  background: #f6f9fc;
  color: #526070;
  font-size: 12px;
}

.note-mark {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: #dceaf7;
  color: var(--auth-blue);
  font-weight: 750;
}

.preflight-note b { margin-right: 10px; color: #344054; }

@media (max-width: 1100px) {
  .connect-card,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .flow-panel {
    border-top: 1px solid var(--auth-line);
    border-left: 0;
  }

  .flow-list {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .connect-main {
    padding: 24px 20px;
  }

  .flow-list {
    grid-template-columns: 1fr;
  }

  .content-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
