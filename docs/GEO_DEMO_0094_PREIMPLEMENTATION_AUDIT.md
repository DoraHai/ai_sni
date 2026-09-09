# GEO 同域双数据源演示：0094 实施前审计

## 审计边界与结论

本审计只读取 Git revision、迁移文件和 SQLAlchemy metadata，没有连接 `sem_prod`、`gsnipers_demo`
或其他数据库。数据库现状采用协调方提供的事实：生产 `sem_prod.alembic_version` 只有
`0094_seo_qa_batches`；拟使用独立 `gsnipers_demo`，由现有 API 进程在同一网址、同一登录下按已鉴权
演示租户选择数据源。

对照基线：

- GEO：`codex/production-geo@5df03e016d7b862017750b86f90b33001ba63310`，head
  `0074_geo_ticket_assignment`；
- SEO 0094：`codex/seo-qa-durable-batches-20260906@ddab535d46032506f7d0de05eae5758e80afd5aa`，
  head `0094_seo_qa_batches`；
- 当前 Draft：PR `#504`，`a14304112442fadf9fcd2a958058b1635b4f4592`。本文件不改变该 PR。

结论：`0094_seo_qa_batches` 已包含 GEO 到 `0073_geo_schema_repair` 的完整祖先链。当前 GEO head
比 0094 多且仅多 `0074_geo_ticket_assignment`。因此从真正空库严格执行 0094 全链后，当前 GEO 模型
缺少的精确对象只有：

| 表 | 缺少对象 | DDL | 约束/索引 |
| --- | --- | --- | --- |
| `geo_action_tickets` | `owner_name` | `VARCHAR(100) NULL` | 无新增约束或索引 |
| `geo_action_tickets` | `due_date` | `DATE NULL` | 无新增约束或索引 |

不能把 `gsnipers_demo` 直接 stamp 成 0094。应在最终协调分支创建包含所有当时 live heads 的 merge
revision，并从空库执行 `alembic upgrade <final-head>`。若当时 live heads 仍只有这里审计的两条，merge
revision 的 parents 应包含 `0094_seo_qa_batches` 和 `0074_geo_ticket_assignment`，且自身不需要 DDL；
Alembic 会先执行缺少的 0074 两列。若 SEM 或其他模块已增加新 head，必须一并纳入，revision 名称和
编号不能由 GEO 单方面预定。

## 祖先图证据

使用 Python AST 读取每个迁移文件的 `revision` 和 `down_revision` 后，从两个 head 反向遍历：

- GEO 0074 祖先（含自身）：88；
- SEO 0094 祖先（含自身）：111；
- 两者交集：87；
- GEO 独有：仅 `0074_geo_ticket_assignment`；
- 0094 明确包含 `0073_geo_schema_repair` 和 `0074_merge_geo_seo_heads`。

关键分叉如下：

```text
0072_merge_login_seo
├── 0073_geo_schema_repair
│   ├── 0074_geo_ticket_assignment              # GEO head，0094 不包含
│   └── 0074_merge_geo_seo_heads ── ... ── 0094_seo_qa_batches
└── 0073_seo_distribution_variants ─┘
```

0094 在 `0074_merge_geo_seo_heads` 合并 `0073_geo_schema_repair` 与
`0073_seo_distribution_variants`，随后经 SEM/SEO merge 和 SEO 0078–0094 到达最终 head。因此 0094
不是“SEO-only 空库”：它的祖先包含共享基础表以及 GEO 0035–0073 DDL。

共同祖先文件逐 revision 做 SHA-256 内容比较，共 87 个 revision 中只有
`0065_seo_rewrite_schema_repair` 内容不同。GEO 分支的 0065 额外重复执行了 GEO 0063/0064 修复；0094
分支的 0065 只保留 SEO 修复，但其后 `0073_geo_schema_repair` 包含同一组 GEO 幂等修复。对真正空库，
原始 0063/0064 本身也会执行。因此这个文件差异不会造成空库缺表或缺列；对历史 stamp 库，0073 是
实际的 GEO 修复节点。

`alembic_version=0094_seo_qa_batches` 只能证明 revision 标记，不能单独证明历史 DDL 实际存在。生产库
曾出现 stamp 越过父迁移的背景，所以若以后要判断 `sem_prod` 的真实 schema，仍需数据库负责人用
只读 catalog 查询核对，不能根据本静态审计推断。

