# AI 站内规划与工作台协作约定

本轮由「开发2.0」统一集成，用户授权创建「顾问工作台开发」「超管工作台开发」窗口，并协调既有 SEM、SEO、GEO 窗口。沿用现有百炼/DeepSeek 调用链。本轮不开发官网写入，只保留关闭的能力描述。

## 分工与生产基线

|负责窗口|范围|生产分支|
|---|---|---|
|开发2.0|客户侧站内任务 AI 入口、状态/证据显示、固定路由边界、联调验收|codex/production-sem|
|顾问工作台开发|console=advisor、授权任务聚合前端、工作台入口|codex/production-sem|
|超管工作台开发|console=platform 的 AI 治理视图、平台只读客户端|codex/production-sem|
|SEO 生产开发续接 2026-09-05|SEO AI 站内提案、本站限额/幂等/版本保护、顾问汇总|codex/production-seo|
|1.0（GEO 项目）|GEO AI 站内提案、项目事实/限额/幂等/版本保护、顾问汇总|codex/production-geo|
|SEM 获客工作台只读数据接入|实际共享平台后端治理与成本计量|codex/production-sem-backend|

各窗口使用独立 worktree 和单一职责分支；生产合并/发布由总控统一进行，不跨模块合并整个分支。数据库迁移先人工审核；未获审核的 api_controls_schema.sql 不得执行或启用。保留 BAIDU_WRITE_DRY_RUN=true。

## 客户与顾问接口契约

既有站内记录：`id,module,tenant_id,scope_id,title,workflow,allowed_actions,completion_evidence`。SEO scope 为 site_id；GEO scope 为 project_id，互不替代。

`GET /api/v1/{seo|geo}/workbench/advisor-tasks`：query 为可选 tenant_id、before_id、limit（最大50）。响应 `schema=1,module,items,next_before_id`。服务端先按当前顾问分配、客户绑定、项目业务范围、模块权限和启用状态过滤，再分页。补充 `scope_name,tenant_name,next_action,blocker,capabilities`。不通过全体客户枚举后前端筛选来实现权限。

`POST /api/v1/{seo|geo}/workbench/onsite-tasks/{id}/ai-proposal`：body 为 `tenant_id`、模块scope字段、`expected_revision`、UUID `request_id`、`mode=initial|revise`。响应沿用站内记录。前端只在 freshly read 的 `capabilities.ai_planning.can_generate === true` 且该记录允许 save_proposal 时提供动作；后端仍独立执行全部鉴权。

能力字段：

- `capabilities.ai_planning={enabled,can_generate,reason,daily_limit?}`。
- `capabilities.website_execution={enabled:false,status:'reserved',reason:'官网自动修改暂未接入，按批准方案人工实施'}`。
- `workflow.ai_run={request_id,state,mode,source_revision,source_hash,actor_user_id,started_at,finished_at?,error?}`。state 为 running、ready、failed、unknown、stale。错误应为安全业务描述，不能泄露原始供应商响应、密钥或提示全文。
- 提案说明建议放 `workflow.ai_proposal={summary?,items:[{id,reason,source_refs?,missing_information?}],missing_information?}`，而非添加既有验收 Item 模型禁止的字段。source_refs 使用获准来源的标识和可公开说明，不包含私密事实原文。

返回的 request_id 必须与请求一致。AI 无权批准、实施、验收或扩展数据范围；保存提案按 save_proposal 的同等语义处理，撤销旧批准及后续证据。来源、账号资格或任务版本改变后，旧 AI 结果不得覆盖人工修改。

持久化运行准入早于外部调用；nonce 去重、模块每日有限调用、供应商失败/结果未知均有真实记录。结果未知不得自动重试付费。平台 controls 未启用时也须保留模块自治限制。调用费用只在超管展示。

## 超管只读契约

`GET /api/v1/platform/ai-governance`：只允许既有超级管理员资格，响应 `schema=1,state=available|schema_pending,modules:[...]`。modules 包括 module/provider/model/configured、metering.state、limits（标明是否真实生效）、calls（failed/unknown/source/window）。无法从实际台账证明的统计返回 null/unavailable，不能填零。平台编辑及官网能力未接通时明确 disabled/reserved。

## 展示与验收

客户侧显示服务月份、重点词/问题、阶段、负责人、下一步与需要补充的资料，交付复检与排名/收录/GEO引用效果分别展示。SEO/GEO 原业务环节保留，GEO 站内与传播任务可并行，技术任务共用时关联同一证据。

第一批验收包含跨客户与跨顾问拒绝、撤权、迟到响应、nonce并发、版本冲突、供应商失败/未知、UI未保存草稿保护、输出转义、官网写入始终不可用。重要发布、事实确认、最终验收保留人工。真实供应商调用使用既有计量，开发测试优先使用隔离库和供应商替身，禁止操作真实客户网站或资金。

自动月度建单与接续只有在显式计划授权、资料有效、版本匹配且具备去重时启用；未交付的能力如实标明未启用。
