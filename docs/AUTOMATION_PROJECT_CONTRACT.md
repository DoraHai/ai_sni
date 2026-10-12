# SEO/GEO 项目执行控制 schema 1（开发契约，2026-10-11）

基于冻结 SEO #648/5ae1ae70 的独立后续分支 `codex/seo-automation-projects-20261011`。
本稿供顾问 UI 与 GEO 适配使用；不代表已部署。共享核心不导入 SEM 或模块模型；模块适配器负责当前身份、权益、分配、范围及额度。

## 既有能力与新增层

`seo_automation_runs` 已保存 ranking/competitor/backlink 的 scheduled/manual 摘要及数量，不包含项目控制、动作幂等、并发版本、追加事件或人工接管。保留这些底层记录；新项目运行只引用真实任务/旧运行，不再写一套假的采集成果。既有站内任务仍使用 SeoTask/GeoActionTicket 和各自 AI 请求队列。

## API

前缀 `/api/v1/{module}/workbench`，module=seo/geo；scope_id 在 SEO 是 site_id、在 GEO 是 project_id。
每个范围请求必须明确 tenant_id，后台核对真实归属；不由前端选择数据库、模型或账号凭据。

| 请求 | 输入及返回 |
|---|---|
| GET `/automation-projects?tenant_id=4&before_scope_id=100&limit=20` | tenant_id 可省略；只返回当前有效实名顾问实际分配的范围，先过滤再分页；返回 schema,module,items,next_before_scope_id。按 scope_id 降序，limit 1–50；不冒充全量统计 |
| GET `/automation-projects/{scope_id}/control?tenant_id=4` | 返回下述 Project；未配置为 version=0,state=not_started,configuration=null，无写入；未安装/半安装共享结构为只读 schema_pending，全部写能力 false |
| PUT `/automation-projects/{scope_id}/control` | `{tenant_id,request_id,expected_version,configuration}`；单独保存配置，不启动，不改现有生产/资金开关。未运行或本次已结束才能修改 |
| POST `/automation-projects/{scope_id}/control` | `{tenant_id,request_id,expected_version,action}`；action=start/pause/resume/takeover/end/disable_cycle。返回 Project + replayed；动作原子持久化，后台异步执行 |
| GET `/automation-projects/{scope_id}/runs?tenant_id=4&before_run_id=UUID&limit=20` | 历史运行；按 created_at,id 稳定降序；游标必须属于同范围；返回 schema,module,tenant_id,scope_id,items,next_before_run_id；limit 1–50 |
| GET `/automation-projects/{scope_id}/events?tenant_id=4&after_id=0&limit=50` | 项目全部事件，包含尚无运行编号的配置；返回 schema,module,tenant_id,scope_id,items,next_after_id；各项保留真实 run_id 或 null |
| GET `/automation-projects/{scope_id}/runs/{run_id}?tenant_id=4` | 返回 schema,module,tenant_id,scope_id,run，包含真实 steps、进度、成果引用及费用状态；不会执行或恢复任务 |
| GET `/automation-projects/{scope_id}/runs/{run_id}/events?tenant_id=4&after_id=0&limit=50` | 返回 schema,module,items,next_after_id；按追加事件 ID 升序，limit 1–100；只读、权限/范围校验，事件不暴露 prompt/凭证/原始异常 |

所有写操作 request_id 是 UUID，expected_version 为非负整数。同一范围/主体/请求编号及同样内容重放不重复写、不重复启动；相同编号不同内容 409 automation_request_conflict。版本过期 409 automation_version_conflict。401 未认证、403 无当前操作权限、404 范围/运行不存在，禁止越权枚举。错误 `{detail:{code,message}}`；私有读写响应 no-store。写入遇缺结构/ACL 返回 503 automation_schema_pending，不偷偷绕过日志；DB 不可达 503 automation_unavailable。未知写结果不得由 UI 自动重试，应先精确 GET 核对。

## 配置（必须由人显式保存，AI 不得创建或修改）

```json
{
  "tenant_id": 4,
  "request_id": "12345678-1234-4234-8234-123456789abc",
  "expected_version": 0,
  "configuration": {
    "task_ids": [123,124],
    "operations": ["onsite_ai"],
    "cycle": {"mode":"once","enabled":false},
    "limits": {"max_dispatches_per_run":2},
    "stop_condition":"drafts_ready_or_blocked",
    "owner_user_id":7
  }
}
```

- task_ids 为已有本站/项目站内任务 ID，1–20 个、去重；只允许已存在、未结束、可起草且资料范围有效的任务，不自动建新任务或重做已产出的方案。
- operations 首期共同支持 onsite_ai。模块现有周期动作必须由适配器明确声明并确认已有完整配置后才能接入；UI 不应自行开启未声明操作。页面审批、官网写入和验收不在自动操作集合。
- stop_condition 必填且首期固定 drafts_ready_or_blocked：已选任务逐一产生待审草稿或明确阻塞后停止自动推进，等待顾问；调用次数上限独立生效。已有运行时 start 返回 409 automation_run_active，不能靠 start 重发。
- cycle.mode=once/daily/monthly，enabled 显式布尔；once 必须 false。开启未来周期不跳过本次等待人工状态；旧请求不明不自动重试，已生成待审任务不重复调用。没有合格任务返回 waiting_input，不制造“成功运行”。
- max_dispatches_per_run 为 1–20 次已持久化准入，不承诺金额预算，也不替代现有站点日限/平台预算。负责人必须是当前有效分配且具备模块编辑权限的实名顾问；首期配置负责人为当前操作人，不接受署名代替账号。
- 暂停、接管和结束增加执行代际，阻止新的自动外部请求及迟到自动成果写入；已经提交的供应商请求可能继续并计费，不能承诺撤回或退款。

