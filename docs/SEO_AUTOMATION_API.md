# SEO 辅助自动化接口契约

## SEO-01 内容审核与稿件确认

所有路径以 `/api/v1/seo` 为前缀。客户和顾问使用同一套内容对象；后端根据登录账号的数据库租户绑定、RBAC 权限和站点顾问分配记录计算可执行动作，不接受前端传入的 `role`、`advisor` 或用户名作为授权依据。

### 读取交付稿及允许动作

`GET /workbench/content-assets/{content_id}/delivery?tenant_id={tenant_id}&site_id={site_id}`

要求 `seo.content:view` 或 `edit`，并继续执行现有租户、站点和模块权限校验。返回：

```json
{
  "content": {
    "id": 88,
    "tenant_id": 1,
    "site_id": 9,
    "content_type": "article",
    "title": "示例稿件",
    "outline": "...",
    "body": "<p>...</p>",
    "version_count": 3,
    "payload_hash": "64位sha256",
    "status": "ready",
    "updated_at": "2026-10-07T10:00:00Z"
  },
  "workflow_status": "awaiting_customer_confirmation",
  "confirmation": {
    "status": "pending",
    "latest": null,
    "requires_exact_version": true,
    "approval_is_publication": false
  },
  "allowed_actions": {
    "submit_review": false,
    "review": false,
    "confirm_as_customer": true,
    "confirm_as_advisor_proxy": false,
    "reject_as_customer": true,
    "reject_as_advisor_proxy": false,
    "edit_content": false,
    "start_publication": false
  },
  "permission_basis": {
    "actor_user_id": 12,
    "tenant_bound_customer_account": true,
    "active_site_advisor_assignment": false,
    "seo_content_permission": "view"
  },
  "result_basis": {
    "internal_review_status": "ready",
    "customer_confirmation_status": "pending",
    "publication_status": "not_loaded",
    "page_check_status": "not_loaded",
    "search_effect_status": "not_attributed_to_single_content"
  }
}
```

`confirmation.status` 为 `pending | approved | rejected | stale`。`stale` 表示历史确认存在，但不再对应当前 `version_count + payload_hash`。审核通过、稿件确认、发布成功、页面检查与搜索效果分别返回，不能互相代替。

代码先部署而数据库仍为 `0104` 时，交付接口明确返回 `workflow_status=confirmation_unavailable`、`confirmation.status=unavailable`，并将客户确认、顾问代确认和开始发布三个动作全部设为 `false`。`unavailable` 表示 0105 确认结构尚未迁移，不能解释为 pending、已确认或拒绝。兼容期内原有发布后端保持既有行为，但新工作台不得显示可确认或依据该状态启动发布。

### 客户确认或顾问代确认

`POST /workbench/content-assets/{content_id}/confirmations?tenant_id={tenant_id}`

```json
{
  "version_count": 3,
  "payload_hash": "从 delivery 原样回传的64位sha256",
  "decision": "approve",
  "actor_mode": "customer_direct",
  "note": "同意发布"
}
```

- `customer_direct`：必须是实名 JWT 账号，且账号的服务端 `tenant_id` 等于目标客户，并有 `seo.content:view` 或 `edit`。全客户账号不能用此模式冒充客户；已有当前站点顾问分配的账号即使也绑定该客户，仍必须使用 `advisor_proxy`，不能把代确认记成客户亲自确认。
- `advisor_proxy`：必须是实名 JWT 账号，同时具备数据库角色授予的 `seo.content:edit`，并在 `seo_site_advisor_assignments` 中有目标租户和站点的 active 分配。`tenant_id=None`、角色名称或前端标志都不构成代确认授权。
- 代确认记录保存真实 `actor_user_id`、当时的服务端 `actor_role_name`、`actor_mode=advisor_proxy`、时间、意见、准确版本与摘要，不记录成客户本人操作。
- `reject` 必须填写 `note`；稿件退回 `drafting`，修改后版本递增，旧确认自然变为 `stale`。
- 同一账号对同一准确版本、相同决定和意见的重复请求幂等返回现有结果。

主要错误：

| HTTP | `detail.code`/文本 | 含义 |
| --- | --- | --- |
| 400 | 退回稿件时必须填写修改意见 | `reject` 缺意见 |
| 403 | 稿件确认必须由实名登录账号操作 | API Key 或无用户身份不能确认 |
| 403 | 只有绑定当前客户的实名账号可以直接确认稿件 | 客户直接确认身份不成立 |
| 403 | 只有当前站点已分配且具备内容编辑权限的顾问可以代确认 | 缺顾问分配或编辑权限 |
| 409 | `content_version_conflict` | 版本或摘要变化；响应同时给当前版本和摘要 |
| 409 | 只有内部审核通过且尚未发布的稿件可以确认或退回 | 内容状态不在 `ready` |

### 精确版本内部审核

现有接口继续使用：

- `POST /content-assets/{content_id}/submit-review?tenant_id=...`
- `POST /content-assets/{content_id}/review?tenant_id=...`

请求新增可选的 `version_count`。共享工作台必须发送读取时的版本；不一致返回 409 `content_version_conflict`。字段暂时保持可选以兼容已上线 SEO 内页，后续在旧调用方全部升级后才能收紧为必填。

### 顾问分配

- `GET /workbench/advisor-assignments?tenant_id=...&site_id=...`
- `PUT /workbench/advisor-assignments`

```json
{
  "tenant_id": 1,
  "site_id": 9,
  "advisor_user_id": 7,
  "active": true
}
```

读取要求 `seo.content:edit` 与 `settings.accounts:view/edit`；写入必须是实名账号且同时具备两项 edit。被分配账号必须存在、启用、未绑定其他客户，并由数据库角色授予 `seo.content:edit`。

### 发布门禁与未知结果

下列现有入口新增准确版本确认门禁：

- `POST /content-distribution/preflight`
- `POST /content-distribution/publish`
- `POST /content-distribution/publications/manual`
- `POST /content-distribution/publications/{id}/complete`
- `POST /content-distribution/publications/{id}/materials`
- `POST /content-distribution/publications/{id}/retry`

无有效确认返回 409 `content_confirmation_required`。预检不会整体报错，而是在对应组合的 `errors` 中标出未确认。旧稿件和已有发布记录不会自动补造确认；迁移上线后需要由客户或已分配顾问对准确当前版本进行一次真实确认，之后才能新建、完成人工发布或重试。已提交到外部平台的同步查询不因门禁停止，以便继续核对实际结果。

当最近一次发布尝试为 `outcome=unknown` 或 `requires_manual_review=true` 时，重试请求除原有 `confirm=true` 外还必须提供：

```json
{"manual_check_outcome": "not_published"}
```

否则返回 409 `publication_outcome_unknown`，防止未知结果盲重试。

## 数据库与部署依赖

迁移源文件：`migrations/versions/20261007_0105_seo_content_confirmations.py`，父版本 `0104_seo_page_ai_tdk`。只新增 `seo_site_advisor_assignments` 与 `seo_content_confirmations`，不改客户现有内容和发布数据。本批未执行迁移、部署或数据回填。

SEO 健康检查兼容 `0104`（代码先发布但新接口不可用）与 `0105`，到达 `0105` 时额外验证两张表的必要列及确认表约束。正式上线必须单独批准迁移，并在启用新前端动作前完成管理员顾问分配。

## SEO-02 服务状态与发布后核验

### 服务阶段只读状态

`GET /workbench/service-status?tenant_id={tenant_id}&site_id={site_id}`

要求同时具备 `seo.content:view` 和 `seo.site:view`，并通过租户、模块和站点范围检查。接口只读取数据库，不启动爬虫、排名采集、AI、发布或报告任务。

响应的 `phases` 包含 `SEO-A01/A02/A03/A05/A06/A07`。每段统一返回：

- `state`: `ready | needs_attention | not_ready | no_data`；
- `blockers`: 可机读缺项，如 `target_keywords_missing`、`crawl_run_missing`、`publication_checks_incomplete`；
- `facts`: 现有对象数量、最近运行或状态分布；
- `as_of`: 对应事实的最近观测时间，没有数据时为 `null`。

`evidence_endpoints` 指向原有明细接口。阶段状态只是已有事实的汇总，不替代稿件确认、发布结果、页面核验或搜索效果证据。

排名阶段除总观测数外，还按每个 active 关键词返回 `keywords_without_observation`、`keywords_with_stale_observation` 以及最多 100 个对应关键词 ID。过期阈值复用百度排名采集的新鲜度配置；列表超出上限时 `coverage_truncated=true`。历史上存在过排名数据但当前已过期，不会继续显示为 ready。

