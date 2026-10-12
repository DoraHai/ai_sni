# SEO/GEO 项目控制 v2 最小契约（2026-10-11，本地开发）

基线 SEO b7229986，共享 e8157e1c；后续分支 codex/seo-automation-v2-20261011。
SEM 不在本批范围。仅本地提交，不 GitHub/push/部署/生产 DDL/真实付费调用。
旧 schema1 HTTP 包络和旧 Configuration 原样保留；新配置使用 contract_version=2。
能力白名单由模块实际已接入的门禁决定，不以共享语法可解析作为“已支持”。

## 配置、资料版本与 typed target

```json
{
  "contract_version":2,
  "operations":["onsite_ai","ranking_collect"],
  "targets":[
    {"operation":"onsite_ai","object_type":"onsite_task","object_id":123,"source_revision":1,"source_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    {"operation":"ranking_collect","object_type":"keyword","object_id":20,"source_revision":1,"source_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  ],
  "service_plan":{"revision":3,"sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},
  "source_bindings":[],
  "cycle":{"mode":"once","enabled":false},
  "limits":{"max_dispatches_per_run":20,"max_external_calls_per_run":40},
  "stop_condition":"drafts_ready_or_blocked","owner_user_id":7
}
```

operation/object_type 为长度至多40的安全标识；模块必须按能力白名单验证，不允许任意
函数名/插件名/URL/模型/密钥。targets 1–20、操作去重、每个操作必须有明确目标。
目标 object_id >0；source_revision >=0；source_hash 与 service_plan.sha256 为 SHA256。
source_revision 是模块真实对象版本（无版本对象为0，哈希仍必须校验），不是前端自造版本。
模块提供只读配置依据，按权限给出实际计划 revision/哈希及目标 revision/哈希；只有人能
保存该绑定。计划和目标均在派发前及成果写入前重算比对，变化即阻塞，不能自动更新绑定。
limits.max_dispatches_per_run 1–20；max_external_calls_per_run 1–100，均为准入次数，
不是金额预算，现有财务/站点限额必须仍生效。周期不会自动扩大目标清单。
target 可选 variant 为至多40字符安全标识（默认null），用于绑定配置中已批准的引擎等
有限枚举；不是自由工具/模型名。唯一键为 operation/object_type/object_id/variant。
GEO prompt×engine 必须分别成为 target 或稳定 call_key，每次真实请求单独登记。
source_bindings 为可选数组（默认[]，最多8项），每项
`{kind,object_id,revision,sha256}`；kind 是模块白名单安全标识，revision>=0。
可绑定 tenant_patrol_settings、project_prompt_set、project_scope_registry 等多份真实配置。
GEO 必须证明每个 prompt×engine 有唯一项目归属；只过滤已接管的集合，其余保留旧流程；
registry 读取错误禁止按“未接管”继续。归属冲突/不完整时配置或启动阻塞，不停整租户。

只读依据入口固定为 GET `/{scope_id}/configuration-basis?tenant_id=…&operation=…&before_object_id=…&limit=25`，
limit 1–50，每次只查询一种 operation；包络
`{schema:1,module,tenant_id,scope_id,contract_version:2,state,service_plan,source_bindings,available_operations,targets,next_before_object_id}`。
state=ready/schema_pending；pending 时 service_plan=null、source_bindings=[]、targets=[]、available_operations=[]。
targets 为上述 typed target，可增加安全 label；同一个 object_id 的所有合法 variant 必须一起返回，
limit 是对象数，最多每对象10个已配置 variant；按 object_id 降序，过滤权限后再分页。
目标/计划哈希仅包含业务输入、绑定、资料版本，不包含队列、ai_run、调用配额、游标或自生成日志。
顾问从此接口选择绑定，不手填哈希。每次配置/start/resume/外呼/回写都重算校验。

