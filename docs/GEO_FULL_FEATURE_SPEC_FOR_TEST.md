# GEO 完整功能说明 · 供 Codex 双轮测试

> **版本**：`main` @ 2026-08-07（展示名 + 三级优化结构 + 按天切片 + 交付切片）  
> **交付形态**：仅 GEO 代码；无生产机。交接见 `docs/GEO_CODE_DELIVERY.md`。  
> **本文用途**：给 Codex / 自动化代理做**两遍完整回归**时的功能清单 + 命令清单。

---

## 0. 给 Codex 的任务指令（可整段复制）

```
你是 ai_sni 仓库的测试执行者。当前交付是 GEO 部分（tag geo-mvp-2026-08-06 / main）。

目标：按本文「第 9 节」把验收命令完整跑 **两遍**（Pass A 与 Pass B），两遍都必须全绿。
不要测 SEM/百度写回。不要改业务代码除非测试失败且失败原因明确是环境（端口占用、迁移未升、服务未起）。

环境约定（Windows 或 Linux 均可）：
- 仓库根目录执行命令
- 使用 .venv 中的 python
- GEO API: http://127.0.0.1:8011 （app.geo_main:app）
- 主站 API（可选，定时巡检）: http://127.0.0.1:8000 （app.main:app）
- 静态台（accept_m1 需要）: http://127.0.0.1:5176
- 鉴权头: X-API-Key: geo-demo-local-key（本地 dev）
- tenant_id=1

开始前：
1) alembic upgrade head
2) 确保 8011 在听；5176 静态 geo 在听
3) 可选 seed: python -m scripts.seed_geo_demo --tenant-id 1 --verify-facts

Pass A：按第 9.1 顺序跑完全部脚本，记录每项 PASS/FAIL。
Pass B：清空/重启 8011 后再跑一遍同样脚本（验证可重复性）。
最后输出：两遍结果对照表 + 若有失败则根因与复现命令。
```

---

## 1. 产品定位

在 SEM 平台旁落地 **GEO（生成式引擎优化）自助闭环**：

```text
网站诊断 → 内容生产（事实/Brief/母稿/渠道稿/门禁）
         → 发布回填 / Webhook
         ↘ AI 可见度（快照/巡检/引用/竞品/评价/期次）→ 交付摘要
```

- **独立进程**：`app.geo_main:app`（默认文档端口 **8011** 本地 / 生产模板 **8010**）  
- **主站共用**：鉴权、租户、Postgres；定时巡检挂在 `app.main` scheduler  
- **非目标**：微信/知乎 OAuth、代理商 HTML/ZIP 三件套、SEM 出价写回、GeoLook 15 引擎默认真采大盘

---

## 2. 前端入口（Vue :5173，权限 `geo.content`）

| 路径 | 展示名 / 功能 |
| --- | --- |
| `/geo/overview` | GEO 概览 KPI：优化文章、**品牌提及率**、**品牌点名认知率**、**AI 引用次数**；可筛 **优化业务/单元** |
| `/geo/workbench` | 工作台枢纽（主推 Vue） |
| `/geo/tasks` | **优化文章**（原内容任务）列表 |
| `/geo/tasks/:taskId` | **主编辑器**：Brief / 事实 / 生成 / 补丁 / 渠道 / 审校 / 回填 / Webhook / 分发推荐 |
| `/geo/businesses` | **优化业务 → 优化单元（关键词）** 三级管理 + 按天汇总切片 |
| `/geo/prompts` | **优化意图词**（原机会词）；可挂 `unit_id`；`question_group` / `is_brand_probe` |
| `/geo/facts` | 事实库；核验 |
| `/geo/engines` | **引擎**；`sample_mode`（mock_persona / openai_compat） |
| `/geo/ai-settings` | 租户 LLM（百炼/DeepSeek 等） |
| `/geo/publishing` | 发布渠道 + Webhook 账号 CRUD |
| `/geo/visibility` | 回答快照登记 / 探测 / 多引擎草稿 |
| `/geo/visibility/patrol` | **全自动巡检**（参数、定时、历史、ops 告警；落库后自动 rebuild 日指标） |
| `/geo/period-diff` | **期次对比** before/after Δ（品牌提及率 / 点名认知） |
| `/geo/citations` | **AI 引用次数**（域名聚合；需说明统计口径） |
| `/geo/competitors` | 竞品分析 |
| `/geo/evaluation` | 情感 / 位置 |
| `/geo/deliverables` | 交付摘要：周期 + **业务/单元切片** + 按天序列 + MD 下载 + 打印 |
| `/geo/diagnosis` 或 diagnostic-center | 网站体检 → 可桥接建优化文章 |

