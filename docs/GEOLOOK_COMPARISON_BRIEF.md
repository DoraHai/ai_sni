# GeoLook × Growth Sniper GEO 对照简报

> 对照对象：开源 GeoLook（`_refs/geolook`）vs 本仓库 GEO（`app/geo/`、`docs/GEO_*.md`、`frontend/public/deal-sniper-prototype/geo/`）  
> 范围：逻辑与数据模型，非营销话术  
> 结论先行：**值得借方法论与可复现算法切片，不值得搬 CLI/文件仓架构。** 优先做「采样口径 + 阵地权重 + 工单验收 + 编造 lint + 拓词」五类适配，贴合中国 B2B GEO 与已有 Wave A/B/C。

---

## 1. GeoLook 能力地图

主线：`抓取 → 体检 → 采样 → 工单 → 资产 → 报告 → 自动验收 → 交付`（`scripts/geo.py` 的 `new` / `serve`）。

| 模块 | 核心逻辑 | 关键源文件 |
| --- | --- | --- |
| **项目底座** | 单 URL 建项目；LLM 仅从官网正文抽品牌/竞品/问题库；抽不到标「待确认」 | `bootstrap.py`、`geo.py` `init/new` |
| **抓站** | 多页 crawl → `evidence/pages.jsonl` + site 级 robots/sitemap/llms | `crawl.py` |
| **六维体检** | 可抓取性15 / 长度15 / 结构20 / **可抽取块25** / 权威15 / 对题性10；`block_gap` 聚合 | `audit.py` + `references/method.md` |
| **采样** | 15 引擎（API + 人工表）；问题按 `market` 路由；点名题剔除出提及率；位次/引用域名/负面线索 | `sample.py` |
| **指标** | 提及率、Top1/Top3、引用份额、GEO 健康分（五项加权，未测归一） | `sample.aggregate`、`analytics.py` |
| **拓词** | 百度下拉 + Google suggest；只产候选，人工入库；快照 diff 标「需求上升」 | `expand.py` |
| **工单** | audit/metrics/benchmark → 带 `acceptance.check` 的任务；七工作包；外部信源为 P1 | `tasks.py` |
| **阵地蓝图** | 19 阵地带 CN-GEO 引用量/位置/平台覆盖；问题组→内容形态→渠道适配 | `blueprint.py`、`cn-source-ranking.md`、`cn-platforms.md` |
| **内容工作台** | 选题池、大纲、AI 初稿、可引用度、**编造 lint**、分发清单 | `generate.py`（outline/draft/lint） |
| **部署资产** | llms.txt、JSON-LD 多类型、definition/FAQ HTML 片段 | `generate.py` |
| **验收** | 重抓 + checker DSL → 自动 `done` / 回归 `todo`；进度 before/after | `verify.py` |
| **交付** | 诊断/优化/执行三份 HTML + 交付包 CSV | `deliverables.py`、`deliver.py`、`report.py` |
| **发布** | GitHub / WP 草稿 / 公众号草稿 / Webhook；永远手动确认 | `publish.py` |
| **方法论库** | 评分阈值、采样纪律、内容模板、国内外平台 | `references/*.md` |

架构边界（刻意）：单机、`work/<slug>/` 文件仓、`http.server` 绑 127.0.0.1、**无账号/无 DB**。

---

## 2. 与我们现状对照

状态口径：**已有** = Wave A/B/C 栈已落地；**部分有** = 有雏形但缺 GeoLook 级纪律/算法；**缺失** = 产品化未做。