SEO 首批候选操作：onsite_ai、ranking_collect、site_diagnosis、monthly_onsite_plan、
content_draft、monthly_report、indexation_collection、incremental_diagnosis。只有实际端到端检查点及旧调度器防绕行完成后才加入
available_operations。index_check 暂不承诺：robots/indexable 不是收录，缺少已核实
单页收录来源时仍 not_controlled；indexation_collection 仅指站长之家非官方域名百度
收录量估算，须带 status/data_quality/methodology 及真实快照引用，不是单页收录证明。
ranking_followup 的分析成功也不等于实采排名。
GEO 各操作由其适配器注册，共享层不预先宣称它们全部支持；自动发布不因此契约获得授权。

## Typed step 与逐次外呼回执

step 保留 v1 的 status/progress/result_links/evidence_refs/fee_state 等字段，增加
operation、target（上面的确定对象）、calls。kind=operation；step_key 是模块生成的
安全短标识，不含正文、URL 或凭证；onsite_ai 保留 onsite_ai:<task_id>。
非 onsite 步骤的 task_id=null，UI 应使用 target.object_type/object_id 解释对象。
run 请求 ID 与每步请求 UUID 持久化，不因重启变化。

每个外部 HTTP/供应商请求使用稳定 call_key（安全短标识，至多80字符），在同一个
run/step 内唯一。begin_call 在事务中校验同范围、generation、运行状态及次数上限，
追加事件、保存准入记录后提交才能外呼。相同 call_key 不重复调用；结果不明不付费重试。
finish_call 保留状态、时间、安全 evidence_refs、fee_state，不保存响应正文/密钥。
HTTP 抓取可使用明确的 kind=http，付费/API 请求使用 kind=provider；不能把没有费用证据
的 provider 请求标成免费。回执收尾允许发生在停止之后，业务成果保存必须再次 check_step。
多页/多提示词操作每次请求都过门禁，不能只在整个批次开始时检查一次。

## 结束与既有调度器

新增 action=end_project，和 end 共用原有乐观版本及 UUID 幂等约束。
end 只结束本次；end_project 同事务设置 cycle_enabled=false、next_due_at=null 和 ended_at，
使所有已接管操作的新外呼及旧调度器准入停止；在途保留 ending，收尾后 idle。
Project 增加 ended_at（旧结构/未结束时null）；不能 resume/start 已结束项目。
重新开启须人显式保存新配置（清除 ended_at，not_started）后再 start，不隐式恢复。
这些动作不等于业务验收，也不创建 completion_evidence。

**接管原则：** 未配置 v2 时保留既有客户开关，不擅自启动新的项目运行。显式选入 v2
operations 的范围由项目机制独占自动调度；旧 scheduler/启动恢复不能再次建立独立
任务或绕过暂停。未被选入/未实现完整检查点的能力仍 not_controlled。
旧批次在新配置前已开始时，回包保存前必须重新读取门禁；新配置/停止后不得采用旧成果。
门禁锁顺序统一 project → run → 模块业务行；不得在持有业务锁后反向等待 project。
已接管操作不能通过 v2→v1 降级或移除 operation 隐式释放回旧 scheduler；需要停止时使用
end_project，归属仍保留。GEO 子集 registry 同样必须保留已停止目标的归属证据。
审核、人工官网修改、客户确认和验收保留人工接口；官网执行仅预留。

当前实现中，一轮步骤全部收尾后保留 waiting_human / waiting_input，项目仍 active；
不会自动把待人工处理解释为运行结束。顾问显式 end 本轮后，启用周期且到期的项目才可
创建下一轮，并重新校验来源。已生成方案、冻结月报或跨月来源变化需要重新选取配置。
因此当前周期机制不是无人值守的连续生产。SEO 实际操作范围见 SEO_AUTOMATION_V2_ADAPTER.md。

## 审计与导出