**静态兼容台**（:5176）：`/geo/dashboard.html`、`editor.html` 等；日常主路径是 Vue。

---

## 3. 功能域详解（测什么）

### 3.1 内容主环（核心）

| 步骤 | 行为 | 关键 API / 规则 |
| --- | --- | --- |
| 建优化业务/单元 | 三级结构顶层 | `POST /optimization-businesses`、`POST /optimization-units` |
| 建优化意图词 | 问题、组、探测题、`unit_id` | `POST /prompts` |
| 建优化文章 | 绑 prompt | `POST /content-tasks` |
| Brief | AI 建议 + 保存 | `POST .../suggest-brief`，`PATCH` task |
| 事实 | CSV/录入、核验；召回与绑定 ≥3 verified | `facts`、`retrieve-facts`、`PUT .../facts` |
| 生成母稿 | 仅用绑定事实 | `POST .../generate` |
| 规则检查 | 11 条规则 + 可抽取块 | `POST .../check` |
| 补丁 | 插入修复；正文应变长、Score 更新 | `POST .../apply-patch` |
| 渠道稿 | website/wechat/zhihu 等 | `POST .../variants`，export |
| 审校 | submit → approve | `submit-review` / `review` |
| 回填 URL | 门禁通过后 | `POST .../publications` |
| Webhook | 官网/文档 auto_publish + webhook 凭证 | `POST .../push` |

**门禁（发布/推送必须拦）**

- 规则未就绪、未审校通过  
- 可选：GEO Score / AI 审稿（默认关）  
- **编造 lint 高危**（`GEO_LINT_GATE` 默认 true）：占位竞品名等 → 400 明确文案  

### 3.2 诊断桥

- 诊断中心创建 GEO 任务：`POST /content-tasks/from-diagnosis`  
- 可种子诊断事实：`seed-diagnosis-facts`  

### 3.3 AI 可见度

| 能力 | 说明 |
| --- | --- |
| 人工快照 | 粘贴正文 + 标注提及/竞品/情感/位置/URL |
| 单引擎 probe | 草稿，默认不写库 |
| 多引擎 probe-batch | 多引擎草稿 |
| AI 标注建议 | `suggest-fields` |
| URL 抽取 | `extract-urls` |
| 真采样 | 引擎 `sample_mode=openai_compat` + Key；否则人设模拟 `simulated=true` |

### 3.4 全自动巡检

| 项 | 说明 |
| --- | --- |
| 立即巡检 | 优化意图词 × 启用引擎；`prefer_real` / `auto_persist` |
| 落库 | 写 `geo_answer_snapshots`，更新 brand mention tags |
| 落库后 | **自动 rebuild** 当日 `geo_daily_metrics`（租户/业务/单元） |
| 定时 | `enabled` + **时间段** `window_start/end_hour` + **间隔** `interval_hours` |
| 调度 | GEO service scheduler 每小时 :05（`run_geo_visibility_patrols`） |
| 日汇总兜底 | GEO service scheduler **00:40** `run_geo_daily_metrics_nightly`（近 2 天） |
| 配额 | `GEO_PATROL_MAX_RUNS_PER_DAY`（默认 24）→ 429；`MAX_CELLS_PER_RUN` 截断 |
| 运营 | `GET /visibility-patrol/ops-status`（配额/引擎健康/告警） |

### 3.5 三级结构与按天汇总

```text
优化业务 → 优化单元（关键词）→ 优化意图词 → 优化文章
```

| 能力 | 说明 |
| --- | --- |
| 业务/单元 CRUD | `optimization-businesses` / `optimization-units` |
| 意图词挂单元 | `geo_prompts.unit_id`；列表可 `unit_id` / `business_id` 筛选 |
| 日汇总 scope | `t` 租户 · `b{id}` 业务 · `u{id}` 单元 |
| rebuild | `POST /daily-metrics/rebuild` 单日或 `date_from`/`date_to` 区间 |
| 触发 | 巡检落库、快照 CRUD、定时 nightly |
| 口径 | **品牌提及率**排除探测题；**品牌点名认知率**仅探测题；**AI 引用**来自快照 `cited_urls`（次数+独立域名，非全网抓取） |

### 3.6 观测与交付

| 能力 | 口径要点 |
| --- | --- |
| content-stats | `visibility_mention_rate` **排除探测题**；无样本 → `null`（未测≠0） |
| | `probe_recognition_rate` 仅探测题；`visibility_top1_rate` 首位占比 |
| 期次对比 | 两窗 Δ：品牌提及/top1/点名认知/自有域引用 |
| 引用/竞品/评价 | 快照聚合（UI：**AI 引用次数**） |
| 交付 pack | JSON + `format=md`；可选 `business_id`/`unit_id`；含 `scope` / `daily_series` / 业务·单元切片 |

