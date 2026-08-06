# GEO 可交付 MVP 清单

> 目标：达到**自助运营可交付**（演示 / 内测 / 单租户上线），不是 GeoLook 对标级。  
> 日期：2026-08-06 · 关联 `docs/GEO_PROJECT_ROADMAP.md` L1

## 0. 交付定义（签字用）

在一个干净环境中，运营人员可独立完成：

```text
诊断/选题 → Brief → 事实绑定 → 母稿生成 → 规则补丁/Score
→ 渠道稿 → 审校 → 回填 URL / Webhook → 可见度快照 → 交付摘要
```

**无阻断级缺陷**（静默失败、假成功、404 入口、内网 Webhook 误导等有明确提示）。

---

## 1. 自动化门禁（合并 / 发版前必过）

```bash
# 在仓库根目录，API 已起 :8011，静态台可选 :5176
python -m pytest -q tests
python scripts/accept_geo_m1.py http://127.0.0.1:8011 geo-demo-local-key 1
python scripts/accept_geo_delivery.py http://127.0.0.1:8011 geo-demo-local-key 1
```

| 脚本 | 覆盖 |
| --- | --- |
| `pytest` | 规则、Brief merge、鉴权路径等 |
| `accept_geo_m1.py` | 可见度/引用/竞品/渠道 bootstrap/Webhook 门禁/静态页 |
| `accept_geo_delivery.py` | 内容主环：建议 Brief、召回、绑定、生成、补丁、渠道规则、审校门禁 |

- [ ] 三项全绿  
- [ ] CI（GitHub Actions `pytest`）绿  

---

## 2. 本地一键环境

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_local_geo_demo.ps1 -WithVue
# 可选：-WithDiagnosticCenter
python -m scripts.seed_geo_demo --tenant-id 1 --verify-facts
```

| 服务 | 端口 | 用途 |
| --- | --- | --- |
| 主站 API | 8000 | Vue 开发代理默认目标 |
| GEO API | 8011 | 静态台 / 独立验收 |
| Vue | 5173 | SPA 运营入口 |
| 静态台 | 5176 | 兼容完整 editor / dashboard |

**正确静态入口（勿漏 `/geo/`）：**

`http://127.0.0.1:5176/geo/dashboard.html?tenant_id=1&api_key=geo-demo-local-key&api_origin=http://127.0.0.1:8011`

- [ ] 四端口可起  
- [ ] seed 后租户有 ≥3 条 **verified** 事实  

---

## 3. 浏览器主环手测（租户 1）

> **第一步收尾（2026-08-06）**  
> - 自动化：`accept_geo_m1` 9/9 · `accept_geo_delivery` 10/10 · `verify_delivery_step1` 12/12  
> - 演示种子：`seed_geo_demo --verify-facts`（tenant 1，≥3 verified）  
> - 服务：8000 / 8011 / 5173 / 5176 已就绪  
> - 表中 **✓ 自动** = 代码/接口/页面加载已验；**☐ 目视** = 需本机点一次确认 toast/版式（浏览器自动化点击不可靠时）

### 3.1 Vue 路径（主入口）

| # | 步骤 | 期望 | 结果 |
| --- | --- | --- | --- |
| V1 | 打开 `/geo/overview` | KPI 有数或 0，无白屏 | ☐ 目视 |
| V2 | `/geo/workbench` → 内容任务 | 列表可开 | ☐ 目视 |
| V3 | 新建或打开**空 Brief**任务 → AI 建议 | 行业/受众/意图/类型/CTA 有值 + 成功提示 | ✓ 自动（delivery suggest-brief） |
| V4 | 保存 Brief | 刷新后仍在 | ✓ 自动（delivery patch brief） |
| V5 | 召回 / 一键绑 3 条 verified / 保存绑定 | 已绑 ≥3，状态 facts_bound 或可生成 | ✓ 自动（retrieve+bind） |
| V6 | 生成母稿 | 正文非空 + **成功/警告 toast**（含字数与状态；`needs_fix` 属正常需修规则，非失败）+ 页内蓝字提示 | ✓ 自动生成；**目视 toast**（代码已含 generateHint） |
| V7 | 检查就绪 → 一键应用全部补丁 | 正文字数变长，Score 更新，目标规则通过 | ✓ 自动（apply-patch body+score） |
| V8 | 生成 website/wechat/zhihu | 三页签有稿；渠道覆盖显示已有三渠道 | ✓ 自动（variants + channel rule） |
| V9 | 提交审校 → 通过 | review_status=approved | ☐ 目视（门禁负例 N2 已验未审校 400） |
| V10 | 回填公网 URL（如 https://example.com/…） | 200，publications 有记录 | ☐ 目视（需先 V9） |
| V11 | Webhook：公网 HTTPS 账号推送 | 成功或明确业务错误（非静默） | ☐ 目视 / 内网 URL 见 N3 |
| V12 | `/geo/visibility` 登记快照 | 竞品/引用页有聚合变化 | ✓ 自动（m1 snapshot loop） |
| V13 | `/geo/deliverables` 导出 MD | 可下载/可复制 | ☐ 目视 |

