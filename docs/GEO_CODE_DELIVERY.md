# GEO 代码交付说明（无生产机 · 仅交付 GEO 部分）

> **交付形态**：代码 + 本地验收脚本 + 文档，**不包含**甲方生产机部署与签字。  
> **生产上线**：由接收方在自有环境按 `docs/GEO_PRODUCTION_RUNBOOK.md` 执行（可选、后置）。  
> 日期：2026-08-06 · 关联 PR：`feat/geo-visibility-auto-patrol`（#30）

---

## 1. 交付结论

| 项 | 说明 |
| --- | --- |
| 交付物 | 本仓库中 **GEO 相关代码、迁移、前端页、测试与文档** |
| 不交付 | 生产主机、密钥轮换、Nginx 线上改配、运维 7×24 |
| 验收标准 | 本地/演示环境自动化全绿（见 §5），主环可演示 |
| 生产 Runbook | 随代码附带，**不作为本次交付门禁** |

本次「可交付」= **GEO 自助运营 MVP 代码完成 + 产品化增强代码完成 + 本地门禁通过**。

---

## 2. GEO 范围边界（代码地图）

### 2.1 属于 GEO 交付（应验收）

| 区域 | 路径 |
| --- | --- |
| GEO API 进程 | `app/geo_main.py`、`app/geo/**`、`app/api/geo.py`（若挂载） |
| 内容工作台 | `app/geo/content/**`（任务、事实、Brief、门禁、巡检、交付、渠道 Webhook…） |
| 诊断 | `app/geo/audit.py`、`app/geo/generate.py`、`app/geo/verify.py`、`app/geo/routes.py` |
| 模型 / 迁移 | `app/models/geo_*.py`、`migrations/versions/*geo*`、`0052`/`0053` 巡检 |
| Vue 前端 | `frontend/src/views/geo/**`、`frontend/src/api/geoContent.js`、router 中 `/geo/*` |
| 静态工作台 | `frontend/public/deal-sniper-prototype/geo/**` |
| 诊断中心前端 | `frontend/diagnostic-center/**`、`frontend/geo-frontend/**`（若用独立静态发布） |
| 部署模板（GEO 独立单元） | `deploy/geo-*`、`deploy/README-GEO-INDEPENDENT.md`、`scripts/deploy_geo_api.sh` |
| 验收脚本 | `scripts/accept_geo_*.py`、`verify_productization_must.py`、`e2e_geo_enhancements.py`、`smoke_geo_webhook_push.py`、`seed_geo_demo.py` |
| 文档 | `docs/GEO_*.md`、`docs/LOCAL_GEO_DEMO.md`、`docs/GEO_PRODUCTION_RUNBOOK.md`（后置） |

### 2.2 共享底座（GEO 运行依赖，非 SEM 业务交付）

GEO **共用** 且本次交付中作为依赖保留，**不要求**验收百度投放写回：

- `app/database.py`、`app/config.py`、`app/security/**`（鉴权、加密、prod_guard）
- `app/models/tenant.py`、`user` / `role` 等账号体系
- 主站 `app/main.py` 中 **挂载 geo_router** 与 **scheduler 中的 `run_geo_visibility_patrols`**（定时巡检）
- Postgres + Alembic 全库迁移链（GEO 表挂在同一 head 上）

### 2.3 明确非 GEO 交付（可不演示）

- `app/baidu/**`、SEM 出价/写回/关键词工作台业务
- 拓词、否词、搜索词、线索、oCPC 等 SEM 菜单能力
- 生产机实际运维操作

---

## 3. 推荐运行方式（接收方本地）

### 仅 GEO API（内容/可见度/发布 API）

```bash
# 配置 .env（可参考 .env.example；本地 APP_ENV=dev）
alembic upgrade head
python -m uvicorn app.geo_main:app --host 127.0.0.1 --port 8011
```

### 定时巡检需要主站进程

可见度 **定时** 任务在 `app.main` 的 scheduler 中，不在 `geo_main`：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

手动「立即巡检」只依赖 `geo_main` 即可。

### 前端

```bash
cd frontend && npm run dev          # :5173 Vue /geo/*
# 可选静态台
cd frontend/public/deal-sniper-prototype && python -m http.server 5176 --bind 127.0.0.1
```

