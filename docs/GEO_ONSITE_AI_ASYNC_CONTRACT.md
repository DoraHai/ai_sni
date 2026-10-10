# GEO 站内 AI 方案异步契约

## 提交

`POST /api/v1/geo/workbench/onsite-tasks/{task_id}/ai-proposal`

- 必须携带 `X-Snipers-Onsite-Protocol: durable-v1`。缺失或其他值在入队、额度预留和供应商调用前返回
  HTTP `409` 与 `code=onsite_client_upgrade_required`，客户端应刷新工作台。
- 新请求持久化成功后返回 HTTP `202`。
- 响应保留现有 public task 顶层结构，并增加 `request_run`。
- 相同 `request_id` 与相同参数是幂等请求；已终止时返回 HTTP `200`。
- 同一任务已有 `queued`/`running` 请求时，新 nonce 返回 HTTP `409`。
- 无可公开使用事实等预检失败在入队前返回 HTTP `409`，不会计费。

## 轮询

`GET /api/v1/geo/workbench/onsite-tasks/{task_id}/ai-requests/{request_id}?tenant_id={tenant_id}&project_id={project_id}`

该 GET 是纯查询：不初始化配置、不修改超时状态、不重试、不调用模型。前端可每 3 秒轮询，在终态停止。

`request_run.state` 取值：

- `queued`：已持久化，尚未执行。
- `running`：执行器已领取，可能已发起计费请求。
- `ready`：严格校验通过且方案已保存，仍需人工审核。
- `failed`：已确认失败，不自动重试。
- `unknown`：计费请求或保存结果无法确认，必须人工核对，系统不自动重试。
- 调用门禁拒绝或初始计量台账写入失败时，供应商尚未被调用，分别记为
  `failed/admission_denied` 或 `failed/admission_unavailable`。供应商调用后终态计量写入失败记为
  `unknown/metering_finalize_unknown`，不得自动重试。
- `stale`：权限、项目范围、任务版本或公开资料版本已变化，结果未写入。
- `cancelled`：已取消；已发出的请求如返回，其迟到结果不会写入。

`request_run` 只返回请求 ID、作业 ID、状态、取消标志、`can_cancel`、受控错误文案、时间和轮询路径；不返回 prompt、凭证或供应商原始错误。`can_cancel` 仅对仍在排队或执行、当前顾问仍有效且与原发起人一致的请求为 `true`。

`queued`/`running` 期间 public task 的 `allowed_actions` 为空列表。取消能力不混入旧 `/actions` 枚举，前端应使用 `request_run.can_cancel` 和下方的独立取消接口。

## 取消

`POST /api/v1/geo/workbench/onsite-tasks/{task_id}/ai-requests/{request_id}/cancel?tenant_id={tenant_id}&project_id={project_id}`

只有当前有效项目顾问且是请求发起人才能取消。排队任务立即取消；运行中任务记录取消请求，供应商返回后丢弃结果。

## 健康与队列

`GET /api/v1/geo/workbench/onsite-ai/health`

仅全局超级管理员可读，返回 `schema=1`、`module=geo`、`observed_at`、`worker`和 `queue`。

- `worker.scope=this_process`。只有本进程真实成功 tick 才是 `active/verified`；启动但尚无 tick 是
  `unverified`，不代表整个服务健康。
- `queue` 是 `geo_async_jobs` 中站内 AI 作业的单次只读聚合：`queued`、`running`、`unknown`
  数量以及最早排队/运行时间。该接口不恢复任务、不调用供应商，也不返回客户正文、prompt 或密钥。
