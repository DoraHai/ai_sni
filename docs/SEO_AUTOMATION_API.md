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

任务完成仍使用 `PATCH /tasks/{task_id}` 的 `status=done`，但必须满足：目标页面在任务创建后重新检查、状态为 `healthy` 或 `verified`、问题码为空，并且站点 `seo.site.healthy_page_count` 相比任务基线真实增加。完成证据返回页面 ID、复检时间、HTTP 状态、审计分数和空问题列表。人工修改网站或把任务手工打勾都不能直接完成任务。

指标快照新增：

```json
{
  "metric_key": "seo.site.healthy_page_count",
  "unit": "count",
  "description": "当前网站最近一次检查状态为 healthy 或 verified 的页面数量；仅页面重新检查后的持久化结果计数。"
}
```
