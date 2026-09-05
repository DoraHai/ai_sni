# SEM 基础契约（2026-09-05）

## 范围与交付状态

从最新 main 创建 `codex/sem-foundation-contracts`。本次仅实现客户级只读指标与
一键真实回写缺失幂等键拒绝；SemTask 只提交设计供独立 Schema 审核。
不修改 SEO/GEO、不对接驾驶舱、不部署、不运行任何 Alembic 命令。
`migration=not-run`。任务 CRUD 尚未实现、未开放，不能当作已经可用。

## 只读指标接口

`GET /api/v1/sem/metrics/snapshot?tenant_id=<正整数>` 返回
`{tenant_id, items: [{metric_key, value, unit, as_of, trend_7d, definition, data_status}]}`。

- 需要合法登录态或已有合法 API Key；必须同时具有 `monitor.dashboard`、
  `verify.adjustments` 查看权限，并满足客户隔离、SEM 模块授权有效。
- 这是单客户快照，不提供跨客户聚合，也不暴露其他客户的冲突账户身份。
- `as_of`：报表指标为最近纳入的报表日期（上海时区零点，表示日期，不是采集时刻）；
  当前状态指标为读取时间。无有效数据时为 null。
- `value=null` 不等于 0；有真实零消耗报表才返回 0。返回值是已落库观测值，
  不证明所有账户/日期都同步完成，不可直接视为百度账单或核销依据。
- `trend_7d`：统一为 null 或 `{direction, change_pct, change_abs}`。
  direction 为 up/down/flat/null，仅表示相对七天前的事实方向，不评价好坏。
  change_abs 为当前值减七天前值；change_pct 为差值 / 七天前值的绝对值 × 100。
  基数为 0 时百分比为 null，仍保留可计算的绝对变化和方向；确实没变化才是 flat。
  花费比较截至昨日的本月累计与该报表日期七天前的本月累计（9 月 9 日对比 9 月 2 日）。
  跨月重置、不足七天历史、月内缺报或归属异常时整个对象返回 null，不插值或当零处理。
  补报会重算观测历史，不是不可变快照，也不证明所有账户均已完整同步。
- 月预算、账户状态、审批状态、身份冲突没有可用历史快照，趋势返回 null，
  不拿当前状态/预算倒推过去七天。以后新增历史快照必须另行审核。
- 只读本地数据库，不刷新 token、不请求百度、不启动采集、不写入任何记录。

| metric_key | unit | 一句话口径 |
| --- | --- | --- |
| sem.spend.month_to_date_cny | CNY | 本月截至昨日、当前客户可归属账户的关键词报表 cost 合计，不是实时账户总花费。 |
| sem.spend.budget_utilization_pct | percent | 上述本月花费 / tenants.monthly_budget × 100，无正数月预算返回 null，不封顶 100%。 |
| sem.accounts.active_count | account | 当前客户本地 status=active 的百度账户记录数，不代表远端 token 已实测有效。 |
| sem.approvals.pending_count | approval | 当前客户 writeback_approvals 中 status=pending 的数量，不含 approved/consumed。 |
| sem.identity.conflict_tenant_count | customer | 当前客户存在隔离标记或 active UCID 跨客户重复时为 1，否则为 0。 |

身份冲突客户仍可看到上述冲突数，其他四项返回 null/identity_blocked，不读取其报表。
报表账户为空、不存在或属于别的客户时，该月花费与使用率失败关闭，避免漏计后伪装正常。
data_status 包含 available、observed_reports、no_reports、unattributed_reports、
no_budget、identity_blocked；observed_reports 明确不表示全量报表完整。

## 一键回写幂等补强

沿用现有 `idempotency_key`（16–128 位 ASCII 字母/数字/-_.:），不另增 client_request_id。
一键真实回写（没有显式 approval_id）必须提供 key；缺失时在数据库工作前拒绝，
不修改实名、confirmation、approver、参数 fingerprint、TTL 或消费校验逻辑。
前端已有 runIdempotentWriteback 生成并复用 key，本次无需前端改动。

原有机制继续有效：客户 + 操作员 + key 的摘要构成事务锁范围；持久化记录只保存
摘要，重复 key 返回同一记录；不同参数拒绝；已消费、过期的记录无法再次消费。
同一 key 不会因过期而自动创建新记录（比“有效期内不可重放”更严格）。
合法新意图须使用新 key。不能在网络重试时换 key，否则它表示另一笔操作。
演练不创建/消费资金确认，仍允许无 key；显式 approval_id 保留原先一次消费机制。
数据库失败需由已有请求事务回滚；不更改外部执行与 pending 台账持久化顺序。

## SemTask Schema 提案（未实现、待审核）

建议新增独立 `sem_tasks`，不改用审批表承载任务，不挂接自动真实回写。
共享 API 的 module 固定 sem；SEO/GEO 各自实现并审核，不在此表混存。

| 字段 | 建议类型 / 约束 | 原因 |
| --- | --- | --- |
| id | bigint 主键，自增 | 稳定任务引用 |
| tenant_id | bigint 非空 FK tenants.id，删除限制 RESTRICT | 必须具备客户隔离，不随客户删除审计任务 |
| module | varchar(8)，CHECK module='sem'，非空 | 共享契约识别模块 |
| action_type | varchar(64)，非空，服务端允许列表 | 不允许任意脚本/方法执行 |
| title | varchar(300)，非空 | 人话标题 |
| params | jsonb 非空对象，各 action 单独验证 | 保存参数；禁止凭据、任意 URL 或 SQL |
| status | varchar(20)，非空，枚举 open/in_progress/done/cancelled | 显式状态机 |
| created_by | varchar(80)，非空，服务端写入 user:<id> 或 cockpit | 不接受客户端冒充创建人；cockpit 当前不开放 |
| assignee_role | varchar(64)，非空，服务端角色白名单 | 分配角色不是权限授予 |
| completion_evidence | jsonb 可空对象，done 时必须非空 | 服务端核验的指标变化证据 |
| created_at / updated_at | timestamptz 非空，服务端维护 | 新表统一带时区，API 输出 ISO8601 |