详见 `docs/LOCAL_GEO_DEMO.md`。

---

## 4. 能力清单（代码已实现）

### 4.1 内容主环

Brief 建议 → 事实召回/绑定 → 母稿生成 → 规则补丁 / Score → 渠道稿 → 审校门禁 → URL 回填 / Webhook（官网/文档）/ **社交直发**（wechat/zhihu/baijiahao/toutiao，`auth_type=social_api` + api_url + access_token）

### 4.2 可见度

人工快照、多引擎探测、`openai_compat` 真采样、**全自动巡检**（时段/间隔/配额/落库）、引用/竞品/评价、**期次对比** Vue

### 4.3 产品化增强（代码内）

提及率口径（排除探测题、top1、未测≠0）、巡检 ops-status、编造 lint 门禁、`channel-blueprint` 分发推荐、交付 MD/打印

### 4.4 工程门禁

- `prod_guard`（仅 `APP_ENV=prod` 时强制密钥）
- Nginx 模板禁止注入 API Key（文档 + 配置注释）
- 租户 `ensure_tenant` 隔离

---

## 5. 代码交付验收命令（无生产机）

在仓库根目录，本地 API 起于 **8011**（及可选 5176）：

```bash
python -m pytest -q tests
python scripts/verify_productization_must.py
python scripts/verify_productization_must.py http://127.0.0.1:8011 geo-demo-local-key 1
python scripts/e2e_geo_enhancements.py http://127.0.0.1:8011 geo-demo-local-key 1
python scripts/accept_geo_m1.py http://127.0.0.1:8011 geo-demo-local-key 1
python scripts/accept_geo_delivery.py http://127.0.0.1:8011 geo-demo-local-key 1
# 可选 Webhook 链路
python scripts/smoke_geo_webhook_push.py
```

| 脚本 | 用途 |
| --- | --- |
| `pytest` | GEO 单测（含巡检/门禁/口径等） |
| `verify_productization_must` | 产品化工程项 + 可选 live |
| `e2e_geo_enhancements` | 增强 API 冒烟 |
| `accept_geo_m1` | 可见度/引用/渠道 bootstrap |
| `accept_geo_delivery` | 内容主环 |
| `smoke_geo_webhook_push` | 审校→导出→Webhook |

**本次代码交付签字建议：上述命令全绿即可，不要求 §4.2 生产机勾选。**

---

## 6. 建议代码交接方式

1. **合并 PR #30**（`feat/geo-visibility-auto-patrol`）到 `main`，或打 **tag**（如 `geo-mvp-2026-08-06`）。  
2. 将本文件 + `GEO_DELIVERY_CHECKLIST.md` + `LOCAL_GEO_DEMO.md` 作为交接包目录索引。  
3. 接收方若以后有生产机：再执行 `GEO_PRODUCTION_RUNBOOK.md`（与本次交付脱钩）。

### 不建议

- 从 monorepo 物理删除 SEM 目录再交付（破坏迁移链与鉴权依赖）  
- 把 `APP_ENV=prod` 的本地 demo 当成上线验收  

若必须「瘦身目录说明」，以 §2.1 清单为范围说明即可，仍建议 **整仓 git 交付**，用文档划界。

---

## 7. 签字（代码交付）

| 角色 | 姓名 | 日期 | 结论 |
| --- | --- | --- | --- |
| 研发 | | | §5 自动化全绿；GEO 范围见 §2 |
| 接收方 | | | 代码已收；本地可按 LOCAL_GEO_DEMO 起服 |
| 生产部署 | — | — | **不适用 / 后置**（无生产机） |

---

## 8. 文档索引

| 文档 | 用途 |
| --- | --- |
| 本文 `GEO_CODE_DELIVERY.md` | **仅代码交付**边界与验收 |
| `GEO_DELIVERY_CHECKLIST.md` | 功能清单；§4.2 生产机为后置 |
| `LOCAL_GEO_DEMO.md` | 本地端口与入口 |
| `GEO_PRODUCTION_RUNBOOK.md` | 将来有机器时的上线步骤 |
| `GEO_PROJECT_ROADMAP.md` | 路线图与非目标 |
