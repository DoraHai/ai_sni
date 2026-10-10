# SEO 站内 AI 提案与顾问汇总

开发基线：`ca6a34c28da342327526539579898bfa3baedd87`（origin/codex/production-seo，含 PR640）。
对齐 `AI_WORKFLOW_COORDINATION_20261010.md`。本轮仅后端、本地测试与提交，无生产配置、迁移、采集、发布或官网写入。

## 顾问汇总（只读）

`GET /api/v1/seo/workbench/advisor-tasks?limit=20&tenant_id=4&before_id=100`

- `tenant_id`、`before_id` 可省略；`limit` 默认 20，范围 1–50。
- 响应：`schema=1,module="seo",items,next_before_id`，按任务 ID 降序；下一页严格 ID 小于游标。
- 先用 SQL 联结任务、站点、客户、模块权益、当前 active 顾问分配、有效实名用户和角色，再分页。用户客户绑定、网站启用、模块 active/trial 和到期日均在 SQL 中过滤。无分配/无编辑资格返回空，API Key 无实名身份返回 403。显式越权客户筛选返回 403。
- 每项沿用站内记录，新增 `scope_name,tenant_name,next_action,blocker,capabilities`；blocker 为安全 `{code,message}` 或 null。仅汇总 `onsite_optimization` schema=1，不声称包含所有类型的顾问工单。
- GET 不创建任务、不更新游标或运行状态、不启动生成/采集，也不访问供应商。没有全量统计字段，当前页长度不等于任务总量。

## 手动触发 AI 提案

`POST /api/v1/seo/workbench/onsite-tasks/123/ai-proposal`

```json
{
  "tenant_id": 4,
  "site_id": 2,
  "expected_revision": 1,
  "request_id": "9d4d4214-ce30-4b89-a6d8-cbfa51186ec8",
  "mode": "initial"
}
```

必须为有效实名顾问，拥有本站 active 分配、seo.site/seo.content 编辑权限和 seo.keywords 查看权限，客户绑定匹配且网站与模块启用。接口不接受新增 URL、模型配置、资料 ID 或工具命令。

`initial` 仅 draft；`revise` 允许当前未结束任务，包括复检失败。done/cancelled 拒绝。POST 只持久化入队，HTTP 202 立即返回当前任务、`replayed`、`request_run`、`poll_after_seconds` 和 `links`，不等待供应商。

下面是后台生成完成后的 GET 响应主要字段示意（非真实客户数据）：

```json
{
  "id": 123, "module": "seo", "tenant_id": 4, "scope_id": 2,
  "workflow": {
    "schema": 1, "revision": 2, "phase": "review",
    "ai_run": {
      "request_id": "9d4d4214-ce30-4b89-a6d8-cbfa51186ec8",
      "state": "ready", "mode": "initial", "source_revision": 1,
      "source_hash": "sha256-of-server-source-bundle", "actor_user_id": 7,
      "started_at": "2026-10-10T08:00:00+00:00", "finished_at": "2026-10-10T08:00:05+00:00"
    },
    "ai_proposal": {
      "summary": "AI 起草，事实和适用条件仍须人工核对；未修改官网",
      "proposal_revision": 2,
      "items": [{"id": "title-10", "reason": "依据公开资料，仍需人工确认", "source_refs": ["fact:30:v1"], "missing_information": []}],
      "missing_information": []
    }
  },
  "allowed_actions": ["save_proposal", "cancel", "approve"],
  "completion_evidence": null,
  "capabilities": {
    "ai_planning": {"enabled": true, "can_generate": true, "reason": null, "daily_limit": 5},
    "website_execution": {"enabled": false, "status": "reserved", "reason": "官网自动修改暂未接入，按批准方案人工实施"}
  },
  "replayed": false,
  "request_run": {"request_id": "9d4d4214-ce30-4b89-a6d8-cbfa51186ec8", "state": "ready"},
  "poll_after_seconds": null,
  "links": {
    "status": "/api/v1/seo/workbench/onsite-tasks/123/ai-requests/9d4d4214-ce30-4b89-a6d8-cbfa51186ec8?tenant_id=4&site_id=2",
    "cancel": null
  }
}
```

示例省略原记录的 title、items/source/history 等不变字段；实际 source_hash 是 64 位十六进制。理由与缺项仅在 ai_proposal 内，既有验收 Item 仍只有 id/kind/target_url/expected/instruction。缺证据的项 expected 为空、missing_information 有说明，整体仍待人工补充，不能审核空预期值。

## 持久化后台请求与轮询（2026-10-11）

不新增表、列或迁移。队列复用 `SeoTask.params.onsite_ai_requests`；`onsite.ai_run` 是当前请求的公开投影。SEO 独立调度器每 10 秒发现持久化任务，每批最多 20 条、同时最多处理 2 条，每条独立数据库事务。调度器关闭/演示环境/外部动作关闭时拒绝新增入队；本次不修改生产开关。保持现有官方主模型和入队时记录的模型路由，配置变化时拒绝执行，绝不自动切换或重试供应商。