数据与报告阶段按 `metric_type + dimension + source` 只取最新一条指标观测，再汇总 `available_metric_series` 和状态分布。最新记录为 `pending/partial/failed/stale/not_configured` 时返回 `latest_metric_observations_incomplete`；旧记录不会覆盖当前状态。响应同时给出只读月报入口，是否能生成报告仍由现有月报接口根据发布、页面核验、统计来源和图片证据逐项说明。

`service-status.phases.*.state` 的 `ready/needs_attention/not_ready/no_data` 仅描述当前持久化事实是否齐备，不是任务状态或完成判定。A04 稿件确认必须读取 content delivery；任务完成必须读取 `task.status=done` 且存在服务端核实的 `completion_evidence`。响应的 `semantics` 和 `evidence_endpoints` 给出这些来源。负责人、时间线、发布回填和回执只有已有真实记录时才引用；缺失字段保持 `null/unknown`，服务端不会为了 UI 显示批量补造流程记录。

### 顾问维护服务计划

- `GET /workbench/service-plan?tenant_id={tenant_id}&site_id={site_id}`
- `PUT /workbench/service-plan`

读取要求同一站点的 `seo.content:view` 与 `seo.site:view`。写入必须是实名账号，同时有 `seo.content:edit`、`seo.site:edit`，并存在当前租户/站点的 active 顾问分配；全租户权限或角色名称不能代替分配记录。

GET 额外返回服务端计算的 `allowed_actions.update_service_plan` 和 `permission_basis`。后者包含 `actor_user_id`、`schema_ready`、内容/网站权限等级、`active_site_advisor_assignment` 及 `update_denial_reason`。拒绝原因可为 `advisor_assignment_schema_unavailable`、`authenticated_user_required`、`content_and_site_edit_permissions_required` 或 `active_site_advisor_assignment_required`。这些字段只用于界面解释；PUT 每次仍会重新检查身份、双 edit 权限、0105 结构、active 顾问分配及 revision，前端不能把 GET 结果当作授权凭证。

```json
{
  "tenant_id": 1,
  "site_id": 9,
  "expected_revision": 2,
  "optimization_directions": ["技术 SEO", "核心产品内容增长"],
  "content_topics": ["减速机选型"],
  "service_note": "首期先补齐产品页和技术资料",
  "status": "active"
}
```

每次成功写入 revision 加一，并由服务端记录真实 `updated_by` 和 `updated_at`。旧 revision 返回 409 `service_plan_version_conflict`，避免两个顾问页面互相覆盖。关键词和品牌资料继续使用现有关键词、品牌资产接口，服务计划不复制它们，也不冒充已经执行的定时任务。

SEO-08 增加 `content_cycle_enabled`（默认 false）及 `content_interval_days`（1–90，默认 7）。PUT 不提供这两个字段时保留旧值，以兼容既有客户端。已分配顾问开启后，独立 SEO 调度每分钟检查到期情况：每站点最多一条未结束内容执行链，按主题顺序轮换，每次只建一个选题稿件；错过多期不会集中补建。周期从上一次成功创建起算，修改间隔在下一次创建时应用；暂停、修改计划不会清除游标。关闭周期只停止新周期创建，已有执行链仍继续；`status=paused` 才暂停现有执行链接续。

当 `status=paused` 时，不再接受新的手工排名/竞品/外链采集，后台排名、竞品、外链和驾驶舱指标调度在选取站点时也会跳过该站点；已经持久化的发布、审核、任务、证据和历史数据仍可读取，不会被删除。改回 `active` 后后续调度恢复候选资格，但不会补造暂停期间的运行结果。

### 发布成功后的页面核验

以下入口在发布事实成功提交后，自动尝试为该发布记录建立 `seo_page_captures` 核验任务：

- `POST /content-distribution/publish`
- `POST /content-distribution/publications/manual`
- `POST /content-distribution/publications/{id}/complete`
- `POST /content-distribution/publications/{id}/sync`
- `POST /content-distribution/publications/{id}/retry`

响应增加：

```json
{
  "page_verification": {
    "state": "queued",
    "capture_id": 88,
    "reason": null
  }
}
```

`state` 可为 `queued | existing | not_queued | not_applicable`。常见 `reason` 包括 `capture_disabled`、`publication_url_missing`、`publication_site_missing`、`capture_recent` 和 `capture_queue_failed`。发布成功、页面核验排队、页面核验成功仍是三个独立事实。核验队列异常只回报缺口，不回滚已经落库的真实发布结果。

### 页面整改与复检任务

通用 SEO 任务接口新增 `action_type=page_remediation`，要求 `seo.site:edit`，创建参数必须包含当前站点真实存在的 `page_id`。服务端会固定保存创建时页面状态、问题码和检查时间，不能由请求伪造这些基线字段。

任务完成仍使用 `PATCH /tasks/{task_id}` 的 `status=done`。SEO-11 起要求目标页面在任务创建后重新检查、状态为 `healthy` 或 `verified`、HTTP 2xx、问题码为空；还必须有相同租户/站点/URL 的最新成功快照及任务创建后完成的抓取记录，快照时间与当前检查时间对应。站点健康页面总数另作效果背景，持平或下降不阻止目标完成。人工修改状态或把任务手工打勾不能代替真实快照。完成证据格式见本文 SEO-11。

指标快照新增：

```json
{
  "metric_key": "seo.site.healthy_page_count",
  "unit": "count",
  "description": "当前网站最近一次检查状态为 healthy 或 verified 的页面数量；仅页面重新检查后的持久化结果计数。"
}
```

### SEO-08：内容服务执行链（本地实现，尚未上线）

复用 `seo_tasks`、`seo_content_assets`、版本确认、分平台发布记录与页面采集对象，无新增数据库迁移。依赖已单独审核的 0105 结构：0104、未知 revision 或多个 revision 时不执行工作。本文所有路径前缀为 `/api/v1/seo`。请求中的 4/2 仅为隔离测试示例，不代表获准生产资源。

**触发：**`POST /workbench/service-plan/run`

```json
{"tenant_id":4,"site_id":2,"expected_revision":1,"request_id":"906a7aa2-f9a6-4412-8602-80f31ce6a624"}
```

```json
{
  "created":true,
  "task":{
    "id":102,"module":"seo","action_type":"content_delivery","title":"内容交付 · 选型",
    "status":"in_progress","created_by":"7","assignee_role":"seo_advisor",
    "params":{
      "content_id":101,"plan_revision":1,"trigger":"advisor","plan_topic":"选型",
      "request_key":"request:906a7aa2-f9a6-4412-8602-80f31ce6a624",
      "assignment_advisor_id":7,"triggered_by_user_id":7,
      "publication_policy":"advisor_uses_existing_distribution",
      "phase":"awaiting_draft","waiting_for":"advisor","blocker":null,
      "phase_since":"2026-10-07T08:00:00+00:00","attention_due_at":"2026-10-09T08:00:00+00:00",
      "attention_overdue":false,"notification_sent":false,
      "history":[{"phase":"awaiting_draft","blocker":null,"at":"2026-10-07T08:00:00+00:00","actor":"system"}],
      "history_truncated":false
    },
    "completion_evidence":null,"created_at":"2026-10-07T08:00:00Z","updated_at":"2026-10-07T08:00:00Z"
  }
}
```

同一 tenant/site/request_id 的重复请求返回原任务，`created=false`，即使计划已变更或任务已结束也不会新建。新 request_id 与未结束执行链冲突返回 409 `content_workflow_already_active`；计划版本冲突返回 409 `service_plan_version_conflict`；暂停返回 409 `service_plan_paused`；缺选题或优化方向返回 409 `service_plan_content_topics_required`。服务端锁站点，选题稿件、任务和游标原子提交。新稿件是 `planned`，仅有选题及制作要求，不伪装成 AI 已生成正文。

**接续：**`POST /workbench/content-workflows/{task_id}/advance`

```json
{"tenant_id":4,"site_id":2,"publication_id":91}
```

`publication_id` 可省略；当前准确版本只有一条发布记录时自动关联，多条时必须由顾问明确选择。错误租户、稿件或版本的记录返回 409 `publication_scope_or_version_mismatch`。响应是与上述 `task` 相同的标准任务对象。自动调度执行同一接续函数，真人完成原有动作后无须再创建新执行链。

这两个 POST 均要求实名账号、内容与网站双 edit 权限、服务端 active 站点顾问分配、有效 SEO 模块及活动站点。仅全租户权限不够。401/403 沿用现有认证；任务不在指定租户/站点返回 404；版本结构不可用返回 503 `content_workflow_schema_unavailable`。客户继续仅操作稿件确认。定时触发记录 `created_by=cockpit`、`trigger=scheduled`、`triggered_by_user_id=null`，不会伪装顾问实际点击。