### 3.7 发布与阵地

| 能力 | 说明 |
| --- | --- |
| publishing-channels | 渠道目录、publish_mode |
| channel-accounts | webhook 凭证加密存储，响应不回显 URL 明文 |
| SSRF | 内网/本机 webhook 在非 dev 或策略下拒绝 |
| channel-blueprint | 按问题组推荐国内阵地 |
| media-placements | 空库可种子 CN 阵地 |

### 3.8 工程与安全

| 能力 | 说明 |
| --- | --- |
| 鉴权 | JWT 或 `X-API-Key`（本地 demo key） |
| 租户隔离 | `ensure_tenant` 绑定租户 403 |
| prod_guard | `APP_ENV=prod` 拒 demo/空 JWT/弱 CRYPTO |
| Nginx 模板 | 禁止注入 `X-API-Key` |

---

## 4. 主要 API 前缀

Base：`/api/v1/geo/`

| 分组 | 示例路径 |
| --- | --- |
| 健康 | `content-health`；进程级 `/health/geo`（geo_main） |
| 统计 | `content-stats` |
| 三级结构 | `optimization-businesses`、`optimization-units` |
| 意图词/事实/文章 | `prompts`（`unit_id`）、`facts`、`content-tasks`… |
| 按天汇总 | `daily-metrics`、`daily-metrics/rebuild` |
| 可见度 | `answer-snapshots`、`probe`、`probe-batch` |
| 巡检 | `visibility-patrol/settings|runs|ops-status` |
| 洞察 | `citation-insights`、`competitor-insights`、`evaluation-insights` |
| 期次 | `visibility-period-diff` |
| 交付 | `deliverables/pack`（`format=md`，`business_id`/`unit_id`） |
| 发布 | `publishing-channels`、`channel-accounts`、`.../push` |
| 引擎/AI | `tracking-engines`、`ai-settings` |
| 蓝图 | `channel-blueprint`、`media-placements` |

---

## 5. 数据与迁移

| 表/能力 | 迁移 rev 示例 |
| --- | --- |
| 内容工作台、可见度、发布… | 0036～0051 等历史 GEO 迁移 |
| 巡检 runs/settings | **`0052_geo_vis_patrol`** |
| 巡检时段/间隔/last_scheduled | **`0053_patrol_window`** |
| 优化业务/单元 + prompts.unit_id + daily_metrics | **`0054_geo_opt_hierarchy`** |

验收前：`alembic upgrade head`，`alembic current` 应到 head（含 **0054** 或更新）。

---

## 6. 配置（本地测试相关）

| 变量 | 测试建议 |
| --- | --- |
| `APP_ENV` | `dev` |
| `ADMIN_API_KEY` | `geo-demo-local-key`（与前端一致） |
| `DATABASE_URL` | 本地 Postgres asyncpg |
| `CRYPTO_MASTER_KEY_B64` | 合法 32 字节 key（见 `.env.example`） |
| `GEO_LINT_GATE` | 默认 true |
| `GEO_PATROL_MAX_RUNS_PER_DAY` | 默认 24 |
| `GEO_PATROL_MAX_CELLS_PER_RUN` | 默认 200 |
| `DASHSCOPE_API_KEY` 等 | 可选；无 Key 时巡检/探测走人设或失败有明确错误 |

---

## 7. 测试资产清单

| 类型 | 路径 |
| --- | --- |
| 单元/集成 pytest | `tests/test_geo_*.py`、`test_prod_guard.py`、`test_tenant_isolation.py`、`test_migration_revision_ids.py` |
| 产品化验 | `scripts/verify_productization_must.py` |
| 增强 API 冒烟 | `scripts/e2e_geo_enhancements.py` |
| M1 可见度环 | `scripts/accept_geo_m1.py` |
| 内容主环 | `scripts/accept_geo_delivery.py` |
| 三级结构+日汇总 | `scripts/accept_geo_hierarchy.py` |
| Webhook 链路 | `scripts/smoke_geo_webhook_push.py` |
| 演示种子 | `python -m scripts.seed_geo_demo --tenant-id 1 --verify-facts` |

**不要求**：Playwright 浏览器点击全链路（可选手测）。

---

## 8. 环境启动检查表（Codex 跑前）

