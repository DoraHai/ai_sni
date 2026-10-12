# GEO 项目自动执行控制（开发候选）

GEO 适配共享 `schema=1` 项目控制契约，范围键为 `GeoProject.id`。功能默认关闭；顾问必须先明确保存任务、周期、单次调用上限、停止条件和本人负责人身份，再单独启动。

## 首期实际覆盖

`coverage.controlled` 只有 `configured_onsite_ai`：项目配置里列出的站内整改任务可以依次生成待人工核对的方案草稿。项目按钮不控制手动单次站内 AI、可见度巡检、周期项目工作流、渠道分发/发布、网站写入、审批或验收，这些能力均在 `coverage.not_controlled` 明示。

暂停、接管和结束会立即增加共享执行代际，阻止新的供应商准入。已排队但尚未发出的子作业被取消且记为 `not_called`；已经发出的请求无法撤回，晚到结果只保留费用/事件状态，不写入站内方案。`end` 不代表业务验收，`completion_evidence` 仍为空。

## 接口

- `GET /api/v1/geo/workbench/automation-projects`
- `GET|PUT|POST /api/v1/geo/workbench/automation-projects/{project_id}/control`
- `GET /api/v1/geo/workbench/automation-projects/{project_id}/runs`
- `GET /api/v1/geo/workbench/automation-projects/{project_id}/runs/{run_id}`
- `GET /api/v1/geo/workbench/automation-projects/{project_id}/runs/{run_id}/events`
- `GET /api/v1/geo/workbench/automation-projects/{project_id}/events`

所有范围请求必须给出正整数 `tenant_id`，写操作还需要 UUID `request_id` 和精确 `expected_version`。响应及错误均为 `Cache-Control: no-store`。共享结构未安装或权限不完整时，控制读取返回 `schema_pending`，写入返回 `automation_schema_pending`；数据库异常统一为脱敏的 `automation_unavailable`。

## 权限与恢复

负责人必须是当前服务计划实际分配且仍具备 `geo.assets=edit` 和 `geo.content=edit` 的实名顾问。列表先按实时分配过滤再分页；分配或权限变化后，读取仍可显示记录，但 `can_control=false`、动作清空并返回 `automation_owner_mismatch`。恢复器只领取确有 `pending` 且没有 `running` 步骤的运行，不让等待人工的项目占用恢复窗口。

共享步骤在领取时保存不可变的 `claim_generation`，并在同一事务绑定实际 `GeoAsyncJob.id`。执行器以共享运行中的 `request_id + task_id + job_id + claim_generation` 为权威；删除或篡改子作业 `request_meta.automation_token` 不会把自动作业降级成普通手动作业，也不会绕过暂停代际。

项目自动执行只为仍属于当前项目、尚未发起过 AI 请求且没有既有方案的 `draft` 任务生成首次草稿。任务进入审核等后续阶段、已经存在方案或请求记录、或在排队期间被移到其他项目后，步骤原子记为 `blocked/not_called`，不会创建子作业或覆盖方案。人工单任务接口仍可显式使用 `revise`；自动周期不会替人工决定修订。

## 上线边界

`scripts/automation_projects_schema.sql` 和 `scripts/automation_projects_permissions.sql` 仍是人工审核候选。本阶段只在隔离开发/测试 PostgreSQL 中安装验证，不注册生产迁移、不执行生产 DDL、不启用真实供应商或资金开关、不部署。