| params.phase | 依据及下一步 |
| --- | --- |
| awaiting_draft | 选题已持久化，顾问通过既有内容编辑/生成入口补齐正文；本批不自动调用付费 AI |
| awaiting_internal_review | 有正文但未 ready/published，走既有 submit-review/review |
| awaiting_confirmation | 当前版本无有效 approve，客户确认或顾问代确认；stale/rejected 保留原因 |
| awaiting_publication | 当前版本已确认，顾问选择渠道，走既有分发预检/发布或人工发布登记 |
| awaiting_publication_selection | 当前版本多条发布记录，明确选择本条执行链跟进的记录；不表示所有渠道交付完毕 |
| awaiting_manual_publication | 已有 manual_required/draft_created/preparing 记录，顾问完成真实操作后调用既有 publications/{id}/complete 回填 |
| publication_needs_check | failed/publishing/未知状态，或缺少地址/时间；顾问核对，执行链不调用重试或重发 |
| awaiting_page_evidence | 发布事实已存在，复用/排队该地址的自动页面证据；pending 可在重启后派发 |
| page_evidence_needs_attention | 采集不可用、失败、超时或只有手工截图；使用原有页面采集入口复检，不自动反复请求 |
| page_evidence_ready | 已有页面证据，但站点近7天发布篇数尚未证明比创建时增加；不能手工打勾为完成 |
| completed_with_page_evidence | 实际目标版本发布 + 对应地址自动页面证据，保存 completion_evidence 后 done；全站总量另列 |
| paused / needs_attention | 计划暂停 / 内容缺失或失去归属，停止新的接续 |

`waiting_for` 表示处理角色：advisor / customer_or_advisor / system / null，不是个人账号分配。`assignment_advisor_id` 仅是创建时分配依据，后续授权每次重新核对。撤销顾问分配、站点/模块失效会停止调度；任务字段是最近一次持久化评估结果，GET 不隐式刷新或执行。顾问可手动调用 advance 取得当前拒绝原因。

**读取、取消与提醒：**使用既有 `GET /tasks`、`GET /tasks/{id}`，租户和站点隔离不变；列表 `limit` 默认 50、最多 100，按 id 降序，`before_id` 游标分页，无全量总数。GET 不创建、生成、采集或发布。`DELETE /tasks/{id}` 取消未完成链，保留稿件和外部发布事实；PATCH 不允许手工修改此类任务的 status/assignee_role 或伪造 done。每个阶段等待超过两天仅设 `attention_overdue=true`，无站外通知；历史保留最近100次阶段/原因变化，截断时明确标记，日常不重复追加相同状态。

完成证据引用真实 `content_id/publication_id/source_version/confirmation_id/capture_id/page_url/published_at/captured_at/sha256`。SEO-11 起使用任务目标交付指标，站点 `seo.content.published_7d_count` 的 before/after/change_abs 单列在 `effect_context`；滚动窗口减少、其他文章归档或长期恢复不阻止已证实的目标交付。它表示一条选定渠道的发布及页面证据交付，**不表示页面全部 SEO 检查通过、已被收录或搜索效果提升**，`seo_effect=not_evaluated`。目标发布必须在任务创建后且不晚于当前时间，自动证据必须在发布后且非未来时间；其余版本、确认、关联与证据条件不变。

本批首条可运行链以顾问制作/渠道操作为正式人工步骤；已配 API 渠道仍由顾问调用既有分发接口。周期网站诊断、自动异常建单、周期报告和主动通知尚未由本链实现，不能据此将 A01–A07 全部标记完成。

### SEO-09：网站、监测、月报周期与工作台执行进度

这是 SEO-08 之后的本地增量，不代表已上线。复用原任务、页面/排名快照、月报生成器及顾问分配，无新增迁移。真实页面采集/平台发布/数据库迁移仍须按获准范围执行。本轮测试只有本地数据库和假供应商。

#### 哪些自动、哪些等人工

| 链 | 程序执行 | 人工阶段及边界 |
| --- | --- | --- |
| SEO-08 内容 | 周期建立选题稿件和任务、读取审核/准确版本确认、跟进选定发布记录、排页面证据 | 顾问制作稿件、内审、选择渠道和发布/回填；客户或顾问确认准确版本。不是全自动 AI 生成发布 |
| 周期网站诊断 | 每轮选取最近检查最旧的最多1–10个已登记页面；每站点逐个抓取，保存既有 run + snapshot；问题生成/复用 page_remediation 子任务；真实复检后接续 | 人工实施网站修改，使用既有单页 audit 复检；失败单页需顾问显式 retry。无页面清单时需补录后取消旧链并重新触发，不自动扩大域名或发现全站 |
| 排名异常待办 | 根据已存百度桌面全国自有域名观测生成缺报、过期或下降至少5位的具体关键词任务；新同范围观测到来后自动核对并结束 | 排名采集仍由既有定时任务/手工采集接口负责，本链不新增付费排名请求；下降需新观测恢复至异常前排名，删除/停用关键词不算解决 |
| 月报 | 自动生成上一个已结束北京时间自然月的 HTML 报告并冻结 SHA256、数据行引用、缺数说明；周期不重复生成同月 | 顾问对准确报告哈希填写业务说明后结束，无客户签收要求。统计缺失不会补零或自动拉取；不生成/推送 PDF，不内嵌截图，不冒充单篇点击归因 |

周期均默认关闭。在既有 `PUT /workbench/service-plan` 中可设置：

```json
{
  "website_cycle_enabled":true,
  "website_interval_days":7,
  "website_max_pages":5,
  "monitoring_cycle_enabled":true,
  "monitoring_interval_days":1,
  "report_cycle_enabled":true
}
```

以上是新增字段片段，仍需携带 tenant_id/site_id/expected_revision/optimization_directions 等原契约字段。省略新增字段时保留旧值。网站间隔1–90天，监测1–30天，网站每轮最多10页；开启监测还需 `seo.keywords:edit`。各类型每站点最多一个未结束任务，明确触发也计入周期游标；报告按上一个已结束月去重，错过多期不批量补生成。暂停停止新动作；已开始的请求可保存事实。关闭某周期只停止新任务，不等于取消现有任务。

单页诊断复用每日 crawl_urls 配额，每次只预留1个 URL，遵循原 robots/SSRF 检查并重新验证页面属于站点域名。未开始的 queued 工作可重启接续；running 超过两分钟变为待人工核对，不重复抓取。结果回写前再核对页面归属、URL 和最新检查时间，不能覆盖在此期间产生的较新人工复检。

排名异常每轮最多处理200个 active 关键词；超出时明确 `monitoring_keyword_limit_200`，不把未检查部分当正常。无关键词为 `keyword_inventory_required`，仅阻塞该周期，网站和报告照常推进。无异常时记录 `status=cancelled / phase=no_actionable_issues` 的系统空操作回执，保留 UUID 幂等，不伪造指标增长或 done。

#### 工作台优先使用的只读接口

- `GET /api/v1/seo/workbench/executions?tenant_id=4&site_id=2&page=1&page_size=20`
- `GET /api/v1/seo/workbench/executions/{task_id}?tenant_id=4&site_id=2`
- `GET /api/v1/seo/workbench/executions/{task_id}/report?tenant_id=4&site_id=2`

4/2 是隔离测试示例，不代表生产授权资源。必须验证登录身份、客户归属、SEO 模块启用及站点归属，至少有内容/网站双 view。排名链还需关键词 view；无权限的记录不会计入列表 total。`page_size` 1–100、page 1–10000、按 id 倒序；total 是相同权限与站点范围的全量记录数，items.length 是当前页数量。日期/主题筛选暂未提供，不应在工作台假装已经生效。

```json
{
  "items":[{
    "id":103,"module":"seo","action_type":"site_diagnosis","title":"网站周期诊断与整改",
    "status":"in_progress","created_by":"cockpit","assignee_role":"seo_advisor",
    "params":{
      "kind":"website","phase":"awaiting_site_implementation","waiting_for":"advisor",
      "blocker":"remediation_requires_real_recheck","plan_revision":2,"trigger":"scheduled",
      "pages":{"10":{"state":"observed","snapshot_id":105,"run_id":104,"error":null}},
      "child_task_ids":[106],"attention_overdue":false,"notification_sent":false
    },
    "completion_evidence":null,
    "created_at":"2026-10-07T08:00:00Z","updated_at":"2026-10-07T08:01:00Z",
    "effective_pause":false,"read_only":true,
    "allowed_actions":{"advance":true,"cancel":true,"retry_page_ids":[],"explain_report":false},
    "links":{
      "detail":"/api/v1/seo/workbench/executions/103?tenant_id=4&site_id=2",
      "advance":"/api/v1/seo/workbench/executions/103/advance",
      "cancel":"/api/v1/seo/workbench/executions/103","report":null
    }
  }],
  "total":1,"page":1,"page_size":20,"cycles":{},"read_only":true,
  "as_of":"2026-10-07T08:02:00+00:00"
}
```

