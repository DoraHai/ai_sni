# SEO 项目控制适配：本地开发候选，2026-10-11

本轮在独立 `codex/seo-automation-projects-20261011` 分支实现；#648 的冻结提交
`5ae1ae70d57a986a9f4f901310fffb2b0ae299e1` 不变。没有推送、合并、部署、生产 DDL、
真实模型调用或开关变更。新结构仍是独立 SQL/ACL 审核候选，不注册 Alembic revision。

## 已接入

入口 `app/api/seo_automation_projects.py` 已挂到 SEO 主 router。路径前缀
`/api/v1/seo/workbench/automation-projects`：

| 方法和后缀 | 行为 |
|---|---|
| GET 空后缀 | 当前有效实名顾问被分配的网站；可选 tenant_id/before_scope_id，limit 1–50，先权限过滤再分页，无伪造总数 |
| GET `/{scope_id}/control?tenant_id=…` | 当前控制记录；没有配置返回 not_started/version0；不会初始化 |
| PUT `/{scope_id}/control` | 显式保存已存在任务、owner、cycle、limit；不启动 |
| POST `/{scope_id}/control` | start/pause/resume/takeover/end/disable_cycle；乐观版本、UUID 幂等，返回当前状态与 applied_version |
| GET `/{scope_id}/runs?tenant_id=…` | 历史运行，稳定 created_at/id 游标，不允许跨范围 cursor |
| GET `/{scope_id}/runs/{run_id}?tenant_id=…` | 精确运行、步骤、进度、成果引用和费用状态 |
| GET `/{scope_id}/events?tenant_id=…` | 包含首次配置等 run_id=null 的项目级事件 |
| GET `/{scope_id}/runs/{run_id}/events?tenant_id=…` | 精确运行事件 |

全部私有响应（包括权限、数据库和输入错误）no-store。结构/ACL 待就绪时只读
`Project.state=schema_pending`、`capabilities.schema_state=pending`，不可写；数据库故障
是脱敏 503 automation_unavailable，不返回空项目假装正常。读取接口不推进采集/任务。

权限通过真实 User/Role、tenant 绑定、SEO module entitlement、有效站点、顾问分配和
网站/内容编辑及关键词查看权逐次核验。API Key 身份不能配置自动项目。配置中的 owner
必须是当前实名顾问。新顾问接手一个仍属旧 owner 的活动项目时，控制能力明确禁用并返回
automation_owner_mismatch；本轮不增加跨顾问强制转移接口。

## 执行与真实边界

`run_automation_projects` 在现有 SEO scheduler 下每 10 秒扫描最多 20 个受控项目，
每个项目使用独立事务。未安装新结构时不创建/执行；禁用 scheduler、外部动作或 demo
环境不运行。仍须人先保存并 start，保存 cycle.enabled 不会直接触发第一次执行。

只处理配置中已有且符合条件的 draft 站内任务，复用 `SeoTask` 原 AI 队列，调用次数、
站点日限、平台财务和真实计量保护不变。项目 claim、事件、子队列请求和配额在同一事务
提交，避免双队列不一致。没有任务/任务已起草或曾有不可重放调用时 blocked/waiting_input，
不创建新任务、不反复付费。每日/月度未来周期只复用同一已选任务集；不会自动扩充范围。

现有 `seo_onsite_ai_jobs.execute_request` 在项目行锁后取站点/任务锁；实际外呼前再次核对
当前身份、分配、权益、任务/资料版本，持久化唯一 dispatch marker 后释放事务再调用。
回包应用前重新核对同一代际及原始执行归属。暂停/接管/结束后迟到成果不得写入方案，
只保存 stale/unknown 和真实费用引用。已准入的 HTTP 不能撤回，显示 pausing 等待收尾。
重启不重发已登记请求；超时转 unknown 等人工核对。子任务被移出原站点/删除后，原项目
安全收尾 unknown，不读取它的新范围业务内容，也不重新派发。

`api_usage_events` 按原 tenant、module、精确 job_ref 查询。有真实台账且金额已知才标
recorded；缺台账或金额未知保持 unknown_charge。兼容已审核金额字段；不以旧估算覆盖
人工核验未知金额。手工取消后的迟到费用记追加 late_provider_receipt，不采用旧方案。
自动步骤 succeeded/人工 end 都不会产生业务 completion_evidence、审批或验收。

## 尚未接入项目停止检查点的既有能力

返回的 coverage.controlled 仅有 configured_onsite_ai。coverage.not_controlled：
manual_onsite_ai、ranking_collection、competitor_collection、backlink_collection、
content_cycle、service_diagnosis_cycle、monitoring_cycle、monthly_report_cycle、qa_batches、
image_verification、page_capture、platform_publication、website_mutation、approval、acceptance。

核对结论：`seo_automation_runs.py` 是采集结果摘要，不能充当暂停门禁；排名与竞品/外链
任务目前按租户或批次触发，缺少受控 run/step token 以及回包前检查。内容周期和
`seo_service_workflows.py` 虽有 opt-in、网站服务暂停及自身进度，仍是独立执行状态机，
尚未绑定本项目 generation。接入前必须逐请求补入同范围 checkpoint、真实台账/成果引用，
并测试批次中途撤销及迟到写入；不能只在 scheduler 外层加开关就宣称全部暂停。
页面审核、官网实施、验收保持人工步骤，不在自动动作集合。

## 本地验证与样例

使用专用 loopback seo_workflow_test 数据库，每个测试独立随机 schema；供应商以
MockTransport 代替，真实授权、项目/任务 SQL、队列、计量代码运行，没有生产数据。
新增集成测试 `tests/test_seo_automation_projects_postgres.py` 包括真实 JWT 与实时 RBAC、
HTTP 配置/动作/所有读取契约、权限/范围派发前变化、真实计量下迟到结果、进程丢失、
日志失败回滚、周期不重复起草、游标隔离及数据库错误脱敏。共享核心另有独立原生 PG 测试。

设置 `SEO_AUTOMATION_SAMPLE_PATH` 为 TEMP 下文件路径后运行集成测试，可导出实际 HTTP
响应（合成客户/站点，不含 auth header、凭证或客户隐私）。本轮文件：
`C:\Users\Administrator\AppData\Local\Temp\seo-automation-api-synthetic-samples.json`。
样例不是生产接口已上线的证明；前端联调仍应使用本地候选接口。

本轮结果：8 个相关测试文件 300 项通过、0 跳过；最后补充跨范围子请求标记隔离后，
SEO 适配层 35 项原生 PostgreSQL/HTTP 测试再次全部通过、0 跳过（两组数字有重叠，
不相加）。共享核心文件保持 e8157e1c 不变，其 36 项测试包含 24 项原生 PG 场景。
仅有既有 jieba/pkg_resources 弃用提示。测试报告分别在 TEMP 下
`seo-automation-final-regression.xml` 和 `seo-automation-adapter-final.xml`。