索引：主键；`(tenant_id, status, created_at, id)` 支持稳定分页与队列；
`(tenant_id, action_type, created_at, id)` 支持按动作审计。暂不创建大 JSON GIN 索引。
约束：JSON 对象类型检查、status 枚举、module 常量、done 要求证据非空；
证据真实性不能仅靠 CHECK，需要服务层核验。同一事务行锁保护状态更新。
不修改现有表字段，不回填历史任务或客户数据。

### API 与完成语义提案

- POST /api/v1/sem/tasks：服务端从身份生成 created_by，强制 tenant 及模块授权；
  创建时记录核验指标、客户/账户范围、基线观测与判定条件，不接受自填完成证据。
- GET /api/v1/sem/tasks 与 /{id}：所有查询必带租户范围，过滤及稳定游标分页。
- PATCH /{id}：只允许白名单字段、合法状态转换；普通 PATCH 不得进入 done。
- POST /{id}/verify：只读核验指标后写任务审计状态，不发起百度写回；
  同一客户/账户/指标/单位、基线与观测时间有效、数据可用且满足目标条件才进入 done。
- DELETE /{id}：逻辑取消为 cancelled，不物理删除审计记录。
- 完成证据至少包含 metric_key、tenant_id、账户范围、baseline/value、各自 as_of、
  条件/阈值、服务端核验时间和可追溯来源引用。不将数值变化等同因果证明。
- 当前无不可变指标快照时，需审核基线/结果嵌入式证据方案；不能拿未来会变化的
  URL 或当前值冒充历史证据。指标缺失、身份冲突、样本不足时保持未完成。

### Schema 风险、审核与回滚

本次没有读取生产库 revision/Schema，也未创建 ORM 表或迁移；上述不是线上已核实结构。
实施前另行授权只读核对生产 revision、表结构及 main 迁移图，确认单独新迁移的
down_revision，禁止修改历史迁移。新表 FK 可能产生短暂锁等待；单独维护窗口执行。
迁移单独提交、单独审核，不进入普通 SEM 部署自动步骤。
应用必须等表就绪后才开放任务 API；回退应用时禁用任务入口，保留新增表和审计数据，
不通过删表或 downgrade 破坏客户记录。无需本次生产配置、Nginx或数据库操作。

## 验证

运行 `python -m pytest tests/test_sem_foundation_contracts.py tests/test_writeback_approval.py -q`。
覆盖身份/权限隔离、模块授权、只读 HTTP、零值与缺失值、多账户归属、趋势口径、
缺失幂等键、已消费 key 重放、旧审批指纹与 TTL 回归；全量离线回归排除迁移执行测试。

本次执行结果：专项 48 passed；全量 1708 passed、2 skipped，git diff --check 通过。
两项跳过是未配置专用本地 PostgreSQL 的历史测试，未连接生产数据库替代。
新增汇总测试执行 SQLite 内存数据库真实 SQL；并发测试使用事务锁替身验证服务流程，
这是首轮结果；后续原生 PostgreSQL 验收结果见下节。
全量测试使用进程级虚拟配置并清空 AI Key；首次继承本机 AI 配置时 GEO 的一项测试失败，
在旧基线复现并确认隔离配置后通过，没有改动 GEO 来绕过测试。

### 后续契约加固与原生数据库验收

共享 trend_7d 对象格式澄清后：专项重新执行 73 passed，覆盖增长、下降、持平、
零基数、不足历史、精确七天比较及跨月；不再返回日期数组或空数组。

最终回归：1728 passed、0 skipped；按约定不收集 SEO 迁移执行测试；
既有 jieba/pkg_resources 弃用警告 1 条。git diff --check 通过。

- 指标响应接入 Pydantic，OpenAPI 暴露固定五项指标、单位、带时区 as_of、
  缺失状态和趋势结构；拒绝错误单位、无时区时间、非有限数值、旧版趋势数组和漏项。
- 补每月第一天、跨月及闰年边界、补报重算测试；不把缺报误作零花费。
- `tests/test_sem_foundation_postgres.py` 在 PostgreSQL 16.15 上验证原生事务：
  并发请求等待提交后拒绝重复消费；第一次回滚时重试成功且只留一条记录；
  已提交消费在后续数据库错误回滚后仍不可再消费；过期 key 与不同参数不能创建新确认。
- 仅连接 `127.0.0.1` 且数据库名必须为 `sem_foundation_test`；每次测试生成随机
  `sem_foundation_test_*` Schema，仅清理自己创建的 Schema。
  拷贝审批表用于测试时移除外键，不创建客户或用户数据；这不替代外键完整性验收。
- CI 新增 `sem-foundation-contracts` 测试作业：独立 postgres:16 服务、虚拟凭据，
  自动执行原生测试，不依赖生产 Secret，不部署，不执行迁移。未改生产发布步骤。
- 本地复现需显式设置 SEM_FOUNDATION_TEST_DATABASE_URL 为上述专用测试库，
  执行 `python -m pytest -q tests/test_sem_foundation_contracts.py tests/test_sem_foundation_postgres.py tests/test_writeback_approval.py`。