| GeoLook 能力 | 我们现状 | 判定 | 我们对应落点 |
| --- | --- | --- | --- |
| 网站抓取 + SSRF 安全 | 单页安全抓取 + 16 规则扣分体检 | **已有**（形态不同） | `app/geo/audit.py`、`routes.py` |
| 六维加权 + 抽取块正则 + `block_gap` | 规则清单扣分；有 FAQ/schema/长度，**无五块抽取检测、无实证阈值** | **部分有** | 可增强 `audit.py` |
| 整改建议 → 任务 | advice + `bridge.py` 一键建内容任务 | **已有** | `generate.py`、`content/bridge.py` |
| 结构化工单 + 自动验收 DSL | 内容任务状态机 + 发布门禁；**无站点重抓验收、无 acceptance.check** | **缺失**（工单验收层） | 可挂诊断 run / media placement |
| 多引擎 API 采样 + 人工表 | 人工快照 MVP + DeepSeek probe 草稿；引擎清单可配 | **部分有** | `snapshots.py`、Wave B/B3/C |
| 提及率口径（剔点名题、cn/global 分算、未测≠0） | `visibility_mention_rate` = 有快照中提及占比；人工勾选；无 probe 分离 | **部分有** | Wave C `content-stats` |
| 竞品/情感/位次 | 快照上 `competitors` / `brand_position` / `sentiment` 聚合 | **已有**（人工标注） | Wave C |
| 引用域名 Top / 大盘对照 | 快照可填 `cited_urls`；无域名聚合、无 CN-GEO 对照 | **缺失** | — |
| 问题库七组 + 市场路由 | `geo_prompts` 机会池 + tags；无七组/market 字段纪律 | **部分有** | `prompts` |
| 拓词（百度/Google suggest） | 人工录入/导入 | **缺失** | — |
| 品牌事实库 + 证据等级 A–E | `geo_facts` + 核验/过期/`evidence_publishable` | **已有**（更偏 SaaS 证据门禁） | `facts`、`evidence.py`、`rules.py` |
| 内容规则（定义/FAQ/结论/来源） | 11 条规则 + 修复补丁 + 发布 gate | **已有** | `rules.py`、`gate.py` |
| AI 初稿编造 lint（占位名/未入事实卡数字） | 生成时约束「只用绑定事实」；**无独立 lint 扫描器** | **部分有** | `generate_article.py` |
| 渠道适配母稿→分发稿 | Channel Profile 确定性改写 | **已有** | `channel_profiles.py`、`variants.py` |
| 阵地地图（引用权重/建什么/节奏） | `media_placements` + 发布渠道登记；**无实证权重、无问题组→阵地匹配** | **部分有** | `media.html`、`channels.py` |
| llms.txt / JSON-LD | 诊断侧确定性生成 Organization/WebSite/WebPage | **已有**（类型少于 GeoLook） | `app/geo/generate.py` |
| FAQ/定义 HTML 片段资产 | 内容规则要求有块；无独立 snippet 部署包 | **部分有** | — |
| 效果 before/after / 周期复跑 | B3 复核标签；无期次对比引擎 | **部分有** | Wave B3 |
| 客户交付包（三份 HTML） | 无代理商交付打包 | **缺失**（可后置） | — |
| 多租户 / Auth | FastAPI + Postgres + `geo.*` 权限 | **已有**（我们强项） | 全栈 |
| 本地文件 UI / CLI | 静态 HTML 工作台 + 独立 `geo_main` | **已有**（形态不同） | `frontend/.../geo/` |

---

## 3. 最值得借鉴的 5 点（按价值/契合度）

### ① 采样与提及率口径纪律（最高价值）

**借什么**

- 点名品牌题（品牌验证）**不进**无提示提及率；单列 probe「品牌认知」
- API ≠ Web ≠ App；算不出标 **未测（None）**，禁止用 0 冒充
- 指标：mention / top1 / top3 / own_domain_cite + 负面线索窗口

**源文件**：`_refs/geolook/scripts/sample.py`（`brand_in_question`、`analyze_answer`、`aggregate`）；`references/method.md` §4；`analytics.py` 健康分权重。

**怎么接到我们**

