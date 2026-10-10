# 调用保护与监控审核包（2026-10-11）

后端基线 `4fe201ece3e95b89472d54d40eeb8b8779d58a15`，工作台基线
`4920eba27ba09e6d6c13377c86f0fc17c4cdf439`。本轮交付代码与测试，未经审核不合并、不部署、不执行生产 SQL、不更改任何资金开关。

共享保护与 SEM 只读监控分别提交。总控可以先审查共享提交，再在各发布单元取入；不把整个 SEM PR 合入 SEO/GEO。UI 是独立 PR。

| 服务 | 本轮代码范围 | 当前可证明的保护边界 | 启用前要求 |
| --- | --- | --- | --- |
| SEM | 基线已有计量/预算代码，本轮新增并发和未知费用阻断；本 PR 尚未发布 | 管理结构仍待审核，新增限制未生效 | 审核管理 SQL、核对计量和管理开关、发布版本，再配置策略 |
| SEO | 本轮没有发布或修改独立服务分支 | 调用台账可观测不代表新准入已生效；独立运行开关/代码版本需核对 | 总控取入共享提交，原生测试与独立发布，核对同库和开关 |
| GEO | 本轮没有发布或修改独立服务分支 | 全局/专用/站内模型用途各自核对；新准入尚未在本轮集成 | 总控取入共享提交，保持 task/request_run 契约，独立验收版本和开关 |

`ai-governance.modules[].controls` 仅对本进程 SEM 提供可核对的 runtime_enabled；SEO/GEO 为 null，管理结构就绪时为 runtime_unverified，缺结构时为 schema_pending。不能拿 SEM flag 证明其他两个服务已生效。

## 可在既有费用台账上发布的部分

- `/admin/console/snapshot` 的 `operations.call_monitor`：真实供应商尝试的成功、明确失败、未知、未结束、费用未知、缺价、平均耗时与 P95；查询保持只读、超管权限和 no-store。
- 近 24 小时成功率的分母是 succeeded + error；unknown/requested 单列，不能用请求成功率替代业务结果验收。未结束与超过十分钟未结束统计全部历史；其他运行指标统计近 24 小时。未定价与缺价可能重叠。
- pending 超十分钟、结果 unknown、缺价各有页面告警；告警不额外调用供应商、不发送外部消息。十分钟只用于提醒，绝不自动释放预算或重试。
- `workers.state=not_connected`，没有编造 worker 心跳、队列深度、领取率或 scheduler 故障。SEO/GEO task + request_run 的 queued/running/ready/failed/unknown/stale/cancelled 与心跳契约须等模块侧确认后另行整合；本轮不解析任务业务 JSON。
- 既有计量关闭时返回 ready，只能证明历史记录存在。管理表缺失或部分安装返回 schema_pending；不能因表存在就说限制已经生效。
- 客户、用户身份继续由已有鉴权与可信业务作用域赋值，后台任务无用户 ID 时不冒充用户。未归属调用保留未归属，不猜客户。
- SEM `chat_messages` 清理误导性的“重试后”文案和未实际生效的循环，明确一次调用一次供应商请求；网络错误不记录密钥/响应内容。不增加第二模型或自动 fallback。

## 需要审核结构和显式启用的部分

原有管理审核包仍未授权执行：

1. [api_controls_schema.sql](../scripts/api_controls_schema.sql)：四张管理表和 `api_usage_events.reserved_amount`；原脚本没有 IF NOT EXISTS，必须核查实际 catalog，不能重复执行或对部分安装盲目重跑。
2. [api_controls_permissions.sql](../scripts/api_controls_permissions.sql)：既有对象所有者执行；运行角色的审计权限仅 SELECT/INSERT，不能 DELETE/UPDATE 审计，不赋予 CREATE。
3. 隔离库先执行上述脚本并验收权限、原子准入、并发竞争；生产执行由人工审核后安排。台账已有且计量已启用，并不代表管理表已经获准。
4. 本轮 `max_concurrent` 为 budget JSON 可选字段；`budget:provider:<host>` 使用既有 budget kind，因此没有新增表、列或 kind 的 DDL。旧预算缺字段表示未设置并发限制，没有偷偷赋默认限额。
5. 在各独立服务均部署相同准入协议之前，不配置跨服务新预算。特别是旧版 usage 把未知 target 当全局，旧版也不理解 max_concurrent；只升级 SEM 不能宣称 SEO/GEO 已受保护。由总控分别审查/集成发布单元后再启用。
6. 同时核对 `API_METERING_ENABLED=true` 与 `API_CONTROLS_ENABLED=true`、共享数据库和各服务实际版本；本轮不自动设置。仅修改本服务 flag 不代表其他模块已启用。工作台能力字段防止新版 UI 向旧版 backend 提交新范围/字段。

## 准入与失效语义

同一 PostgreSQL 事务级 advisory lock 保护“读配置、读占用、检查、INSERT requested、提交”，然后才能发请求。两个进程/池共享记录而非各自计数。全局、已确认客户、登录用户、供应商 host 的策略同时检查。供应商依据去掉 query/credentials 的 endpoint host，业务 provider 别名不能绕过限制。