### 3.2 静态台路径（兼容）

| # | 步骤 | 期望 | 结果 |
| --- | --- | --- | --- |
| S1 | `5176/geo/dashboard.html` | 200 | ✓ 自动 |
| S2 | `5176/dashboard.html`（错误） | 404 或跳转说明 | ✓ 自动（404） |
| S3 | editor 打开 task → AI 建议 Brief | `briefReadyLine` 有提示，字段回填 | ✓ 页面/代码；**目视点一次建议** |
| S4 | 生成母稿 / 插入修复 | 生成后 `briefReadyLine` 显示字数与状态；插入修复后正文变长 | ✓ 代码 + API patch；**目视生成提示** |

### 3.3 门禁负例

| # | 步骤 | 期望 | 结果 |
| --- | --- | --- | --- |
| N1 | 未绑 3 事实点生成 | 明确拦截 | ✓ 自动（delivery/generate 门禁路径） |
| N2 | 未审校回填 | **合格任一种**：① 切到渠道页签后点「回填 URL」→ toast/错误区出现审校相关文案（接口 400 或预检提示）；② 页内橙色门禁「未通过审校…」可见。不必依赖按钮 disabled。 | ✓ 自动 API 400「未通过审校」+ 代码 publishGateHint |
| N3 | Webhook 指向 127.0.0.1 | 400 SSRF 提示 | ✓ 自动（历史推送门禁；m1 webhook block） |

### 3.4 第一步收尾命令（复跑）

```bash
python -m scripts.seed_geo_demo --tenant-id 1 --verify-facts
python scripts/accept_geo_m1.py
python scripts/accept_geo_delivery.py
python scripts/verify_delivery_step1.py
```

---

## 3.5 第二步：公网/演示 Webhook 推送（审校 → 导出 → 推送）

> **第二步收尾（2026-08-06）**  
> - 脚本：`python scripts/smoke_geo_webhook_push.py` → **PASSED**  
> - 官网渠道 `publish_mode=auto_publish`  
> - 账号 `demo-webhook-step2-httpbin`（id 以库中为准）  
> - 默认目标：`https://geo-dev-sink.local/hooks/geo-publish`（**仅 app_env=dev** 本地 sink，不依赖外网）  
> - 真实 CMS：`set GEO_SMOKE_WEBHOOK_URL=https://你的公网钩子` 后重跑  
> - 链路：Brief → 事实 → 生成 → 补丁 → variants → export website → 审校通过 → **push 200** + publication

```bash
# 本地（推荐，fake-ip / 无外网也可）
python scripts/smoke_geo_webhook_push.py

# 指向真实公网 HTTPS 钩子
# Windows PowerShell:
#   $env:GEO_SMOKE_WEBHOOK_URL="https://httpbin.org/post"
#   python scripts/smoke_geo_webhook_push.py
```

| 检查项 | 结果 |
| --- | --- |
| 官网 auto_publish | ✓ |
| Webhook 账号 HTTPS 凭证 | ✓ |
| 导出 website 渠道稿 | ✓ |
| 审校 submit + approve | ✓ |
| push 返回 ok / http_status 200 | ✓ |
| 可写回 publication（create_publication） | ✓ |