- 扩展 `geo_prompts`：`group`（七组）、`market`、`is_brand_probe`
- 扩展 `geo_answer_snapshots` 或派生表：自动/半自动解析 `brand_rank`、`cited_domains`、`negative_cues`
- 改写 `visibility_mention_rate`：分母排除 probe；无样本返回 `null`（已有 null 习惯可保留）
- UI：`visibility.html` / `evaluation.html` 分「可见性 vs 品牌认知」Tab

**契合**：Wave B/C 已有人工快照与简单提及率；这是把口径做诚实，而非新开自动巡检大引擎。

---

### ② 国内阵地权重 + 问题组→渠道匹配（中国 B2B 直接可用）

**借什么**

- 官网引用仅 **1.37%** → 官网当事实源；榜单站/内容平台为 P1 引用源
- 平台生态割据表（百度/豆包/元宝/千问/DeepSeek）
- `CHANNEL_FITS`：推荐→榜单/知乎；场景→公众号/头条/技术社区等

**源文件**：`blueprint.py`（`CHANNELS_CN`、`CHANNEL_FITS`、`GROUP_PLAN`）；`references/cn-source-ranking.md`；`cn-platforms.md`。

**怎么接到我们**

- 把 `CHANNELS_CN` 精简成种子数据，写入/增强 `geo_media_placements` 默认行（`authority_note` 带引用量与 why）
- 扩展发布渠道类型：`encyclopedia` / `ranking` / `tech_community`（`channels.py` 已有部分枚举）
- 内容工作台「分发清单」：按 `prompt.group` + `CHANNEL_FITS` 推荐目标阵地（挂 `editor` / `channels`）
- **不要**把 187k 引用库整仓搬进产品；用静态参考表 + 租户实测 `cited_domains` 覆盖

**契合**：已有 media placements 与 China channel adapt；缺的是「为何优先这些站」的实证优先级。

---

### ③ 可抽取块检测 + 体检 issue_codes → 可验收缺口

**借什么**

- 五块正则：定义 / 数字事实 / 对比 / how-to / FAQ（含中日英）
- `block_gap` 全站缺失率；工单 `pages.block:定义` 要求缺口下降 ≥50%

**源文件**：`audit.py`（`RE_*`、`score_page`、`block_gap`）；`tasks.py` `from_audit`；`verify.py` checker。

**怎么接到我们**

- 在 `app/geo/audit.py` 增加可选维度报告（不推翻现有 16 规则扣分）：`blocks`、`issue_codes`
- 诊断 advice 已有 acceptance 文案 → 升级为结构化 `check` 字段，供后续 verify 切片
- 内容规则可对齐：补 `numbers` / `comparison` / `howto` 检查（现有偏 definition/FAQ/conclusion）

**契合**：诊断中心已上线；增强可解释性与「修了没」闭环，服务 B2B 交付可信度。

---

### ④ 工单验收 DSL（服务 vs 建议的分界）

**借什么**

- `acceptance: {type: auto|manual, check: "site.has_llms_txt"|...}`
- 相对指标用 `baseline_count`；回归自动打回；进度 first/current/target

**源文件**：`tasks.py`、`verify.py`。

**怎么接到我们**

- **不要**新建 GeoLook 式 `tasks.json`；映射到已有对象：
  - 站点技术项 → `GeoAuditRun` 重跑对比
  - 外部阵地项 → `geo_media_placements.status` + `published_url`
  - 可见性目标 → 快照期次聚合
- 新表可极简：`geo_action_tickets`（tenant、source_audit_id、check_expr、baseline、status、progress_json）
- Wave 切片：先做 **site.\*** 与 **media published** 两类 auto checker（确定性高）

**契合**：Wave A bridge + B2 media + 诊断持久化已齐；缺的是「重跑判定」产品能力。

---

### ⑤ 初稿编造 lint + 拓词候选池

**借什么**

- Lint：占位竞品名、事实卡外数字、可疑年份（`generate.lint_draft`）
- Expand：百度/Google suggest → 七组分类 → **只候选、不自动改问题库**