```http
GET /api/v1/seo/workbench/onsite-tasks/123/ai-requests/9d4d4214-ce30-4b89-a6d8-cbfa51186ec8?tenant_id=4&site_id=2
```

- GET 返回现有 public task 顶层结构及指定请求的 `request_run`；`workflow.ai_run` 始终代表当前请求。查询历史请求不会替换它。每次读取重新核对实名、客户/网站范围、当前顾问分配、模块授权与权限；越权 403、范围/请求不存在 404，不泄露任务。
- 前端每 3 秒查询 `links.status`；`queued/running` 返回 `poll_after_seconds=3`；终态返回 null 并停止轮询。读接口不领取、不恢复、不调用模型、不更新记录。网络中断后使用同一个 request_id 查询；需要确认入队结果时重放同一 POST，不生成新 nonce。
- 只有返回的 `request_run.request_id` 与界面等待的请求及 `workflow.ai_run.request_id` 都一致时，前端才可采用该请求完成的提案。被后续请求替代时应刷新当前任务，不能把旧响应覆盖到新方案。
- 公开状态：`queued` 已持久化待领取；`running` 已提交调用意图，可能已付费；`ready` 提案已保存待人审；`failed` 调用未获准或供应商明确拒绝；`unknown` 中断/超时/输出不合规或运行中取消，需人工核实；`stale` 权限、服务、任务或事实变化，结果未采用；`cancelled` 领取前取消，未调用供应商。除 queued/running 外均为终态，不自动付费重试。
- 公开时间为带 UTC 时区 ISO 8601：`queued_at` 入队时间，`started_at` 领取并提交调用意图时间（排队时 null），`finished_at` 终态时间。旧请求可能没有 queued_at。公开字段仍含 request_id/mode/source_revision/source_hash/actor_user_id/error，不暴露 prompt、凭证、claim_id 或供应商元数据。
- 排队与运行期间，`allowed_actions` 只保留取消；其它方案写入/审批/实施/复检返回 409 `onsite_ai_busy`。原方案、审核和完成证据在成功生成前保持原状。后台结果通过全部校验后才保存待审方案并清除旧审批与完成证据。

可选受控取消，不要求首期 UI 接入：

```http
POST /api/v1/seo/workbench/onsite-tasks/123/ai-requests/9d4d4214-ce30-4b89-a6d8-cbfa51186ec8/cancel
Content-Type: application/json

{"tenant_id":4,"site_id":2}
```

取消也重新核对当前顾问权限并持久化终态。queued → cancelled；running → unknown，明确供应商可能已调用，不能承诺退费或中止远端计算；迟到结果不再采用。重复取消返回原终态。既有整项任务 cancel 同样使当前请求终止。配额作为准入记录不退还。

## 有界、幂等与事实边界

- 每网站每天最多 **5 次准入**，北京时间自然日，记录在既有 `SeoSite.site_settings.onsite_ai_quota`。本站多个任务共享配额；成功、失败和不明都保留额度，平台 controls 未启用也生效。没有付费自动重试。
- 每任务最多 **40 个不同请求**，请求台账保存在 `SeoTask.params.onsite_ai_requests`，不删除旧 nonce；仍受原任务 100 条历史上限。无需 DDL。
- 先按客户+UUID 的事务级 advisory lock 去重（跨本站任务及同客户其他网站），再按网站/任务行锁串行保存 nonce、操作者、模式、源版本/哈希、无密钥的供应商地址/模型元数据和 `queued`，提交后立即返回。后台按相同网站→任务加锁顺序领取，核对身份/顾问分配/服务授权/事实哈希与版本，提交 `running` 和唯一 claim_id 并释放锁后才调用供应商。同 nonce 同参数返回已记录状态（replayed=true），不同参数/操作者或跨任务复用 UUID 返回 409，不暴露另一任务资料；旧 nonce 已被后续请求替代返回 409，不再付费。另一 nonce 遇到 queued/running 返回 409。
- 供应商超时 45 秒，外层 55 秒；一次尝试。崩溃后 running 保留在数据库，后台发现开始时间超过 120 秒则记 unknown，绝不重新调用（包含已领取但尚未实际发送时的中断）。queued 可在重启后继续领取，但超过 24 小时过期并需人工核对；权限或来源变化则 stale。GET 和 POST 重放都不负责恢复或偷偷重试。此后顾问核对并使用新 UUID 才是新尝试，仍受配额限制。
- 只使用当前任务绑定的关键词和页面、当前网站最多 20 条有效且有出处的 QA 事实；资料总上下文最多 5 万字符。page/keyword/fact 引用使用服务器提供的 ID/版本，未检查页面不提供伪造的页面事实。
- 保留清单所有 id/kind/target_url；关键词预期须属于绑定词，Meta Keywords 限于该页绑定词；内链/canonical 只能选已绑定页面。新网址、假来源、敏感输出、结构不合规拒绝保存。当前没有 robots/sitemap 文件正文证据，因此这类预期必须留空并列缺项；不能编造文件策略。
- AI 文案是待审核建议，引用有效来源不等于系统证明每句话正确，事实、适用条件和内容质量必须人工确认。只发 JSON 提案，没有网站执行工具。
- 外部调用后重新读取实名用户/角色、顾问分配、模块/网站、任务版本以及来源哈希；最终事务对权限与来源记录加短读锁。撤权、版本或资料变化时结果记 stale；受控取消、已过期或已终止请求维持既有终态，迟到结果均不能覆盖人工状态。撤权后的查询拒绝返回任务内容。
- 成功通过原 `prepare_change(save_proposal)`，增加 revision、转 review、清除旧审核/实施/复检/验收与 completion_evidence。人工再次保存方案会清除旧 AI 提案说明，避免把理由挂在已修改方案上。