示例省略 params 中 UUID、历史和内部派发标识。`params.phase` 是最后一次真实推进的阶段，`status` 是标准任务状态；`effective_pause` 单独反映当前计划暂停，不能用请求时间覆盖事实时间。as_of 是本次读取时间，created_at/updated_at 是任务时间；抓取/排名原始证据保留其已有时间格式；报告 month 使用北京时间自然月。

`cycles` 按网站/监测/报告返回 `sequence/month/task_id/last_checked_at/next_due_at/blocker`，在没有新任务时也能解释缺关键词等阻塞。`next_due_at` 是下一次符合周期的时间，不是保证执行时间。角色不是个人负责人，assignment/trigger 身份不是客户签收。没有实际进度比例时工作台应展示阶段/页面数，不编造百分比。

`allowed_actions` 由服务端当前实名身份、双 edit 权限、active 顾问分配、模块/站点状态、0105 结构、具体任务权限和终态计算；暂停时 advance/retry/explain 为 false，仍可取消未完成任务。前端只能展示能力，写接口每次独立复核。任务详情包含现有内容链，`links.advance` 为内容链返回 SEO-08 的 `/content-workflows/{id}/advance`。

报告列表/详情仅返回 `params.report` 元数据（sha256、month、generated_at、publication_ids、analytics_row_ids、missing、pdf_generated=false），不会在列表塞 HTML。report GET 下载已经保存的 HTML，不重新生成；返回私有 no-store、ETag 和 sandbox CSP。顾问说明在 `params.explanation={text,actor_user_id,at}`，与冻结的原始报告分别读取。数据后来更新也不会静默改写已生成报告。

GET **不会启动采集、生成报告、刷新任务、通知或发布**。401 沿用登录失败；403 为客户/权限/模块拒绝；404 为站点或执行链不属于请求范围、或报告尚未生成。空列表是成功无记录，不用零替代缺失的业务指标。

#### 触发、人工接续与取消

`POST /api/v1/seo/workbench/service-cycles/run`：

```json
{"tenant_id":4,"site_id":2,"kind":"website","expected_revision":2,"request_id":"d3f6a4af-57f9-4352-ab50-05d70cdce053"}
```

kind 为 website/monitoring/report；返回 `{created,task}`。UUID 在租户/站点/类型内幂等，重放返回原任务。新请求版本冲突409，已有未结束任务409 `service_workflow_already_active`，暂停409；缺关键词/超过200词409并明确原因。新功能结构不可用503。写权限沿用 SEO-08 的实名已分配顾问+内容/网站 edit；监测额外关键词 edit。

`POST /api/v1/seo/workbench/executions/{id}/advance`：

```json
{"tenant_id":4,"site_id":2,"retry_page_id":10}
```

retry_page_id 仅用于网站链中实际 failed 的单页，否则409 `page_retry_not_available`。省略可请求按事实推进。报告顾问说明使用：

```json
{"tenant_id":4,"site_id":2,"explanation":"本月统计尚未接入，不能判断流量变化；发布记录另见报告。","report_sha256":"从已读取报告元数据取得的64位哈希"}
```

报告缺失或哈希不匹配409 `report_version_conflict`，空白说明422；示例哈希占位符须替换，不能直接作为可发送请求。无需客户再审批说明。`DELETE /workbench/executions/{id}?tenant_id=&site_id=` 取消未完成执行链；已 done 返回409，保留任务、报告、快照和外部发布事实。

#### 完成证据与新增指标

共享 `{metric_key,value,unit,as_of,trend_7d}` 格式不变，trend_7d 仍按已确认对象格式/历史不足null。新增计数在 `/metrics/definitions` 有口径，接口 `/metrics/snapshot` 可读取：

| metric_key | 口径及用途 |
| --- | --- |
| seo.site.observation_count | 站点已保存页面快照数，含失败；诊断任务还独立要求选定页面都成功观测且整改子任务有真实复检证据，不能只靠计数完成 |
| seo.ranking.observation_count | 站点自有域名百度桌面全国观测总数，含有效的未入榜观测；待办还要求每个问题有创建后新鲜观测，下降须恢复 |
| seo.reports.prepared_count | 实际生成并持久化带SHA256的HTML报告数，不按人工勾选、客户签收或任务done计数 |

报告超过200条当月发布记录时停在 `report_publication_limit_200`，不截断后冒充完整月报。完成统一保留真实 source 引用、before/after/change_abs/as_of；统计缺失、截图未内嵌、单篇点击不可归因仍在报告中明确。完成服务动作不等于 SEO 效果增长。

#### 当前准确源码定位（SEO-09）

| 工作台所需能力 | 源码 |
| --- | --- |
| 列表与分页、权限范围 | `app/api/seo_service_workflows.py:list_executions`（93行） |
| 详情、允许动作、链接、报告HTML排除 | 同文件 `projection`（67行）、`get_execution`（111行） |
| 冻结报告只读下载 | 同文件 `read_report`（119行） |
| 触发/推进/取消 | 同文件 `trigger_service_cycle`、`advance_execution`、`cancel_execution` |
| SEO-08 自动/人工边界 | `app/seo_content_workflow.py:reserve_content_workflow`（69行）、`advance_content_workflow`（120行） |
| 网站实际派发与快照/整改建单 | `app/seo_service_workflows.py:execute_diagnosis_page` |
| 排名异常条件与任务接续 | 同文件 `ranking_issues`、`advance_service_workflow` |
| 月报冻结/缺数说明 | 同文件 `prepare_report`，复用 `app/seo_monthly_report.py:build_report_context/render_report_html` |
| 周期配置及能力注册 | `app/api/seo.py:SeoServicePlanUpdate/_service_plan_payload/update_seo_service_plan`；`app/seo_scheduler.py` |

函数名为稳定定位依据，后续编辑可能移动行号。工作台应对照本地提交实现，不把未部署接口称为生产可用。

### SEO-10：默认关闭的自动草稿与明确手动触发资格

仅本地实现，依赖已审核并另行批准执行的0105结构；本批无新迁移。以下ID均为**隔离测试示例**，不是获准的生产资源。所有GET只读取，不能启动生成、采集或发布。

服务计划 GET/PUT 路径不变。PUT 新增字段，省略时保留原值：

```json
{
  "tenant_id": 4,
  "site_id": 2,
  "expected_revision": 1,
  "optimization_directions": ["依据已核对的资料回答选型问题"],
  "content_topics": ["选型依据"],
  "content_ai_enabled": true,
  "content_ai_fact_ids": [30],
  "content_ai_keyword_ids": [20]
}
```

- `content_ai_enabled` 默认false；顾问显式开启才记录服务端 `content_ai_authorized_by/content_ai_authorized_at`。前端不能提交这两个身份字段。运行时必须仍是当前站点active分配、启用账号、正确客户范围，并有内容/网站edit及关键词view权限。
- 资料复用 `GET /api/v1/seo/qa/facts?tenant_id=&site_id=`，最多20条：同租户同站点、active、未过期、正文和source_name非空，总快照不超过5万字符。source_url可空，适用于人工录入资料；这不代表系统已经替顾问核实资料真伪。关键词最多5个，必须精确归属当前站点且active，不接受site_id=null的租户级关键词。
- 已开启时更换资料/关键词必须同时显式传 `content_ai_enabled:true`，否则409 `ai_draft_explicit_enable_required`。关闭可单独false；无关键词权限仍可关闭。无资料/过期/不匹配返回409稳定code，配置不落库。
- 开启适用于当前尚无正文的内容链和后续新链；已有正文、承接页整改稿、已经内审/发布的稿件不自动覆盖。既有每分钟内容调度接入，一条内容链最多领取一次自动生成。
- 复用 `POST /api/v1/seo/content-ai/assist` 的服务函数、日额度和SeoAiOperation，不另外开放自动生成endpoint。SEO-11 起自动草稿显式锁定 DeepSeek，见下文；原公共 assist 的默认路由保持原样。生成内容必须保留所选资料的`[F编号]`，未知引用、无引用、待补充/待核验、无效长度交人工；这些程序检查不替代事实质量审核。
- 成功只保存 `status=drafting`、稿件版本+1和来源快照，阶段为`awaiting_internal_review`。后续仍用现有编辑、submit-review、review、准确版本确认、分平台发布与页面证据接口；不自动审核、代确认、选渠道或发布。
- 领取状态先提交，网络调用不持有任务/站点锁。重启只读对应operation的已持久化结果，成功可回收；running继续等待，退款/失败/超时交顾问，不再次向供应商请求。既有assist内部最多一次格式/关键词纠正仍保留，属于同一次日额度操作，不是无限重试。
- 写回前复核计划revision、明确授权者、账号与分配、资料/关键词快照、稿件hash/版本和任务状态。取消、暂停、禁用、撤权、改稿、改资料后不覆盖稿件。已完成供应商生成但未能采纳的结果仍按既有实际调用计数，不伪称退款；供应商失败走已有退款机制。