v2 增补审核 SQL：project.ended_at；event.safe_changes（数组，默认空）。
配置及动作事件记录白名单字段的 `{path,before,after}`，包括操作/目标ID、owner、周期、
额度、版本、计划/目标哈希和状态；不记录提示词、原文、完整服务计划、供应商配置或凭证。
旧库可继续旧 v1 能力；v2/结束项目/新审计未安装时必须 schema_pending，不自动 DDL。

GET `/{scope_id}/events/export?tenant_id=…&format=json|csv&after_id=0&through_id=…&limit=…`
limit 1–500；第一批返回/响应头给出范围内 snapshot_upper_id，后页固定该上限。
这是有上限的事件 ID 导出窗口，不承诺跨请求 MVCC 快照；并发未提交事件可能稍后可见。
同范围过滤、next_after_id、无猜测总数，不无限拉库。CSV 防公式注入；不得导出正文/密钥。
顾问只读所属范围；缺权限拒绝，不通过导出绕过日志权限。导出不启动任务、不外发邮件。

## 全局只读健康

GET `/api/v1/{seo|geo}/workbench/automation-health`，必须实名全局超管且 tenant_id=null；
沿用 settings.accounts/settings.customers edit，拒绝普通顾问/API Key。
包络 schema=1（独立于配置 contract_version）：

```json
{"schema":1,"module":"seo","scope":{"kind":"global","tenant_id":null},
 "as_of":"2026-10-11T00:00:00+00:00","state":"available",
 "counts":{"projects":1,"runs":2,"pending_human":0,"unknown_cost":0},
 "rows":[{"tenant_id":4,"scope_id":2,"project_state":"active","run_state":"running",
   "pending_human":0,"unknown_cost":0,"cycle_enabled":false,"updated_at":"2026-10-11T00:00:00+00:00"}],
 "truncated":false,
 "queue":{"state":"not_connected","queued":null,"running":null,"unknown":null},
 "worker":{"state":"unverified","verified":false,"last_tick_at":null,"evidence":null},
 "overall":"unverified","alerts":[]}
```

采纳超管 schema1 提案：projects=已配置项目数，runs=历史运行数；pending_human=当前运行
处于 waiting_input/waiting_human/taken_over 的项目数；unknown_cost=历史中有已准入供应商
调用且费用状态仍 unknown_charge/unverified 的步骤数，按步骤去重，不是金额或请求总数。
rows 每个 tenant_id/scope_id 唯一，至多50条，按客户/范围稳定排序；每行 unknown_cost
也是该范围所有历史未核实步骤数，run_state 为当前运行或null。counts 全局独立统计，
不得从截断 rows 求和。truncated 表示超出50个项目。

schema/ACL pending 时 state=schema_pending，counts 保留所有键且值null，rows=[]；
DB故障是脱敏503 unavailable，不能填0表示健康。queue 尚未汇总所有实际执行队列时
state=not_connected，其三个计数均null，不假装0。worker 有真实本进程调度 tick 才可
verified=true、evidence={kind:local_tick,scope:this_process}；没有统一心跳时
overall=unverified，禁止把进程 tick 当全系统健康。alerts 至多10个安全码及固定summary，
不含供应商原文、tokens/凭证。只做系统内提示，不发外部消息。

## 实现顺序与交付

共享核心由 SEO 唯一维护并单独提交供 GEO 挑选；不复制另一套状态机。先实现并测试
兼容语法、typed steps、逐次回执、end_project、安全审计，再接具体模块和旧调度器门禁。
所有控制/外呼边界以原生 PostgreSQL、真实 HTTP 鉴权及模拟供应商测试，不接生产库。
独立审核 SQL 安装后，须按执行方案排空/重建连接池的旧 prepared statements，再恢复
应用写入；不会在业务层自动重试迁移期间的失败写请求。本轮只在隔离测试验证此过程。
最终逐操作报告 controlled/not_controlled、精确 SHA 与 TEMP 合成响应/测试证据。