**源文件**：`generate.py` `FAKE_HINTS`/`lint_draft`；`expand.py`；`content-patterns.md`。

**怎么接到我们**

- Lint → `rules.py` 新增 checks 或 `POST /tasks/{id}/lint`，发布 gate 可选拦截高风险
- Expand → `POST /prompts/expand-candidates`，结果进临时表/列表，运营勾选创建 `geo_prompts`
- 与现有「先证据后成文」一致，强化防幻觉，不依赖多模型巡检

**契合**：内容生产线已是主路径；两块都是小而高杠杆的纯逻辑移植。

---

## 4. 不建议直接搬的部分

| 不搬 | 原因 |
| --- | --- |
| `work/<slug>/` 文件仓 + `geo.json` 单一真相 | 我们是多租户 Postgres；文件锁/`fcntl` 无法水平扩展 |
| `http.server` 绑 127.0.0.1、无 Auth 的 UI | 与 FastAPI 鉴权、`geo.content`/`geo.diagnosis` 权限模型冲突 |
| 整仓 CLI 编排（`geo.py new` 九步一把梭） | SaaS 要异步任务、配额、租户隔离；可学「步骤语义」，不学进程模型 |
| 加权「GEO 健康分」五维合成总分当产品 KPI | 我们 Wave C 已明确拒绝伪科学加权总分；可内部诊断用，不对外主指标 |
| 全量 15 引擎自动 API 采样当默认 | 成本/ToS/联网口径复杂；我们应继续 **人工快照为主 + 可选 probe**，按引擎逐步开放 |
| `publish.py` 一键发公众号/WP | 我们 Phase 1 是加密账号登记 + 人工回填；连接器 Phase 2 另做 |
| 代理商三份交付 HTML 打包 | 非当前中国 B2B 自助运营主路径；顾问场景可后置 |
| 把 references 数据集当运行时依赖 | 方法论文档可 vendoring；运行时只用精炼静态表 |
| SPA/多页全站爬虫默认策略 | 我们诊断是 SSRF 安全单页；全站 crawl 要配额、深度、法律边界，另立 Wave |

---

## 5. 建议的下一步

**值得做「参考适配切片」**，但定位为 **逻辑移植 + 表结构增量**，不是 fork GeoLook。

建议切片顺序（贴合现有栈）：

1. **D0 口径切片（小）**：prompt 分组/probe 标记 + 提及率分母纪律 + 文档化「未测」——直接抬升 Wave B/C 可信度  
2. **D1 阵地种子（小）**：用 `CHANNELS_CN`/`CHANNEL_FITS` 增强 `media_placements` 默认与分发推荐  
3. **D2 抽取块 + lint（中）**：audit blocks + 内容 lint 进 rules/gate  
4. **D3 验收 MVP（中）**：media/llms/schema 类 auto verify（不做全量 metrics 验收）  
5. **D4 拓词候选（小，可并行）**：百度 suggest → prompts 候选池  

**不值得**：把 GeoLook UI/CLI 嵌进仓库，或用其替换我们内容工作台。

**是否保留 `_refs/geolook`**：建议 gitignore 或 submodule 文档说明；**产品代码只 vendoring 精炼常量/正则/checker 映射**，避免整树进主仓。

---

## 附录：GeoLook CLI ↔ 我们模块速查

| GeoLook 命令 | 我们近似能力 |
| --- | --- |
| `crawl` / `audit` | `POST` 诊断 + `app/geo/audit.py` |
| `bootstrap` | 无；事实/机会靠人工与导入 |
| `sample` / `sample-sheet` | `answer-snapshots` + probe |
| `expand` | 无 |
| `plan` / `verify` | advice + bridge；无 auto verify |
| `generate` / `lint` | `generate_article` + `rules`/`gate` |
| `blueprint` | `media_placements` + channel profiles（弱） |
| `deliver*` | 无 |
| `publish` | publishing-channels 登记（无第三方调用） |
| `ui` | `frontend/.../geo/*.html` |