## Project 与 Run

```json
{
  "schema":1,"module":"seo","tenant_id":4,"scope_id":2,
  "version":1,"generation":1,"state":"not_started",
  "configuration":{"task_ids":[123,124],"operations":["onsite_ai"],"cycle":{"mode":"once","enabled":false},"limits":{"max_dispatches_per_run":2},"stop_condition":"drafts_ready_or_blocked","owner_user_id":7},
  "cycle_enabled":false,"next_due_at":null,"current_run_id":null,
  "capabilities":{"schema_state":"ready","can_configure":true,"can_control":true,"available_operations":["onsite_ai"]},
  "coverage":{"controlled":["configured_onsite_ai"],"not_controlled":["ranking_collection","competitor_collection","backlink_collection","platform_publication","website_mutation","approval","acceptance"]},
  "allowed_actions":["start"],"blocker":null,"updated_at":"2026-10-11T00:00:00+00:00"
}
```

Project.state=schema_pending/not_started/active/pausing/paused/taking_over/taken_over/ending/idle；未保存配置时 allowed_actions=[]，可以 PUT 配置。
capabilities.schema_state 固定为 ready/pending；它和 Project.state 的 schema_pending 是不同字段。pending 禁写。
SEO 已有适配实现及未覆盖范围详见 `SEO_AUTOMATION_PROJECT_ADAPTER.md`；共享复用入口和事务要求见 `SHARED_AUTOMATION_CORE.md`。仍未部署。
Run.state=queued/running/waiting_input/waiting_human/pausing/paused/taking_over/taken_over/ending/ended/failed。
start 创建运行；pause 立即阻断新准入，有在途则 pausing，收到/安全隔离原结果后才 paused；takeover 同理 taking_over→taken_over；end 同理 ending→idle（run=ended，不是 accepted/done）。resume 只继续从未发出的步骤，不重发不明调用。disable_cycle 仅停用未来周期，不终止当前已许可运行。
run 包含 id,state,generation,stop_requested,started_at,finished_at,dispatch_count,steps,progress,completion_evidence；完成 AI 草稿后 waiting_human；completion_evidence 不因 end 自动生成。

运行响应示例（时间、ID 均为合成示例）：

```json
{
 "schema":1,"module":"seo","tenant_id":4,"scope_id":2,
 "run":{
  "id":"12345678-1234-4234-8234-123456789abd","state":"waiting_human","generation":2,"stop_requested":false,
  "started_at":"2026-10-11T00:00:00+00:00","finished_at":null,"dispatch_count":1,
  "progress":{"total_steps":1,"terminal_steps":1,"running_steps":0,"waiting_steps":0},
  "steps":[{"step_key":"onsite_ai:123","kind":"onsite_ai","task_id":123,"status":"succeeded",
    "started_at":"2026-10-11T00:00:01+00:00","finished_at":"2026-10-11T00:00:06+00:00",
    "waiting_for":"advisor","blocker":null,"result_links":[],"error_code":null,
    "request_id":"12345678-1234-4234-8234-123456789abe","evidence_refs":["seo_task:123"],"fee_state":"unverified"}],
  "completion_evidence":null
 }
}
```

step.status=pending/running/succeeded/failed/unknown/stale/cancelled/blocked；waiting_for=system/advisor/null。
result_links 仅模块生成的相对 API 路径，不接受调用方 URL；fee_state=not_called/recorded/unknown_charge/unverified，必须对应真实计量证据。步骤 succeeded 仅表示该自动步骤已产出，绝不等于业务验收。未知费用保留，不允许自动释放或付费重试。

事件页固定：`{schema,module,tenant_id,scope_id,run_id,items,next_after_id}`；有后页时 next_after_id 为本页最后 ID，无后页 null；不返回猜测总数。

事件为只追加持久化记录：id,run_id,actor_kind(human/system/ai),actor_user_id,module,step_key,code,request_id,evidence_refs,fee_state,created_at。AI 仅作为结果来源主体，永远不能调用 start/resume 或改额度。不得在日志存正文、提示词、密钥或供应商原始异常。先提交 dispatch intent 和事件，才能调用供应商；事件写失败必须禁止新的外呼。回包后即使代际失效也保留真实计量与脱敏事件，只抑制自动业务写入。

## 并发与上线边界

共享状态/运行/动作/事件在同一事务保存，动作乐观版本、范围幂等与行锁；每次外部请求前和自动结果落库前检查持久化 generation/run/current owner。重启只恢复尚未开始的工作，已提交请求意图保持不明或读取原结果，不自动再付费。
新增 SQL/ACL 为独立审核包，只在专用隔离 PostgreSQL 验证；不注册未经审核的生产迁移，不执行生产 DDL、不部署、不改真实模型/资金开关。既有 #648 固定候选不再修改。