服务计划GET新增：

```json
{
  "content_ai_policy": {
    "can_configure": true,
    "can_disable": true,
    "configure_denial_reason": null,
    "provider_configured": false,
    "output_status": "drafting",
    "automatic_review": false,
    "automatic_confirmation": false,
    "automatic_publication": false,
    "attempts_per_workflow": 1,
    "failure_handling": "advisor_uses_existing_editor_or_assist"
  },
  "trigger_actions": {
    "content": {
      "allowed": true,
      "reason": null,
      "method": "POST",
      "endpoint": "/api/v1/seo/workbench/service-plan/run",
      "kind": null,
      "expected_revision": 1,
      "request_id_format": "uuid",
      "meaning": "new_execution_only"
    }
  }
}
```

示例省略未变化字段和其他kind；真实 `trigger_actions` 总是包含 `content/website/monitoring/report` 四项，同时在GET `/workbench/executions`顶层提供。后三项endpoint为`/api/v1/seo/workbench/service-cycles/run`并携带对应kind。请求使用已展示的tenant/site、expected_revision和新UUID；未知响应重试保持同一UUID，不能另造UUID绕过正在执行的链。

触发能力与`allowed_actions.update_service_plan`独立。按写端要求复核0105、实名、双edit、当前站点分配、模块/站点启用、服务计划暂停与revision、同类型已有活动链；内容需选题/方向，监测额外需关键词edit及1–200个启用词。常见reason为`authenticated_user_required`、`active_site_advisor_assignment_required`、`site_or_module_not_operational`、`service_plan_paused`、`service_plan_required`、`content_workflow_already_active`、`service_workflow_already_active`、`keyword_edit_permission_required`、`keyword_inventory_required`、`monitoring_keyword_limit_200`。allowed只表示可新建执行链，不保证资料齐全、采集成功或有异常；网站无既有页面等阻塞仍在执行任务中返回。写端在行锁内再次校验，不能以GET资格作为永久授权。

内容任务 `params.ai_draft` 返回 `status=claimed/succeeded/needs_attention`、`request_id`、`claimed_at`、`authorized_by`、`plan_revision`、`source_version`与输入摘要。成功另外返回`operation_id/generated_by=system/saved_version/fact_snapshots/finished_at`；人工处理时返回稳定`reason/quality_checks`。阶段`ai_draft_in_progress`由系统等待，`ai_draft_needs_attention`由顾问处理。资料过期、额度不足、供应商未配置、结果未知、输入变化均不标成done。没有自动重试按钮，失败任务可通过现有编辑器/assist人工制稿并正常继续。

### SEO-11：自动草稿供应商与目标完成证据

仍为本地实现，不新增迁移或公开生成接口；内容自动链继续依赖0105。服务计划 GET/PUT 新增 `content_ai_provider`（仅 `deepseek`，默认值同此）和 `content_ai_model`（`deepseek-chat | deepseek-reasoner`，默认 `deepseek-chat`）。省略保留原值；自动草稿开启期间修改模型也必须显式携带 `content_ai_enabled:true`，否则409 `ai_draft_explicit_enable_required`。默认模型不读取全局 DashScope 模型配置。

自动草稿及其一次格式纠正都显式传入 DeepSeek key、官方 HTTPS 地址和所选模型。仅允许 `https://api.deepseek.com` 的空路径或 `/v1`（可显式443端口）；其他网关不会被标成已确认的 DeepSeek。缺 DeepSeek 配置、仅有 DashScope 配置或路由无效时，任务转人工且不发请求；供应商失败走既有退款机制，不回退其他供应商。GET `content_ai_policy` 增加 `provider=deepseek`、`supported_providers=[deepseek]`、`supported_models`、`fallback_allowed=false` 和 `provider_unavailable_reason`，读取不调用供应商。开启计划可保存但不等于供应商可用。

任务 `params.ai_draft.generation_route` 冻结非敏感的 `provider/model/base_url` 并参与幂等摘要；成功额外保存 `provider`、请求的 `model` 和响应报告的 `response_model`。后者缺失时为null，不能拿请求模型充当已核实的供应商返回版本。返回其他供应商模型时拒绝采纳；旧缓存结果没有供应商来源证据时转人工，不重新请求生成。主要reason：`ai_draft_deepseek_not_configured`、`ai_draft_deepseek_route_invalid`、`ai_draft_deepseek_route_changed`、`ai_draft_provider_evidence_missing`、`ai_draft_provider_model_mismatch`。不返回或保存key。原公共assist的默认路由、请求摘要与响应格式保持兼容。

`content_delivery` 与 `page_remediation` 的新完成证据采用限定任务对象的观察计数，避免站点总量把正确交付卡住：

| `metric_key` | 统计口径 |
| --- | --- |
| `seo.content.target_delivery_verified_count` | 限定本任务内容、准确版本和选定发布记录；任务创建后发布且取得发布后自动页面证据计1，否则0，不表示搜索效果增长。 |
| `seo.site.target_clean_recheck_count` | 限定本任务目标页面；任务创建后取得与当前页面对应的成功、无问题重新抓取快照计1，否则0，不表示全站健康页面净增长。 |

以下为任务完成证据的结构示例，ID仅作隔离示例：

```json
{
  "metric_key": "seo.site.target_clean_recheck_count",
  "metric_definition": "限定本任务目标页面；任务创建后取得与当前页面对应的成功、无问题重新抓取快照计1，否则计0，不表示全站健康页面净增长。",
  "unit": "count",
  "scope": {"task_id": 900, "tenant_id": 4, "site_id": 2, "page_id": 10},
  "before": 0,
  "after": 1,
  "change_abs": 1,
  "as_of": "2026-10-07T08:00:00+00:00",
  "completion_basis": "target_object_evidence",
  "source": {
    "page_id": 10,
    "url": "https://example.com/page/10",
    "status": "healthy",
    "checked_at": "2026-10-07T07:59:00+00:00",
    "snapshot_id": 91,
    "crawl_run_id": 92,
    "http_status": 200,
    "audit_score": 100,
    "issue_codes": [],
    "source_issue_codes": ["h1_missing"],
    "meaning": "target_page_rechecked_clean"
  },
  "meaning": "target_page_rechecked_clean",
  "effect_context": {
    "metric_key": "seo.site.healthy_page_count",
    "scope": "site",
    "before": 2,
    "after": 1,
    "change_abs": -1,
    "snapshot_url": "/api/v1/seo/metrics/snapshot?tenant_id=4&site_id=2"
  },
  "seo_effect": "not_evaluated"
}
```

0→1指任务创建后新证据的获得，不代表未知的历史页面质量从差变好。页面必须核对最新快照（不能筛掉失败后拿旧成功顶替）、当前页面时间及真实完成的抓取run；同一时钟刻度只有任务冻结的旧快照ID和新的更大快照ID可证明先后时才接受。旧任务没有快照基线时严格要求复检时间晚于创建。站点总量移到 `effect_context`，允许持平、下降或旧基线未知；内容证据还在scope注明 `content_id/publication_id/source_version`，source继续含准确确认、自动capture和内容摘要。

兼容要求：不改共享任务最小字段，也不改 `/metrics/snapshot`、`trend_7d` 或既有站点指标定义；上述两个key只在任务对象的完成证据内使用。历史已done的证据原样保留，未完成旧任务按新条件核实，旧baseline仅供效果背景。消费方按 `completion_basis` 和 `scope` 识别对象指标，不能把对象0/1汇总当成站点统计，也不能再固定假设completion_evidence.metric_key等于baseline.metric_key。旧消费方若依赖该假设需先适配；无数据库回填或DDL。其他任务种类的完成条件不在本批修改范围。

### UI-09：人工发布证据的准确版本前提与旧入口兼容

`POST /api/v1/seo/content-distribution/publications/manual` 新建人工登记必须携带 `source_version` 和 `payload_hash`，从已展示稿件的`version_count/payload_hash`读取；内容列表新增payload_hash，delivery原有payload_hash也可用。保存前临时重新读最新版本然后静默替换预期值，不符合本约定。