- 请求次数与金额按北京时间日/月统计，requested 也计请求次数，拒绝的请求不计供应商尝试。
- 并发占用是全部历史 requested + unknown。0 表示暂停新请求，null 表示未设置；成功或收到明确失败响应且终态写入提交后才结束并发占用。超时结果 unknown 继续占用；写终态失败或崩溃时保留 requested，不按 PID/时间自动释放。
- 金额预算先预留保守费用；缺少价格、无法限制输入/输出、流式/多模态仍拒绝。错误或 unknown 不能假定免费；即使有 reserved_amount，已结束且 estimated_amount 为空仍暂停同范围金额预算。
- 跨日/月的历史未结束请求或未核清费用不会被日历重置抹除。历史未知费用可能持续阻断，须账单核查；禁用保护绕过占用不是结算办法。
- 准入拒绝给出范围标识；超管预算表列并发与待核清数，监控列最早未结束时间并提供调用台账入口。可按客户/用户/接口、状态和包含该时间的日期范围定位请求 ID。告警认领/标记处理只写告警审计，不修改调用或预算。

## 人工安全解除：独立审核对象，当前不可操作

永久保留并发位有可用性代价。本轮选择阻断并提供可定位记录，不提供“强制释放”按钮。安全解除机制必须先审批，不能只把告警标记完成。

审核中的后续协议应满足：

1. 命名全局超管定位精确 event UUID、scope、供应商 request ID、冻结价格版本，向供应商核实终态/用量/扣款；只有可验证的终态证据才能结束 requested。供应商暂无记录不是未扣款证据。
2. 已确认终态但金额还未知，可以结束真实并发占用，金额预算仍阻断；有供应商未扣费证明才能登记零费用，有用量或发票才能登记可信金额。账单币种不匹配不得隐式换算。
3. 在与准入相同的事务锁下 SELECT FOR UPDATE 检查 expected state/version，追加独立结算审计（操作者、证据引用/摘要、核对时间、前后状态、幂等 UUID）后更新精确事件；一个事务提交。迟到的供应商结果不得覆盖已核实的结算。
4. 不删除调用，不自动重复发送，不把预留当实际扣款；结算不能触发百度资金写回。原台账尚无结算版本/证据对象，字段、权限和迟到结果的协议另交具体 SQL 与原生并发测试审核。
5. 结算的回退是保留已追加证据并做另一条经审核的纠正记录，不能删审计、覆盖原证据或通过回滚业务事务抹掉已付费请求。

## 价格来源与局限

2026-10-11 读取 [DeepSeek 中文官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)：
api.deepseek.com 的 deepseek-flash，以及该页明确承认的旧名 deepseek-v4-flash、deepseek-v4-flash-vision-exp，按人民币高峰价格（输入 2、缓存 0.04、输出 8 元/百万 token）保存标为 `peak_ceiling` 的保守上限；pro 的独立报价按该页 9/0.30/27 保存独立模型行。不是时段账单金额，不推断节假日，不改变主模型。

总控读取的现用 SEM/SEO 默认及 GEO 站内模型是 deepseek-chat；GEO 全局 DashScope 槽为 deepseek-v4-flash-0731，专用 DeepSeek 槽为 deepseek-v4-flash，三种用途分开。现行价格页没有 deepseek-chat，且 [官方旧版公告](https://api-docs.deepseek.com/zh-cn/news/news260424) 表述其退役日期，与此前真实调用成功证据存在差异；因此本轮不自动把它计为 Flash、不猜金额、不改路由、不发付费探针。DashScope 的 -0731 也不按官方 DeepSeek 价格算。准确合同/别名计费证据待核对；可审核后配置精确 rate override，仅作用后续请求。

历史价格不追补，unknown 不归零，账单实际扣款保持未接入。

## 集成验收补充

完整表/列/权限、生产只读证据、重复/部分安装和回退、三池 fixture 与上线检查见
[PLATFORM_CONTROLS_ROLLOUT_20261011.md](PLATFORM_CONTROLS_ROLLOUT_20261011.md)。
共享补丁按序取入：`f49cd5af`（unknown 并发保留）、`6fc9b74a`（半安装准入阻断）、
`eed858cf`（计量失败发送阶段）；SEM 后台客户作用域是后续独立提交，不能整包取到 SEO/GEO。
UI #650 已交总控整合到 #646，本轮冻结 #650，不单独发布。

## 风险与回退

- 所有新功能通过独立 backend/UI PR；代码回退沿用各自发布流程。当前两个开关保持现状，schema 等待人工审核。
- 管理结构是增量，没有业务删改；锁/statement timeout 分别限制为 3s/15s。失败回滚该结构事务；部分安装先人工盘点，不运行 DROP/CASCADE。
- 启用后未知占用可能阻断新请求，跨服务版本差异可能漏保护；必须核对账务、登记完整性和全模块升级，不能把版本就绪与限制生效混为一谈。
- 若要关闭管理保护，必须由负责人明确审核风险；这会解除后续准入检查但不会结算或删除历史占用。无需 DROP 新表/字段；保留证据后回退应用。资金开关、模型数量及默认路由不在此回退范围。