**UI 对照：** `/geo/publishing` → 官网页签 → 账号应显示「Webhook 已就绪」；任务编辑器选该账号点「Webhook 推送」。

---

## 4. 第三步：生产最小集 / 产品化必做

> **工程门禁（代码仓内可自动验）**  
> ```bash
> python -m pytest -q tests
> python scripts/verify_productization_must.py
> python scripts/verify_productization_must.py http://127.0.0.1:8011 geo-demo-local-key 1
> python scripts/accept_geo_m1.py
> python scripts/accept_geo_delivery.py
> ```  
> 本地 `APP_ENV=dev` 可用 demo key；**生产 `APP_ENV=prod` 启动会硬拦截 demo/空密钥**（`app/security/prod_guard.py`）。

见 `deploy/README-GEO-INDEPENDENT.md`（secrets / logs / backup / smoke）。

### 4.1 工程已落地（代码 + 文档）

| 检查项 | 状态 |
| --- | --- |
| 生产密钥门禁（prod 拒 demo key / 空 JWT / 弱 CRYPTO） | ✓ `prod_guard` + main/geo_main 启动 |
| Nginx 模板不注入 `X-API-Key`；注释禁止注入 | ✓ `deploy/nginx.conf` · `geo-routes.nginx.conf` |
| 前端生产不依赖内嵌 Key（仅 DEV + VITE_API_KEY） | ✓ router |
| 巡检日配额 + 单次格数上限 | ✓ `GEO_PATROL_MAX_RUNS_PER_DAY` / `MAX_CELLS_PER_RUN` |
| 租户隔离 `ensure_tenant` 单测 | ✓ `tests/test_tenant_isolation.py` |
| 备份与日志路径写入部署文档 | ✓ README-GEO-INDEPENDENT |
| 可见度全自动巡检（时段/间隔/落库） | ✓ API + Vue `/geo/visibility/patrol` |
| 产品化自动验脚本 | ✓ `scripts/verify_productization_must.py` |

### 4.2 上线机操作清单（目标环境签字）

- [ ] 目标机 `APP_ENV=prod`（或 `production`）  
- [ ] `alembic upgrade head`（含 `0052` 巡检表、`0053` 时段/间隔）  
- [ ] 已轮换 `ADMIN_API_KEY` / `JWT_SECRET`（≠ admin）/ `CRYPTO_MASTER_KEY_B64`（32 字节）  
- [ ] `APP_BASE_URL` 为公网 HTTPS，非 localhost  
- [ ] `geo-service` 健康：`curl -fsS http://127.0.0.1:8010/health/geo` → `"db":"ok"`  
- [ ] `content-health` 与 `/geo-health` 反代 200  
- [ ] Nginx **未** `proxy_set_header X-API-Key`；前端构建 **无** `VITE_API_KEY`  
- [ ] 按 runbook 配置 Postgres 备份 + 确认 `journalctl -u geo-service` 有日志  
- [ ] 抽测：登录 → `/geo/tasks` 主环 → Webhook 或回填 → `/geo/visibility/patrol` 一次  

> 说明：4.1 由研发在仓库闭环；4.2 需在**真实生产/预发主机**由运维+研发共同勾选，代码无法代替密钥轮换与机上验收。

---

## 5. 已知非阻塞（可进二期）

- 微信/知乎 OAuth 直发（P3）  
- 客户 HTML/ZIP 三件套加深（P4）  
- SEM↔GEO 意图枢纽（P5）  
- GeoLook 工单 DSL / 15 引擎大盘（P6）  
- 浏览器 Playwright E2E（建议后补）  

---

## 6. 签字

| 角色 | 姓名 | 日期 | 结论 |
| --- | --- | --- | --- |
| 研发 | | | 自动化全绿 |
| 产品/运营 | | | 主环手测通过 |
| 交付 | | | 可上演示 / 内测 |

**发布说明模板：**  
本版本 GEO 自助 MVP：内容闭环 + 可见度 + Webhook 回填；入口 Vue `/geo/*` + 静态 `/geo/*.html`；禁止根路径 `dashboard.html`。
