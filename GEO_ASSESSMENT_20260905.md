# GEO 模块评估（2026-09-05）

评估版本：`e0d2ff2bc3186827124b4bba61bca283e7089899`，来自 `origin/codex/production-geo`。

范围：本地源码审查、GEO Python 测试、前端 Node 测试和独立生产构建。未访问生产数据库，未发布，未修改业务源码或其他工作区。未完成登录后的浏览器业务验收，也未验证线上供应商配置和实际采样效果。

## 总体判断

现有代码具有较完整的 GEO 运营工作台基础，功能广度已超过简单原型，但不足以仅凭构建成功认定为成熟的自动化效果评估系统。下一阶段应优先提高采样可信度、后台任务可靠性与回归门禁，再扩大功能范围。

## 功能现状

| 功能 | 源码中已有能力 | 交付判断 |
|---|---|---|
| 品牌与知识库 | 官网提取、品牌资料、事实绑定、竞品候选 | 已有实现；候选仍需人工确认 |
| 内容生产 | 母稿、Brief、评分、渠道稿、编辑、复制 | 主流程较完整；尚未逐项进行浏览器验收 |
| 分发 | 渠道账号、推送连接器、分发记录、发布回填 | 已有实现；实际发布依赖渠道权限和配置 |
| 可见度 | 多引擎配置、回答快照、定时巡检、提及率与首选率 | 有观测基础；采样设计存在偏差风险 |
| 分析 | 引用、竞品、评价、媒体策略、站点结构、工单 | 已有页面与服务；部分高级能力在当前界面隐藏 |
| 交付 | 分享页和相关后端能力 | 部分历史入口重定向，不能将历史规划全部算作当前可访问功能 |

页面证据：`frontend/geo-frontend/src/router.js`。隐藏项证据：`frontend/src/utils/geoEditorSurface.js`，包含 `showBatchPush=false`、`showAiReview=false`、`showCompetitorAdvancedAnalysis=false` 等。隐藏可能是产品简化，不能直接视作缺陷。

## 优先处理的问题

### P1：多 worker 的任务恢复缺少执行者隔离

`deploy/geo-service.service:14` 配置 `--workers 2`。`app/geo_main.py:35` 在每个 worker 的 lifespan 中执行恢复；`app/geo/content/async_jobs.py:222` 查询全部 pending/running 作业，将 running 标失败并重新调度 pending。`run_job_in_background`（306 行）没有原子领取 pending 状态的条件更新。

因此启动交错、worker 重启或重复调度时，存在误标另一 worker 活跃任务和重复执行的路径。这是源码可确认的并发风险，本次未在多进程数据库环境复现。建议使用数据库原子领取、执行者/租约与过期恢复机制；仅给调度器加文件锁不足以保护该恢复路径。涉及模型或迁移时须单独安排共享数据库变更。

### P1：可见度采样包含品牌提示，不能直接代表自然提及

`app/geo/content/probe.py:81` 在回答生成阶段同时要求模型回答和判断品牌；107 行把品牌参考名加入用户提示。真实凭证路径也使用此提示。生成前泄露待测品牌可能影响回答，使提及率产生偏差。建议先只用原始用户问题采集回答，再由独立步骤判断品牌、竞品和引用。

当前 `openai_compat` 标记证明采用模型 API 路径；它本身不是消费者产品页面原始回答的采集证据。报告应清楚区分 API 采样、模拟与人工采集，不能将其直接承诺为公开产品的真实排名。本结论来自代码路径审查，未测量偏差幅度。

### P2：测试与当前实现有漂移，发布专属门禁覆盖范围偏窄

72 个 `test_geo*.py` 文件共运行 424 项：422 passed，2 failed。

- `test_geo_brand_profile.py:91`：预期 AI 不可用但返回 ai_used=True。测试 mock 的是 `app.ai.deepseek.is_enabled`，实现已从 `app.geo.ai_client` 导入；隔离对象不一致，应先修正测试替身并核查环境依赖，不能直接判定为业务故障。
- `test_geo_tenant_switcher.py:34`：仍要求页面包含 `GeoPrototypePageHeader` 字符串，与当前页面实现不符。应核对客户切换真实行为后更新契约，不能简单删除断言。

GEO baseline 和生产 workflow 专属门禁仅列出 11 个 Python 测试文件；通用 PR CI 另有全量 pytest。因此并非完全没有全量 CI，但 GEO 生产 push 的专属验证弱于完整回归。

GEO baseline 的 paths 未包含 `frontend/src/views/geo/**`、共享组件和工具文件，而独立 router 实际引用这些路径。独立部署不等于源码完全隔离。建议让 GEO 门禁覆盖实际依赖路径，并执行现有 Node 测试；增加租户切换、编辑保存、长任务和分发失败等行为级测试。

### P2：维护成本集中在超大文件

- `app/geo/content/routes.py`：9,606 行，146 个路由装饰器匹配。
- `frontend/src/views/geo/GeoTaskEditorView.vue`：4,990 行。
- 编辑器以外，提问、竞品等页面也超过千行。

建议按内容任务、采样、分发、报表拆分后端路由与服务；编辑器按母稿、渠道稿、评分和任务状态拆分。应逐步迁移并保留接口，避免一次性大重构。

### P2：交接资料不一致

当前 GEO 分支缺少交接文件所列的 `AGENTS.md` 和 `SYNC-INSTRUCTIONS.md`。旧 HANDOVER 与 RUNBOOK 保留过时分支、部署步骤和要求重启 SEM 的描述；与当前独立 GEO 发布约束冲突。应统一现行说明，历史内容明确标为归档，避免后续操作者误用。

### P3：首屏资源偏大

生产构建成功，入口 JS 约 799.68 kB（gzip 255.97 kB），入口 CSS 约 376.02 kB（gzip 52.15 kB）。构建报告大 chunk 警告。建议按需加载 UI 依赖并测量真实加载时间；仅凭包大小不能判定实际首屏慢。

## 验证记录

- 初次 pytest 收集因测试必填环境变量缺失中断；补充进程内测试变量后完成上述 424 项。
- 测试数据库地址显式设为本机不可用端口，未执行迁移。该轮属于以 mock 为主的测试，不等同数据库集成验证。
- `node --test frontend/tests/geoEditorSurface.test.mjs frontend/tests/geoPlatformAiSettings.test.mjs`：6 passed，主要为源码与工具契约检查。
- 独立目录安装依赖后，`frontend/geo-frontend` 的 `npm run build` 成功。
- Python 输出保存于 `geo-assessment-tests.txt`。
- 未改业务源码，未操作 SEM、SEO、登录页或线上服务。

## 建议顺序

1. 修正采样与分析混在一次提示中的设计，明确效果数据口径。
2. 解决后台作业并发领取与恢复问题，并补充针对性验证。
3. 修复测试漂移，扩大 GEO 专属门禁，完成登录后主流程验收。
4. 逐步拆分大文件、统一文档，再优化资源体积和扩展高级功能。