## 供应商与错误

### 2026-10-10 稳定性修订（模型输出协议 v2）

- 本轮基线为 `d6297f3b7b7af643fe402058aa2c3cb87d4ad247`。外部 API 请求、站内工作流 schema、权限与配额不变；仅模型输入/输出增加 `schema_version=2`，无版本的旧输出仍兼容。
- 服务器按原 item id 装配固定 kind/target_url；模型重复提供时必须完全一致。输入包含 `bound_pages` 的 id/url/ref。内链和 canonical 可提供 `destination_page_id`，服务器只从实际绑定页装配目标 URL 与页面出处，不推测事实出处。
- 内链来源固定为当前项 target_url，expected 只允许目标页裸 URL，不能自链。HTML、Markdown 或方向说明不会被提取为地址，而是保留为待确认缺项；外部或改写地址仍拒绝。中文标点、句末标点仅在说明文本的 URL 校验中识别，不用于修正 expected 地址。
- 非空 expected 同时带 missing_information 时，保留所有阻碍并清空 expected。空预期未说明原因时补充“尚未给出可核验内容”；有效资料明确标注冲突时，受影响标题/描述列明真实来源及冲突摘录，不选一个数字当结论。此检测只识别显式冲突标记，不是通用事实一致性引擎；文案仍须人工核实。
- 缺项结果可以保存为待审草案，`ai_run.state=ready` 只表示草案处理成功。存在空 expected 的方案不能审批，不能视作已完成内容或已修改网站。敏感输出、伪造出处、外部地址先校验再处理缺项，不允许借留空绕过拒绝。
- 回归保存 18 份既有真实供应商输出，含正常资料、缺项及检测仪量程冲突，离线执行且不再次调用供应商。另以真实本地 PostgreSQL 验证保存、审批拒绝、nonce 重放及异常输出不覆盖原方案。离线通过不代表新提示词的在线生成成功率，需另行批准真实模型评测。

复用现有 `app.ai.deepseek.chat_json` 及当前官方 DeepSeek 主模型配置；不修改现有配置解析器、不增加默认第二模型，不创建密钥、不换供应商。入队记录服务器当时解析出的路由，后台调用前必须完全相同；单次请求不做失败回退。仅接受现有官方 HTTPS 入口。计量 context 绑定 tenant/user/module=seo/feature；`job_ref=site:{site_id}:onsite_ai_proposal:{task_id}:{request_id}`，底层供应商 operation 仍为既有 `chat.completions`。不修改 metering/controls schema 或开关，不向普通客户/顾问返回供应商成本、密钥或原始错误。

- 401/403：身份、权限、分配不符；404：任务/站点范围不符。
- 409：旧 revision、nonce 冲突、正在运行、已结束、来源变化或迟到结果。
- 422：请求或上下文不符合限制；429：本站当日准入上限；503：未配置可用官方供应商。
- 已完成准入的供应商拒绝记录 failed，超时/解析失败/不合规输出记录 unknown。POST 202 仅代表请求已记录；GET 200 仅代表成功读取，调用方必须检查指定 request_run.state，不能把 HTTP 成功当作生成完成。

## 本轮未启用与验证

月度自动建单、自动接续、官网自动修改均未启用；不新增计划开关或调度任务。启动/月度/整改由已有人工建单入口创建，再由有权限顾问明确触发 AI。

测试包含纯校验、HTTP 契约及真实 PostgreSQL：跨客户、撤权、角色/客户绑定变化、模块到期、并发 nonce、跨任务日限额、迟到与人工更新、资料变化、供应商失败/未知、复检失败后修订清证据、GET 无写入。PG 使用现有 loopback `seo_workflow_test`、显式 schema-create 授权和每测试随机 schema；供应商替身，不接真实平台。SEO baseline 原生 PG 作业纳入新测试并检查零跳过；常规回归纳入 baseline/deploy，发布白名单仅增加必要精确路径。

后台队列专项验证包含并发入队/领取、请求连接断开、领取后进程丢失模拟、协程取消、结果提交失败、重新扫描恢复、取消与迟到输出、入队后和调用中的权限/资料变更、只读轮询、历史请求隔离、运行期开关、排队过期及路由变化。本地数据库均为临时独立 schema，供应商全部替身；没有真实付费调用或生产变更。
