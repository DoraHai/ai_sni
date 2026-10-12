# GEO 自动项目 v2 实际覆盖

本文记录当前代码的真实边界。共享契约和账本由共享实现提供；本分支没有执行生产 DDL、真实供应商调用、渠道发布或网站修改。

## 已接入受控执行

| operation | 类型化目标 | 产物与限制 |
| --- | --- | --- |
| `onsite_ai` | `onsite_task` | 为 draft 站内任务生成首次 AI 方案。人工审核、实施、复检和验收不自动执行。 |
| `visibility_patrol` | `prompt × engine` | 每个问题与引擎独立步骤，写真实回答快照。正式指标仍排除模拟、人工和未知来源。 |
| `content_brief_suggestion` | `content_task` | 保存确定性建议作业结果，不覆盖任务 Brief。 |
| `competitor_report_draft` | `competitor_alias` | 从项目快照生成非持久化待审报告，不直接确认正式结论。 |
| `content_master_draft` | `content_task` | 仅为尚无母稿的任务生成 V1；不提交审核或替客户确认。 |
| `channel_variant_draft` | `content_task × channel` | 仅当最新母稿仍有活跃实名用户的审核通过记录时生成一个规则草稿；不调用模型、不发布。 |
| `publication_monitor` | `publication` | 只读抓取登记公开页。每次 HTTP 请求和重定向跳转分别准入，只写监测证据与人工复查工单。 |
| `outcome_review` | `metric_task` | 用完整周正式指标更新复盘观察；未达标时创建人工工单，不自动改内容。 |
| `periodic_workflow` | `project` | 刷新项目并创建人工工单，不调用模型。 |

配置和开始运行校验完整计划。逐步骤执行只校验当前未完成目标，同时精确校验共同服务计划及 source bindings。前一步产生母稿或监测状态后不会用已完成目标阻断后续步骤；外部修改当前目标、范围、负责人或权限仍会阻断。

`source_bindings` 按 `(kind, object_id)` 无序精确集合比较，revision 与 sha256 必须一致。不同 operation 只读取自己的来源：竞品快照超过 500 只阻断竞品报告，非法渠道只阻断渠道稿，不影响巡检、周期或站内方案。

## 预留而未接管

`authorized_distribution` 仍为预留项。现有配置没有同时绑定“确认母稿版本、渠道稿版本、渠道账号、明确动作、人工放行人和有效期”的不可变证据，因此不会创建推送或发布作业。

真实网站修改也未接管。`approval`、`acceptance`、客户确认和人工质量判断保持人工流程。

## 外呼、费用与停止语义

- 每个供应商请求或 HTTP 跳转有独立 `begin_call`；同一 call key 已准入后不会自动重发。
- 单次运行外部请求总数受 `max_external_calls_per_run` 限制，共享契约当前上限为 100，并非每步骤只允许一个请求。
- pause、takeover、end 或权限、来源变化后不再发送下一请求；迟到响应只保存回执，不写业务成果。
- 可核实 `api_usage_events` 金额时供应商调用记 `recorded` 并引用账本事件；缺少完整台账时保持 `unknown_charge`。供应商成功不等于已记账。
- HTTP 公开页检查记 `not_called`，调用次数仍受外部请求上限约束。
- 已成功但费用未知的不可变回执不会被承诺为自动补记，需要独立费用核对流程。

## 旧入口防绕行

- 租户巡检按已接管 `prompt_id` 排除，未接管问题继续沿用旧巡检，不要求整租户迁移。
- 项目周期在业务写入前检查归属，暂停或结束不会退回旧周期。
- 发布监测按 `publication_id`、结果复盘按指标工单 ID 排除已接管记录。
- 内容与站内 AI 子作业从共享运行反查归属；已准入、运行中、结果未知或完成步骤不会由恢复器重发。
- 部分安装、损坏或重复归属失败关闭，不能降级成普通后台任务。

## 人工与运行边界

一次运行全部步骤到达成功、阻断或未知后进入等待人工。下一周期只在人工结束当前运行后计算；本实现没有把等待人工伪装成无人值守循环。

本地验收使用隔离 PostgreSQL、实际 ASGI 路由和 MockTransport。上线仍需要审核迁移、生产配置、真实队列健康、模型质量与真人发布流程验收。

## 真实登录与输出安全验收（2026-10-11）

`tests/test_geo_automation_v2_real_auth_postgres.py` 在随机隔离 PostgreSQL schema 中执行真实
`/api/v1/auth/login -> JWT -> User/Role -> require_scoped_auth -> GEO v2` 链路，没有覆盖
`require_scoped_auth`、`require_auth` 或伪造 `AuthContext`。专项 3 项全部通过、0 跳过，覆盖：

- 配置依据、configure、start、control、run、events、export 和全局 health；
- 匿名、API key、篡改/过期 JWT、跨租户和租户绑定账号拒绝；
- 同一 JWT 下的角色撤权、用户停用和模块开通撤销即时生效；
- start 后、外部请求前撤销模块权益时外呼数为 0；供应商返回期间通过真实 JWT 暂停时，迟到回执保留但不写正式回答快照。

该验收发现并修正了路径权限归类：`/api/v1/geo/workbench/automation-projects/*`
现按 GEO 资产/内容的读写权限校验，health 按平台管理权限进入后仍执行路由内的
“两项权限 + 全局实名用户 + 数据库新鲜身份”校验。

AI 站内草稿校验同时增加两类拒绝规则：`API_KEY` / `api-key` / `apikey`
赋值及高置信密钥样式，以及没有真实流程证据的“已实施/已发布/已验收”完成声明。
否定句和未来指导（例如“尚未发布”、“不得声称已发布”、“人工审核后实施”）保持可用。
`tests/test_geo_onsite_ai.py` 定向 61 项全部通过。