## 0094 已覆盖的 GEO DDL

当前 GEO metadata 有 28 张 `geo_*` 表。除 0074 的两个可空列外，建表、后续加列、外键、唯一约束和
索引都来自 0094 的共同祖先：

```text
geo_action_tickets                 geo_ai_settings
geo_answer_snapshots               geo_article_versions
geo_async_jobs                     geo_audit_runs
geo_channel_accounts               geo_channel_polish_prompts
geo_channel_variants               geo_competitor_aliases
geo_competitor_report_versions     geo_competitor_reports
geo_content_tasks                  geo_daily_metrics
geo_deliverable_archives           geo_expand_runs
geo_facts                          geo_media_placements
geo_optimization_businesses        geo_optimization_periods
geo_optimization_units             geo_prompts
geo_publications                   geo_publishing_channels
geo_task_facts                     geo_tracking_engines
geo_visibility_patrol_runs         geo_visibility_patrol_settings
```

需要在空库验收中重点核对的唯一约束为：

- `geo_channel_accounts(channel_id, display_name)`；
- `geo_channel_polish_prompts(tenant_id, channel_key)`；
- `geo_competitor_aliases(tenant_id, alias_name)`；
- `geo_competitor_report_versions(report_id, version_no)`；
- `geo_daily_metrics(tenant_id, metric_date, scope_key)`；
- `geo_deliverable_archives.share_token`；
- `geo_optimization_businesses(tenant_id, name)`；
- `geo_optimization_units(tenant_id, business_id, name)`；
- `geo_publishing_channels(tenant_id, name)`；
- `geo_tracking_engines(tenant_id, engine_key)`；
- 所有模型声明的 tenant、task/version、prompt/snapshot、business/unit、period、channel/account、
  report/version、patrol/snapshot 外键及其 `CASCADE`/`SET NULL` 行为。

0073 还以幂等 DDL 明确修复：`geo_optimization_businesses.profile`、
`geo_facts.business_id` 及索引、`geo_competitor_reports`、`geo_competitor_report_versions`、相关外键、
唯一约束和索引。0074 只增加前述 owner/deadline 两列。

## 最终统一空库迁移验收草案

数据库负责人应在一次性空 PostgreSQL 中执行，不对生产库操作：

1. 使用最终协调代码和完整 migration directory，确认 `alembic heads` 只有一个最终 head；
2. 从无 `alembic_version`、无业务表的数据库执行 `alembic upgrade head`，禁止 stamp；
3. 确认最终 head 的祖先同时包含 `0094_seo_qa_batches`、`0074_geo_ticket_assignment` 以及当时所有其他
   live heads；
4. 通过 `pg_catalog`/SQLAlchemy Inspector 对照上述 28 张表、全部模型列、外键、唯一约束和索引；
5. 精确确认 `geo_action_tickets.owner_name VARCHAR(100) NULL` 与 `due_date DATE NULL`；
6. 在第二个全新空库重复一次，比较 schema digest；
7. 对已升级库再次执行 `alembic upgrade head`，必须无 DDL 变化；
8. 只在以上通过后，才允许创建 demo loader/runtime 账号。不能用当前
   `ops/run_geo_checks.py --postgres` 的 `MetaData.create_all` 代替迁移验证。

## 同域双数据源的 GEO 最小边界

现有 `require_scoped_auth`、`AuthContext.ensure_tenant` 和 `require_geo_read_entitlement` 继续使用生产
控制库完成登录、租户绑定、GEO 开通与到期校验。数据源选择必须发生在这些校验之后，并且只读取服务端
保存的演示绑定，不接受客户端传入 `is_demo`、数据库名、连接串或路由提示。

建议将 GEO 绑定放在现有 `tenant_modules.module_settings` 的 `module_code='geo'` 行，例如：

```json
{
  "geo_data_source": {
    "kind": "isolated_demo",
    "database_key": "gsnipers_demo",
    "fixture_namespace": "g-snipers-geo-demo-v1",
    "read_only": true
  }
}
```