```bash
# 仓库根
alembic upgrade head

# 终端 A
.venv/Scripts/python.exe -m uvicorn app.geo_main:app --host 127.0.0.1 --port 8011
# 或: .venv/bin/python -m uvicorn ...

# 终端 B（accept_m1 静态页）
cd frontend/public/deal-sniper-prototype
../../.venv/Scripts/python.exe -m http.server 5176 --bind 127.0.0.1

# 可选终端 C（定时巡检，非 HTTP 验收必须）
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 探活
curl -s http://127.0.0.1:8011/health/geo
# 期望含 "db":"ok"
```

---

## 9. 双轮测试命令（必须跑两遍）

参数默认：`BASE=http://127.0.0.1:8011`，`KEY=geo-demo-local-key`，`TENANT=1`。

### 9.1 单轮顺序（Pass A = Pass B 相同）

```bash
# 在仓库根；Windows 用 .\.venv\Scripts\python.exe 代替 python

python -m pytest -q tests

python scripts/verify_productization_must.py
python scripts/verify_productization_must.py http://127.0.0.1:8011 geo-demo-local-key 1

python scripts/e2e_geo_enhancements.py http://127.0.0.1:8011 geo-demo-local-key 1

python scripts/accept_geo_m1.py http://127.0.0.1:8011 geo-demo-local-key 1

python scripts/accept_geo_delivery.py http://127.0.0.1:8011 geo-demo-local-key 1

python scripts/accept_geo_hierarchy.py http://127.0.0.1:8011 geo-demo-local-key 1

python scripts/accept_geo_social_usability.py http://127.0.0.1:8011 geo-demo-local-key 1

# 可选但建议（Webhook 全链路；dev 可用本地 sink）
python scripts/smoke_geo_webhook_push.py
```

### 9.2 第二轮（Pass B）要求

1. 停止并重启 `geo_main`（8011）  
2. 确认 `alembic current` 仍为 head  
3. **原样再跑 9.1 全部命令**  
4. 两遍退出码均为 0，且各脚本自身 `Result: N passed, 0 failed`

### 9.3 期望基线（大约）

| 命令 | 期望 |
| --- | --- |
| pytest | 全部 passed（交付时约 190+） |
| verify_productization_must（code+live） | 0 failed |
| e2e_geo_enhancements | ≥14 passed, 0 failed（含业务/日汇总列表） |
| accept_geo_m1 | 9 passed, 0 failed（需 5176） |
| accept_geo_delivery | 10 passed, 0 failed |
| accept_geo_hierarchy | 12 passed, 0 failed |
| smoke_geo_webhook_push | PASSED（若环境无 LLM/外网，允许记录跳过原因，但优先全过） |

---

## 10. 失败时排查优先级

1. **8011 未起 / DB 连不上** → `/health/geo`  
2. **迁移未升** → `alembic upgrade head`  
3. **5176 未起** → accept_m1 静态项失败  
4. **demo key 不一致** → `.env` `ADMIN_API_KEY` vs 脚本参数  
5. **巡检日配额打满** → 换 tenant 或提高 `GEO_PATROL_MAX_RUNS_PER_DAY`（单元测不依赖真跑满）  
6. **Webhook 405/外网** → 使用 dev sink 脚本默认路径，勿依赖 example.com 真推成功  

---

## 11. 明确「测了算 GEO 过」vs「不用测」

| 要测 | 不用测 |
| --- | --- |
| 内容主环 API 验收 | 百度 SEM 出价/写回 |
| 可见度/巡检/期次/交付 API | 生产 Nginx 真机 |
| 门禁负例（未审校不可推） | 社交 OAuth |
| pytest GEO 相关 | 主站盯盘/拓词业务 |
| 租户隔离/prod_guard 单测 | 真实公网 CMS |

---

## 12. 相关文档

| 文档 | 用途 |
| --- | --- |
| `docs/GEO_CODE_DELIVERY.md` | 代码交付边界 |
| `docs/LOCAL_GEO_DEMO.md` | 端口与入口 URL |
| `docs/GEO_DELIVERY_CHECKLIST.md` | 功能清单 |
| `docs/GEO_PRODUCTION_RUNBOOK.md` | 有机器时上线（本次可不跑） |

---

## 13. Codex 最终汇报模板

```text
## Pass A
- pytest: X passed / fail?
- verify_productization_must: ...
- e2e_geo_enhancements: ...
- accept_geo_m1: ...
- accept_geo_delivery: ...
- smoke_geo_webhook_push: ...

## Pass B（重启 8011 后）
- （同上）

## 对照
- 两遍是否一致全绿：是/否
- 失败项与日志摘要
- 环境：commit/tag、OS、DB
```