```json
{
  "tenant_id": 4,
  "site_id": 2,
  "content_id": 101,
  "source_version": 1,
  "payload_hash": "替换为读取到的64位小写SHA256",
  "platform_name": "实际平台名称",
  "page_url": "https://example.com/已实际发布地址"
}
```

哈希示例是占位符不可直接发送。服务端先验证租户/权限/站点，再锁住稿件并刷新，比较版本与hash、审核状态及0105准确确认，随后同事务登记。改稿后409 `content_version_conflict`，确认不满足409 `content_confirmation_required`；缺少任一预期字段428 `content_version_precondition_required`，非法hash422，撤掉内容edit返回403。不会替客户向平台发布。

兼容策略为明确拒绝缺前置条件的旧人工登记调用，0104也不静默绑定服务端最新版本。本仓SEO分发页已携带选择时冻结的版本/hash；旧客户端需要升级，否则428。0104仍沿用原审核门禁，不制造准确确认记录；0105才启用客户/顾问准确确认。发布记录提交后原有页面核验排队副作用保留，GET没有这一副作用。

发布列表每条新增：

```json
{
  "allowed_actions": {"complete": true},
  "action_denial_reasons": {"complete": null},
  "action_requirements": {
    "complete": {
      "endpoint": "/api/v1/seo/content-distribution/publications/91/complete",
      "method": "POST",
      "source_version": 1,
      "page_url_required": true,
      "meaning": "record_existing_publication_only"
    }
  }
}
```

complete只针对`manual_required/failed/preparing`、准确当前版本及有效确认；`publishing`不允许。拒绝原因包括`content_edit_permission_required/content_missing_or_out_of_scope/content_version_conflict/publication_status_not_completable/question_distribution_required/content_confirmation_pending/content_confirmation_stale/content_confirmation_rejected`。已published记录的“再次提交同URL”属于写端幂等恢复，不是新的允许动作；UI不展示再次完成按钮。既有complete仍接受老调用省略source_version（以持久化发布记录绑定版本核对当前稿件），工作台必须按投影携带source_version。回填写端也已加稿件行锁，重查准确确认，跨租户和站点仍拒绝。

旧入口专项核查：当前本地 `SeoContentEditorView.vue` 已按content_id/site读取、携带version_count保存且只更新当前编辑的正文分支；不能拿e494旧宿主行为代替本地现状。`PATCH /content-assets/{id}` 从草稿/ready跳到published及受保护稿件写page_url均返回409，0104/0105都如此。0105新加草稿保存的version_count必填前提，省略428，旧版本409；0104仍允许旧草稿调用缺版本，但不能绕过审核/发布流程。未修改SEM前端，也未部署旧宿主兼容入口。

### PostgreSQL 定向运行包（总控已完成六个并发场景验收）

文件：`tests/test_seo_workflow_postgres.py`。仅接受`postgresql+asyncpg`、host为`127.0.0.1/localhost/::1`、数据库名**严格等于**`seo_workflow_test`且无URL查询参数；另需显式设置`SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE=yes`。不回退应用DATABASE_URL、不加载迁移、不连接生产。每例创建随机schema及最小模型表，最终只清理该随机schema；并非迁移/外键全量验收。

运行条件：已有隔离PostgreSQL、专用空测试库、仅该库CREATE schema权限；现有项目Python环境有pytest/SQLAlchemy/asyncpg及正常应用导入依赖。若需要安装数据库或创建账号/库，由环境负责人另行安排，本批没有安装。完整假配置参考既有测试；下例在**测试进程**设置，不使用生产.env：

```powershell
$env:SEO_WORKFLOW_TEST_DATABASE_URL='postgresql+asyncpg://<本机测试用户>:<测试密码>@127.0.0.1:55432/seo_workflow_test'
$env:SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE='yes'
$env:DATABASE_URL='postgresql+asyncpg://unused:unused@127.0.0.1:1/unused'
$env:SECRET_KEY='isolated-test-secret-isolated-test'
$env:ADMIN_API_KEY='isolated-test-key'
$env:DEEPSEEK_API_KEY=''
$env:DASHSCOPE_API_KEY=''
$env:BAIDU_APP_ID='test'
$env:BAIDU_SECRET_KEY='test'
$env:BAIDU_DEFAULT_USERNAME='test'
$env:BAIDU_DEFAULT_UCID='1'
$env:BAIDU_SELF_ACCESS_TOKEN='test'
$env:BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z'
$env:CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
python -m pytest tests/test_seo_workflow_postgres.py -q
```

六个数据库用例：相同/不同UUID并发预留、并发周期去重、等待期间顾问撤销、并发AI领取单次额度、并发改稿后人工登记旧版本拒绝。四个地址防护用例无需数据库。SEO-10/11开发回归时未找到隔离运行环境，六项数据库用例曾为skipped；该历史记录保留。

2026-10-07总控已在本机专用 PostgreSQL 16.15 固定提交 `67975f32bb1175ba21c9f7dabd6b619b24306860`，实际运行本文件全部 **10 passed、0 skipped**。代码与测试哈希前后稳定，测试schema/用户表前后均为空，未调用真实供应商或生产。验收记录为 `D:/SNIPERS国内版/梳理-2026-10/项目筹备-20261007/SEO_POSTGRES_ACCEPTANCE.md` 及同目录脱敏 `SEO_POSTGRES_ACCEPTANCE_RESULT.json`。

本运行包创建最小模型表并省略外键，证明范围限这六个并发场景和四个连接防护，不代表完整0105迁移、全部外键/约束、压力或真实供应商/线上端到端验收。其他数据库测试及真实渲染依赖仍按各自记录补验；不重复运行已通过这轮，除非相关代码变动或出现新问题。

## UI13 现有列表与维护入口（2026-10-08定向核对）

本节仅给现有接口接线依据，不新增架构或数据库。实际本机后端 `http://127.0.0.1:8031`、应用代码 `f97be780`、数据库0105；后续文档提交不改变运行代码。示例tenant/site=1/1仅为本轮合成资源，不是生产客户授权。请求使用既有真实登录JWT，不在文档传凭证。以下相对路径统一加 `/api/v1/seo`。

### 只读数据页

| 用途 | GET路径与可用参数 | 返回和限制 |
| --- | --- | --- |
| 排名关键词 | `/keywords?tenant_id=1&site_id=1&engine=baidu&device=desktop&page=1&page_size=20`；另可q/priority/intent/status，status默认active，空值表示不过滤 | `{items,total,page,page_size,engine,stats}`；page≥1，page_size 1–200。每条含keyword/latest_rank/rank_delta/rank_url/rank_checked_at/rank_source/rank_is_stale/last_observed_rank。无观测或过期不可显示成排名0；列表没有region参数，不能标为固定“全国”的同口径排名比较 |
| 单词历史 | `/keywords/1?tenant_id=1&engine=baidu&device=desktop&region=全国&days=90` | `{keyword,rank_history,competitor_history,engine,region,optimization_task,diagnoses}`；days 1–366，无分页。仅tenant参数，site由关键词归属决定；须从已限定站点的列表ID下钻，不要假设传site_id会额外过滤 |
| 页面检查清单 | `/site-pages?tenant_id=1&site_id=1&page=1&page_size=20`；另可page_id/q/status/issue_code | `{items,total,page,page_size,stats}`；page_size 1–200。条目含url/http_status/audit_score/diagnostic/issue_codes/last_error/last_checked_at/indexable/status。indexable只表示允许索引；未检查、抓取失败、发现问题不能合并为“通过” |
| 单页依据 | `/site-pages/1/detail?tenant_id=1` | `{page,issue_details,internal_links,latest_snapshot,previous_snapshot,comparison,read_only}`；无分页，最多两条快照。site由页面决定，和单词详情相同须从当前站点列表下钻；读取不触发audit |
| 分页发布与页面依据（数据页首选） | `/workbench/publication-page-evidence?tenant_id=1&site_id=1&page=1&page_size=20`；另可content_id/publication_id | `{items,total,total_pages,page,page_size,read_at,coverage,source,read_only}`；page_size 1–100。每条为`{content,publication,latest_attempt,page_association,page_check}`，发布地址字段为`publication.public_url`。tenant/site必填；无status/平台/日期/主题筛选。投影没有source_version或操作能力，执行前另取发布详情列表及content delivery |
| 原发布操作列表 | `/content-distribution/publications?tenant_id=1&site_id=1&content_id=2`；另可status | `{items,total,status_counts}`，**无服务端分页**，不要传page后冒充已分页。条目含source_version/page_url/last_error/allowed_actions/action_denial_reasons/action_requirements，用于选定稿件的回填/任务接续 |
| 发布尝试 | `/content-distribution/publications/1/attempts?tenant_id=1&site_id=1` | `{items}`，无分页/total。为空不等于发布失败；人工直接登记可能没有attempt。投影只给latest_attempt，完整尝试按本接口读取 |