`database_key` 只能映射到服务器环境中的固定连接配置，不能成为连接串。生产 control tenant 与 demo
数据库 tenant 建议使用相同数值 ID，避免所有现有 tenant-scoped 查询和响应做双向 ID 翻译；loader
必须显式验证两边 ID、名称、namespace 和 entitlement。若不能保证同 ID，则需正式映射字段和全接口
翻译，已经超出“最小适配”。

最小代码结构建议：

1. 新增 GEO 自有 `data_source` resolver：先用生产 session 校验 auth、entitlement 和绑定，再返回
   `production` 或固定的 `gsnipers_demo` session factory；绑定缺失、未知、冲突或 demo DB 不可达时
   fail closed，禁止回退生产库；
2. 仅 `GET/HEAD/OPTIONS /api/v1/geo/integration/**` 可取得 demo session；生产租户仍取原 session；
3. `/api/v1/geo/tenants` 仍从生产控制库读取，可增加 `workspace_mode`、`read_only` 和
   `fixture_namespace`，不返回数据库信息；
4. demo session 的数据库账号只授予所需共享租户行和 GEO 表 `SELECT`。fixture loader 使用独立短期写
   账号，运行时绝不持有；
5. 现有 `read_routes.read_session` 改为 resolver 选择的 `REPEATABLE READ, READ ONLY` session；metrics
   snapshot/dictionary 也必须复用该只读 dependency，不能继续直接使用全局 `get_session`；
6. 所有 demo mutation 在取得业务 session 前拒绝。旧版 GET 可能初始化配置或更新超时状态，不得对
   demo 放行；模块详情通过现有站内 URL 消费 integration/read 接口；
7. scheduler、recovery、stale reconciliation 和 worker 继续只持生产数据 session，且其 tenant selector
   显式排除 `isolated_demo` 绑定。任何直接 executor 入口仍需复核绑定，防止以后给 worker 增加 demo
   连接后越界；
8. 正式指标在读取 demo DB 前后都识别 tenant binding，强制 `value=null`、`trend_7d=null`，并返回
   `demo_tenant` 排除原因。现有 `simulated=true`/`mock_persona` 逐条排除继续保留，形成双层保护；
9. 若工作台要展示虚拟环比，只新增 GEO 纯查询 demo summary，明确 `official=false`、
   `source_kind=simulated` 和全虚拟标识；正式 `/integration/metrics/snapshot` 不返回虚拟数字。

当前 PR #504 的 `APP_ENV=demo` 是进程级门禁：生产进程下不会触发，启用后又会锁住全部客户并停止
全部 GEO 后台任务。它不能原样用于上述同进程双数据源方案。独立复审应保留 fixture/数据库保护思路，
把 runtime 门禁改写为 tenant binding 驱动；本审计不执行回退或改写。

## 测试矩阵

### 迁移与 schema

- 静态图测试：最终 head 可达 0094、0074 和所有新 live heads；只存在一个 head；
- 两次独立空库 `upgrade head` 结果一致；已升级库再次 upgrade 无变化；
- Inspector 精确比对 28 张 GEO 表、模型列、类型/nullability、FK/on-delete、UQ 和索引；
- 明确断言 0074 两列存在；缺少任一列时 API 不启动；
- 禁止用 stamp 或 `create_all` 让测试假通过。

### 鉴权、绑定与双数据源

- 绑定 demo 的普通账号只能访问自己的 control tenant，不能通过替换 `tenant_id` 访问其他客户；
- 未绑定超管选择 demo tenant 后同样进入只读数据源和门禁；
- query/header/body 伪造 `is_demo`、`database_key` 或 namespace 无效；
- production tenant 始终命中生产数据源，demo tenant 始终命中 `gsnipers_demo`；
- demo 绑定缺失、格式错误、数据库不可达、tenant ID/namespace 不符时 503/403 fail closed，绝不回退
  `sem_prod`；错误和日志不泄露 DSN/凭据；
- 连接池和 transaction 生命周期按请求关闭，跨并发请求不串数据源。

### 只读 API 与跨租户隔离

- demo 只允许 integration GET/HEAD/OPTIONS；POST/PUT/PATCH/DELETE、OAuth callback、公开分享、legacy
  GET、生成、巡检、审核、配置、渠道和发布全部在开 demo session 前拒绝；
