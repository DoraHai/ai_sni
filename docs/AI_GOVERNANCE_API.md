# 平台 AI 自动化治理只读接口

## 接口

`GET /api/v1/platform/ai-governance`

只允许已有的命名全局超级管理员：账号无租户绑定，并同时拥有 `settings.accounts=edit` 与
`settings.customers=edit`。匿名账号、普通客户、租户管理员、权限不完整账号和运维 API Key 均返回
403/401。响应使用 `Cache-Control: no-store, private`，接口只执行只读事务，不调用供应商、不生成
AI 内容、不创建任务、不修改控制配置。

## 顶层契约

```json
{
  "schema": 1,
  "state": "available",
  "generated_at": "2026-10-10T00:00:00+00:00",
  "observation_window": {
    "kind": "last_24_hours",
    "start": "2026-10-09T00:00:00+00:00",
    "end": "2026-10-10T00:00:00+00:00"
  },
  "modules": [],
  "controls": {},
  "capabilities": {},
  "incidents": {},
  "coverage": {}
}
```

`state=available` 表示 `api_usage_events` 台账存在；`state=schema_pending` 表示计量结构不存在。
控制结构未审核或未启用不影响计量只读，此时 `controls.editing=disabled`。本接口不会执行
`api_metering_schema.sql` 或 `api_controls_schema.sql`，也不会打开 `API_CONTROLS_ENABLED`。

## modules

固定返回 `sem`、`seo`、`geo` 三项，每项包含：

- `provider/model/configured`：脱敏配置状态。SEM 可读取当前进程配置，但只返回是否配置；不返回 Key、
  URL 认证信息或凭据指纹。SEM 与实际 AI 客户端保持相同优先级：百炼已配置时选百炼，否则选
  DeepSeek；两者都未配置时 provider/model 为 null。SEO/GEO 是独立进程，只有其通过现有 control binding 登记后才显示配置，
  否则 `configured=null`、`configuration.state=unavailable`。
- `metering`：计量表状态及当前 SEM 进程的计量开关。SEO/GEO 的进程开关无法从本进程证明，返回
  `runtime_enabled=null`；近 24 小时有真实记录时为 `observed`。
- `limits`：`kind` 只使用 `scope/budget/calls`，`state` 只使用
  `enabled/disabled/schema_pending/unavailable`。`key=module_autonomous` 表示模块自治调用限额；
  `key=global.daily_calls|monthly_calls|daily_cny|monthly_cny` 表示平台全局限制；
  `key=provider:<host>` 表示服务商开关。本服务无法安全读取其他模块自治限额时返回
  `unavailable/null`。只有真实生效的限制才返回数值或布尔；未启用、缺结构或不可用时 `value=null`。
- `calls`：从 `api_usage_events` 按近 24 小时聚合 `total/failed/unknown/pending/unpriced`，并提供
  tenant、user、job_ref 归属计数、provider/model 与 operation feature 分组。SEO/GEO 的
  `onsite.ai_proposal` 等新 feature 直接按 operation 展示，无需新增字段或 DDL。

`failed` 只统计 `state=error`，`unknown` 只统计 `state=unknown`，`requested` 单列为 `pending`。
表不存在时这些数量返回 null；表存在且观察窗口确实无记录时才返回 0。只要任一调用未定价或用量
缺失，`estimated_amount=null`，`known_amount` 仍明确标为已知小计，不把未知费用当作 0。

明细继续复用已有超管接口 `/api/v1/admin/console/usage`。响应中的 `ledger` 声明可筛选维度；台账
`operation` 对应 feature，`job_ref` 对应已由调用方记录的 site/project/task scope。没有记录 job_ref
时不根据业务表反推，保持未归属。

## 能力与异常状态

- `capabilities.human_review.required=true`。
- `capabilities.website_execution={enabled:false,status:"reserved"}`，本接口不提供任何官网写入能力。
- `capabilities.sem_funds_execution` 只反映现有 dry-run 状态。dry-run 关闭也只返回
  `enabled=null,status=conditional_account_policy`，因为仍需既有账户、scope、审批和额度判定；本改动
  不修改资金动作、审批或开关。
- `incidents` 读取现有 `api_control_audit` 中最后一次 alert 处理状态，保留 `resolved`、`in_progress`
  和重新打开后的 `open` 计数。控制结构不存在时返回 `schema_pending/null`。

该接口不跨数据库读取 SEO/GEO 任务，不用调用次数推断任务数量，也不创建统一 SEM 假任务。任务详情
继续由各模块现有工作台接口负责。