`total`为当前筛选范围记录总数，`items.length`为当前返回量；关键词`stats`主要按同站点active词统计，不跟随q/priority/intent筛选，其中monitored_engines来自当前页词的观测；页面stats按整个站点，不随列表问题/状态筛选。投影coverage.association_counts只统计当前页；页面候选清单最多扫描5000、每条候选摘要最多5，coverage.partial必须提示，不当完整全站统计。排名列表region/device元数据可能来自另一个引擎的最新观测；需要精确范围时使用指定engine/device/region的单词历史。

上述GET只有读取和计算，不启动采集、AI或发布。保留后端输出时间偏移；rank_checked_at、published_at、last_checked_at为UTC，数据库生成created_at/updated_at按既有数据库墙钟序列化，不能删除时区重算。read_at只表示读取时间。未提供日期过滤的入口不要展示已生效的日期筛选。

权限按登录身份的tenant、SEO模块、资源归属及功能权限校验：关键词seo.keywords:view，页面seo.site:view，发布/资料seo.content:view；发布页面投影同时要求seo.content:view和seo.site:view。详情的tenant与实体必须匹配；站点列表应始终显式带site_id。401重新登录；403权限/模块拒绝；404资源不属于范围；400非法枚举；422参数校验失败。不得用403/500的兜底空数组冒充成功无数据。

### 顾问资料和关键词维护复用范围

- `GET /qa/facts?tenant_id=1&site_id=1`返回**数组**，按id倒序最多500条，无分页、q、total或截断标志。字段id/title/statement/source_name/source_url/expires_at/status/version/current。current表示active且未过期，不是独立事实核实。500条上限不能当全量数量。
- `POST /qa/facts` JSON必填tenant_id/site_id/title/statement/source_name，选填source_url/expires_at/status(active或retired)。`PATCH /qa/facts/{id}`是**完整资料表单+version**，不是任意局部patch；必填tenant_id/site_id/title/statement/source_name/version，省略选填字段会回默认值。应先读原值后提交完整表单；过期时间非空必须带时区；version不符409。无删除接口，停用用retired。
- `POST /keywords` JSON必填tenant_id/site_id/keyword；选填cluster/intent/monthly_volume/difficulty/priority/landing_page/status/notes。priority=P0–P3，status=active/paused/archived。`PATCH /keywords/{id}?tenant_id=1`支持除keyword本身外这些维护字段，按exclude_unset局部更新；**不能重命名关键词、没有乐观锁version**，不可在UI承诺冲突保护。归档用status=archived；跨站迁移有引用时409。
- `POST /keywords/import`支持tenant_id/site_id/items，1–500条，items使用KeywordCreate结构；本轮不做批量导入验收。以上写操作分别要求seo.content:edit、seo.keywords:edit。它们是既有模块权限接口，不新增个人负责人/客户确认架构。客户UI应隐藏顾问维护配置，服务端仍按权限拒绝越权写入。
- UI13明确维护需求后，本机runner已新增放行`POST /api/v1/seo/qa/facts`、`PATCH /api/v1/seo/qa/facts/{正整数id}`、`PATCH /api/v1/seo/keywords/{正整数id}`；后续按空库入口需求补充`POST /api/v1/seo/keywords`，共四类路径。查询参数与请求体仍由真实权限/模块/tenant/site/版本校验处理；前端关键词编辑仅使用priority和landing_page，新增表单仅使用tenant_id/site_id/keyword/priority/landing_page（复用既有API，本机runner按方法/路径放行，不改变API原有字段模型）。关键词/资料导入、相邻写接口均未开放，外部请求仍禁止。这是专用本机测试范围，不修改生产配置。

### 客户待确认口径和验证范围

客户待办读取 `/workbench/content-assets/{id}/delivery?tenant_id=1&site_id=1` 的`workflow_status`、`confirmation.status`和`allowed_actions`，不要把content.status=ready直接计入客户待确认。tenant_id和site_id均必填，缺site_id返回422。ready+approved→approved_waiting_publication；ready+rejected→awaiting_content_revision；ready+pending/stale→awaiting_customer_confirmation；结构未就绪→confirmation_unavailable。按钮还须对应allowed_actions=true。交付内容、各渠道published、页面核验、任务done和搜索效果分别展示。

本轮在真实本机API用advisor/customer两个账号各读取上表九类入口（含delivery、资料）均200，18次成功GET；两身份对投影外租户均403、错站点均404，另4次拒绝符合预期。仅登录使用POST，没有业务写入。记录在受限本机 `C:/Users/Administrator/.secrets/seo12-local/ui13-readonly-smoke.json`，不含凭证。合成库只有1词/1页/1条发布，无真实排名快照；空历史和未关联页面不构成真实排名/抓取验证。

本轮未新增运行代码，未做维护写测、多页大数据边界、全组合筛选、真实搜索源或抓取测试；旧有测试存在不等于这些UI13场景本轮已验收。UI12完整状态和500修复/93项回归另见 `SEO_LOCAL_ACCEPTANCE.md`。待前端明确缺失契约后再小范围补齐。

UI13后续维护定向验证：本机runner放行后，37项离线防护测试通过；真实JWT/API的15次检查通过，包括资料新增/完整编辑、旧version409、客户写入403、外租户403、错误站点写入409（先被operational-site门禁拒绝）、关键词priority/landing_page保存及恢复、导入仍403。首次探针错误预期错站点为404，实际在资料创建前即409；核对现有门禁后修正测试预期，没有改业务权限或重放已成功写入。新增合成资料id=2已retired/current=false；原资料id=1保持，关键词id=1的两个业务字段已恢复原值（维护更新时间正常更新）。证据：`C:/Users/Administrator/.secrets/seo12-local/ui13-maintenance-smoke.json`。这不是UI13浏览器表单验收，前端可另新增合成资料做真实交互测试；无需复用或重新激活SEO探针资料。

新增关键词放行后的增量验证：38项防护测试通过，6项真实API检查通过（顾问五字段新增200、客户/外租户403、同站点重复关键词409、仅新探针归档200、导入仍403）。新探针keyword id=2已archived，原关键词1未改，不占active清单。记录：`C:/Users/Administrator/.secrets/seo12-local/ui13-keyword-create-smoke.json`。未重跑已通过的UI12流程或全量审查。

## UI14 图片与多页夹具交付（2026-10-08）

### 图片接法

稿件不存在独立image列表字段。列表给draft/humanized_content，delivery给`content.body = humanized_content or draft or ""`；正文可能HTML或Markdown。前端按正文顺序保留图片与alt，正文先做安全解析/清洗。不能由source_page_id或page_url推断正文图片附件，截图也不是自动的稿件图片库。

现有鉴权图片能力只覆盖SEO截图：

1. `GET /api/v1/seo/site/page-captures/{id}?tenant_id=1`，真实JWT，需seo.site:view（同时还有路由通用权限检查），校验租户与截图所属站点。元数据包含id/tenant_id/site_id/relation_type/relation_id/source_url/status/error_code/source/content_type/image_width/image_height/sha256/warnings/captured_at/uploaded_by/uploaded_at等，**不返回storage_key，也没有通用代理url参数**。
2. UI先核对metadata.id/tenant_id/site_id都与当前上下文一致，再使用`GET /api/v1/seo/site/page-captures/{id}/image?tenant_id=1`获取Blob。source_url是被记录页面地址，不是图片下载地址；site_id不是图片路由参数，不应假设服务端使用额外site_id过滤。需前端复核元数据站点；后端校验截图及其站点属于tenant。
3. 成功Content-Type为image/png/jpeg/webp，Cache-Control=`private, no-store`、X-Content-Type-Options=`nosniff`。非成功截图404/image_not_ready，文件丢失或签名不符404/image_not_found。401须登录，403无权，外租户/不存在按实际权限层拒绝。
4. host transport携带令牌仅用于上述固定同源相对路径，严格限制正整数ID和当前tenant；拒绝任意主机、`//host`、用户信息、重定向到外域及任意代理参数。HTTPS正文外链只可在不带系统Authorization/Cookie、no-referrer且允许CORS时读取；失败显示原alt与失败说明，不转后端任意URL代理。Blob URL使用结束及时revoke。
5. 本机CORS允许`http://127.0.0.1:<port>`或localhost端口，允许Authorization；生产CORS未改。本机目录固定在受限`seo12-local/ui14-media`，与生产截图目录隔离。注意旧截图GET在主数据源上会把超时pending/running转failed，是已有状态维护，不启动抓取；不能把它称为绝对无写副作用接口。本轮只有终态夹具，不发生此更新。