- integration/read 每个事务由 PostgreSQL 确认 `transaction_read_only=on`；尝试写入必须被数据库角色和
 事务双重拒绝；
- answers/questions/content-task/versions/patrol/task 查询只返回 demo tenant 对象；用生产对象 ID 查询
  demo 或反向查询返回 404/403；
- 分页游标绑定 tenant、周边界和筛选条件，不能跨租户复用；时区保持 Asia/Shanghai；
- 切换诺德、老虎、全域演示后，三方对象数量、更新时间和内容摘要互不变化。

### scheduler、worker 与执行防线

- scheduler eligibility selector 不选择 demo binding，即使 demo DB 内设置 `enabled=true`；
- startup recovery、stale reconciliation、daily metrics、followup、patrol、async generation、variants、
  push 直接调用时均拒绝 demo tenant；
- 任务排队后才将租户改为 demo 的竞态中，worker 在获取任务锁后复核并拒绝，不调用模型/网络/发布；
- 并发两个请求不能创建任务、巡检、渠道稿或发布记录；demo 运行账号对 INSERT/UPDATE/DELETE 无权限；
- demo DB 没有模型、搜索、OAuth、渠道发布凭据，任何网络 mock 都应断言零调用。

### 正式指标与虚拟展示

- 全部 `mock_persona`/`simulated=true` 回答逐条显示 `simulated_sample`；
- 把夹具回答篡改为 `openai_compat`、`simulated=false`，并补齐表面完整巡检证据的对抗用例中，租户级
  `demo_tenant` 仍强制正式指标三个 value 和全部 trend 为 null；
- demo summary 只返回完整周虚拟原始对比，包含 `official=false` 和显著标识；正式指标接口永不返回
  demo summary 的数字；
- production tenant 的正式指标、周比较、字典与 completion evidence 全部保持原行为。

## 实施阻塞

1. 迁移协调方需发布包含 0094、0074 及所有新增 live heads 的最终单 head；
2. 数据库负责人需批准 `gsnipers_demo` hostname/database/runtime role/loader role，并完成上述空库验证；
3. 共享身份负责人需批准 `tenant_modules.module_settings.geo_data_source` 的键、写权限和 demo control
   tenant；
4. 必须确定 control tenant ID 与 demo DB tenant ID 是否相同；不同则重新评估全部 ID 翻译边界；
5. 服务器负责人需提供固定 `database_key -> DSN` 映射、连接池、健康检查和无生产回退规则；
6. 工作台负责人需确认现有站内 GEO 页面在 demo 模式只调用 integration/read 及可选 demo summary。

这些条件满足前，PR #504 保持 Draft；不得合并、部署、连接生产库、迁移或装载 fixture。

## 租户级 fail-closed 适配状态

本 Draft 已实现不依赖数据库迁移的控制面门禁，绑定仍只来自服务端
`tenant_modules.module_settings.geo_data_source`。只有上述四字段和值完全匹配时才识别为演示租户；未知
字段、错误类型、错误 database key、错误 namespace 或非只读绑定全部 fail closed。客户端参数不能选择
数据源。

当前阶段没有获批的 `database_key -> DSN` 固定映射，因此行为刻意收窄为：

- 已认证的正式指标 snapshot/dictionary 可读；三个正式指标的 `value` 和 `trend_7d` 强制为 `null`；
- 其他 `integration/read` 返回 `geo_demo_binding_unavailable`，不会使用生产 session 兜底；
- legacy GET、所有写方法、生成、模型、巡检、scheduler、worker、恢复、发布、OAuth 和历史公开分享均阻断；
- `/geo/tenants` 只从控制库返回 `workspace_mode`、`read_only`、`fixture_namespace`，不返回数据库信息；
- 执行路径在首次状态写入前复核绑定，并锁定控制面的 entitlement/binding 行到事务结束；绑定漂移、过期或
  格式损坏都不能继续执行。

这不是可展示完整 fixture 的最终数据源接入。后续只有在固定 resolver、独立只读数据库角色、空库迁移
验收和租户 ID/namespace 校验全部获批后，才可把 `integration/read` 接到 `gsnipers_demo`。在此之前
保持 Draft，且不连接数据库、不安装夹具、不合并、不部署。