真实可验：capture1=成功，capture2=失败，二者tenant/site=1/1、relation_type=site_page、relation_id=2，source=manual，warnings包含synthetic=true、fixture_batch=UI14-20261008、not_publication_evidence=true。图片地址分别`/api/v1/seo/site/page-captures/1/image?tenant_id=1`和`/api/v1/seo/site/page-captures/2/image?tenant_id=1`。64位SHA256及尺寸640×240见本机清单；这是一张带英文合成标记的绘制PNG，不是真实网页截图。稿件4–63正文均依次含这两张HTML img；Markdown解析应由前端夹具另测，不声称本批已提供Markdown正文。

### 多页对象与口径

固定库seo_workflow_test、tenant/site=1/1，标签`UI14-20261008`。只由显式本机脚本 `scripts/seo_local_ui14_seed.py`在一个事务里追加；同批次有回执则不重放，无回执却发现标签则停止。全程自动化/AI/抓取/真实发布关闭，不执行任务；runner按清单拒绝UI14任务的content-workflows/{id}/advance，原task1不在拦截名单。已有六个相关表全部旧行SHA256保持一致，未修改UI12/13对象；没有迁移或身份变更。

| 类型 | 新增ID/数量 | 新增状态预期 |
| --- | --- | --- |
| 稿件 | 4–63，共60 | planned8/drafting8/review8/ready29/archived7；ready进一步pending8/approved7/rejected7/stale7。确认记录明确注明seeded，不是客户真实确认 |
| 任务 | 5–49，共45 | open15/in_progress15/cancelled15，均content_delivery，phase=fixture_not_executed、blocker=synthetic_fixture、完成证据null。只能用于浏览，不执行推进 |
| 关键词 | 5–49，共45 | active15/paused15/archived15，P0–P3混合；无排名快照，不代表搜索观测 |
| 页面/图片 | 新页面2；截图1、2 | 页面pending；人工合成图片成功/失败各1，不与publication1关联 |

稿件列表带`q=UI14-20261008&page_size=20`，total=60、3页均20条，排序updated_at desc/id desc；待确认散布在不同页，ready筛选不等于待确认筛选。关键词带同q和`status=`才能看到45条，page_size=25为25/20，排序priority asc/id desc；默认status=active仅15条本批词。执行链`/workbench/executions?tenant_id=1&site_id=1&page_size=20`按id desc，当前全范围total=46、页20/20/6（45本批+原1条）；没有q/status筛选。通用`/tasks`是before_id游标+limit，不是page/page_size，返回数组且无total；勿混用两种分页。

对象清单：`C:/Users/Administrator/.secrets/seo12-local/ui14-fixtures.json`；双身份API记录`ui14-readonly-smoke.json`。40项本机防护/计划测试通过；31项真实API结果检查通过（涉及元数据/图片、未登录/外租户、分页和四种确认状态），未做全套审查或UI浏览器验收。实际GET没有采集或生成，未执行任务。最初delivery探针漏site_id得到422，补齐必填参数后通过，已修正文档短例。

### 站内沟通：现状与最小后续方案（未实现、无新迁移）

当前`PATCH /api/v1/seo/tasks/{id}`支持`{tenant_id,site_id,note}`追加`params.followups[{note,actor,at}]`，最多100条，需任务对应功能edit、任务未done/cancelled；客户view不能回复，无未读/送达/参与人机制。可以作为顾问任务跟进，不能冒充客户—顾问会话。

`assistant_messages`及`/api/v1/assistant/chat/history`是按tenant+user隔离的私有AI对话，chat会调用AI，**不复用、不开放为人工消息**。当前SEO分支未找到跨客户/顾问人工会话表或已读接口，UI应显示“沟通未接入”，不假发送。

建议最小三表（待共享数据库负责人评审与revision分配）：会话`tenant_id/site_id/content_id`严格范围；参与人表记录实名user_id、customer/advisor角色及read_cursor；消息表append-only存text、sender_user_id、created_at、client_request_id（会话内幂等唯一）、可选当前稿件版本引用。复用现有用户/站点/稿件外键，不使用角色名冒充发送人，不把消息视为稿件确认或任务完成证据。

拟议接口（尚不存在）：列当前稿件会话/游标分页消息、追加文本消息、标记本人已读。每次读/写均核对SEO模块、tenant/site/content归属和参与人；客户必须绑定当前租户且在参与列表，顾问必须仍有该站点active assignment及内容权限；撤权后即时拒绝读写，历史消息保留供仍获授权的参与人审计，换顾问需显式加入参与人。服务端生成sender/time，限制长度、纯文本渲染、UUID幂等，不支持HTML/附件/外部通知。

暂不注册或执行生产migration，不沿用别模块候选revision。批准后先本地迁移/租户隔离/撤权/并发重发与分页测试，再接UI；本批只交此方案，不新增通信架构或微信短信能力。

## UI15 人工文本会话契约（本机后端与浏览器分阶段验收完成）

前缀 `P=/api/v1/seo/workbench/content-assets/{content_id}/conversation`。tenant_id/site_id/content_id三者严格定位稿件；使用现有JWT，无AI、外部通知、HTML执行或附件。内部审核、客户确认和发布接口独立不变。

| 请求 | 参数/体 | 返回 |
| --- | --- | --- |
| GET P | query tenant_id、site_id | `{scope:{tenant_id,site_id,content_id},conversation_id:null或整数,actor:{id,name,kind},allowed_actions:{read:true,send:true,mark_read:true},read_state:{last_read_message_id:0或整数,latest_message_id:null或整数,unread_count:整数},semantics:"human_messages_only"}`；无会话也200，不创建任何行 |
| GET P/messages | query tenant_id、site_id、limit=20(1–100)、before_id可选正整数 | `{conversation_id,items:[message],has_more,next_before_id:null或最小返回id,read_state}`；初始取最新limit条，当前页按id升序显示；before_id向旧历史翻页，严格id<before_id。GET不标已读 |
| POST P/messages | JSON `{tenant_id,site_id,request_id:UUID,body:1–4000字符非空文本}` | HTTP200 `{message,replayed:false或true}`；同会话同sender同request_id同文本返回原消息；换文本复用键409/message_request_conflict。不接受客户端sender/time |
| POST P/read | JSON `{tenant_id,site_id,last_read_message_id:正整数}` | `{conversation_id,read_state}`；只能推进本人游标到当前会话已有消息，单调不回退，不能使用其他会话/未来ID。发送不自动标已读 |

message固定字段：`{id,conversation_id,body,sender:{id,name,kind:"customer"或"advisor"},created_at:"UTC ISO Z"}`。sender姓名来自服务端当前真实用户显示名/用户名快照。unread_count只计本人游标之后的他人消息，消息ID全局单调但可有空隙；所有时间由服务端生成。面板展开实际呈现后，用户显式标记已读才调用read；失败保留同request_id和输入，修改文本应生成新UUID；切租户/站点/稿件、登出或403清理敏感内容。

首期参与资格：实名账号有seo.content查看权限；具有`seo.content:edit`或任何历史顾问分配记录的身份一律进入顾问门禁，必须同时有content edit及该站点active advisor assignment，作为advisor；其余账号必须绑定当前tenant，作为customer。顾问降级为view仍拒绝，不能退化成customer。这使测试customer(user1)可回复、advisor(user2)撤权后不可退化成customer绕过拒绝；未分配编辑身份、API Key、跨客户、停用用户均拒绝。角色名称不作为授权依据。participant表仅记录发送身份参与及个人已读游标，不是静态ACL；具备动态资格的新成员可读会话，但GET不创建参与记录。已有参与记录不会绕过实时权限复核。站点停用/模块不可用时沿现有门禁拒绝写入。

错误为HTTPException detail对象：`{code,message}`（外围既有鉴权可能仍返回字符串detail）。401未登录；403 conversation_forbidden或既有权限拒绝；404 conversation_content_not_found / conversation_cursor_not_found；409 message_request_conflict；422字段/长度/UUID；503 conversation_schema_unavailable（尚未0106）。403时不渲染旧消息，不把失败空列表显示为会话正常。无会话时latest_message_id=null、last_read_message_id=0、unread_count=0。

拟定唯一迁移 `0106_seo_content_messages`，down_revision=`0105_seo_content_confirmations`。已检查本机迁移目录、全部本地Git引用历史和相邻worktrees未发现0106；不代表生产已批准。只在固定本机seo_workflow_test执行，保留旧数据；新会话、参与游标和消息三表，消息只追加，按会话串行分配/提交避免分页遗漏，幂等唯一键兜底。生产迁移/部署仍须单独安排。
