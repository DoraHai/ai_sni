# SEM 独立演示运行环境审计

本文件只审计空独立 PostgreSQL 演示库、SEM 运行时关闭条件和未来 loader
的失败关闭条件。它不授权建库、迁移、装载、部署、同步或写回。协调决定见
`docs/cockpit/DEMO_ENVIRONMENT_DECISION_20260909.md`（协调提交 `1f46fab9`）。

## 结论

现有共享 Alembic 迁移可以在空 PostgreSQL 16 数据库从零执行到单一 head
`0088_seo_image_alt_reviews`。PR 505 的 CI 已在空 PostgreSQL 16 服务中完成这条
迁移路径，`Repository / migration validation` 通过。迁移链会建立 SEM、SEO、
GEO 共享表；它不是只建 SEM 表的迁移子集。

这个结论不表示当前演示包可以装载。存在两个硬阻塞：

1. `sem_tasks` 模型和 API 已存在，但建表迁移仍是独立提案，未进入当前 Alembic
   head。空库执行 `alembic upgrade head` 后没有 `sem_tasks` 表。
2. `baidu_accounts.access_token_encrypted` 与 `expires_at` 均为非空列。离线夹具按
   安全要求没有凭据，不能直接映射成当前 `baidu_accounts` 行。

在这两个问题和下文运行时硬门未解决前，loader 必须不存在可执行 apply 路径。

## 空库迁移依赖

- 数据库必须是 PostgreSQL；迁移和模型使用 `JSONB`、PostgreSQL 部分索引和
  PostgreSQL SQL。SQLite 或通用 SQL 数据库不能作为等价演示库。
- 应用迁移入口读取 `DATABASE_URL`，要求 SQLAlchemy async URL，当前标准方言为
  `postgresql+asyncpg`。
- 当前迁移图只有一个 head：`0088_seo_image_alt_reviews`。共享分支在
  `0064_merge_geo_sem_heads`、`0072_merge_login_seo`、
  `0074_merge_geo_seo_heads` 和 `0077_merge_sem_seo_heads` 汇合。
- 迁移从 `tenants`、`baidu_accounts` 开始，随后建立 SEM 报告、资产、告警、
  操作记录、用户与角色；后续迁移再建立 `tenant_modules` 及 SEO/GEO 表。
- `roles` 由 `0016_custom_roles` 创建并写入系统角色。后续多个迁移更新这些角色的
  权限。空库迁移后会有系统角色行，即使尚无租户和用户。
- `0066_module_workspaces` 依赖已存在的 `tenants`、`roles`、SEO/GEO 来源表，并会
  为已有租户回填模块。空库中这些回填查询没有业务行可处理。
- 若未来装载可登录演示用户，顺序至少为：系统角色已迁移完成 → 演示租户 →
  `tenant_modules(sem)` → 可读取的演示账户/适配层 → 资产和报告 → 演示用户。
  `users.role_id` 与 `users.tenant_id` 都有外键。
- `sem_tasks` 不能随当前 head 假定存在。应由数据库负责人决定把已评审迁移纳入
  演示库迁移链，或首版不装载/不开放任务接口；不得由 loader 私自建表。
- 所有迁移只能由面向空演示库的独立流程执行。现有生产发布流程明确不运行迁移，
  不能复用为演示库初始化器。

## SEM 运行时关闭审计

当前可直接设置的安全配置如下：

| 配置 | 演示值 | 现有作用 | 是否足够 |
| --- | --- | --- | --- |
| `APP_ENV` | `demo` | 标识环境；避免套用生产配置判断 | 否，当前不关闭动作 |
| `DATABASE_URL` | 仅独立演示库 | 隔离全部持久化数据 | 必要，但仍需 loader/启动校验 |
| `SEM_TASKS_ENABLED` | `false` | 任务 API 返回 503，不查询 `sem_tasks` | 是，适用于任务接口 |
| `BAIDU_WRITE_DRY_RUN` | `true` | 百度写回按 dry-run 处理 | 否，dry-run 仍可能写本地台账 |
| `BAIDU_LIVE_WRITE_GRANTS` | 空 | 不授予真实写作用域 | 是，作为第二道写回保护 |
| `BAIDU_LIVE_WRITE_TENANT_IDS` | 空 | 旧版真实写租户白名单为空 | 是，兼容保护 |
| `BAIDU_LIVE_WRITE_ACCOUNT_IDS` | 空 | 旧版真实写账户白名单为空 | 是，兼容保护 |
| `BAIDU_LIVE_WRITE_SCOPES` | 空 | 旧版真实写动作白名单为空 | 是，兼容保护 |
| `BAIDU_LEGACY_SPLIT_CONFIRMATION_ENABLED` | `true` | 强制旧兼容路径保持 dry-run | 是，作为第二道保护 |

当前缺少以下总开关，因此现有 SEM 服务入口不能作为合格的 demo runtime 启动：

| 建议新增配置 | 演示值 | 必须控制的代码位置 |
| --- | --- | --- |
| `SEM_SCHEDULER_ENABLED` | `false` | `app.main.lifespan` 不得调用 `start_scheduler()`；关闭全部六个 SEM APScheduler job |
| `SEM_BAIDU_CLIENT_ENABLED` | `false` | `app.baidu.client` 及 OAuth/刷新/同步入口在构造客户端前返回稳定的 403/503 |
| `SEM_EXTERNAL_ACTIONS_ENABLED` | `false` | 所有手动同步、OAuth、规划器和外部探测入口统一失败关闭 |
| `SEM_WRITE_ENDPOINTS_ENABLED` | `false` | 百度 dry-run、本地台账、审批消费、业务状态变更接口均在业务处理前拒绝 |

必须同时满足以下部署约束：

- demo 服务不运行单独 scheduler 或 worker 进程；不能只依赖账户 `status` 过滤。
- 百度 App ID、Secret、self token、OAuth grant 和 refresh token 不提供给 demo 服务。
  由于当前 `Settings` 仍要求部分百度字段，后续代码应允许 demo runtime 使用空值，
  并由上面的客户端总开关在任何网络对象创建前拒绝。不得用貌似真实的占位凭据。
- DeepSeek 等模型密钥也不提供。首期数据只能读取夹具中已有结果。
- `CORS_ALLOWED_ORIGINS` 与 `APP_BASE_URL` 只指向演示入口；演示 JWT、管理 key、
  加密主密钥均与生产完全不同。
- 启动自检必须显示 `runtime=demo`、数据库名称和上述四个总开关状态，但不得记录
  URL 用户名、密码、token 或完整连接串。任一总开关缺失或为真，进程退出。

`SEO_RANK_SCHEDULER_ENABLED=false` 只影响 SEO 排名 job，不能关闭 SEM
`app.scheduler`。它不能作为 SEM 调度关闭证据。

## Loader 失败关闭草案

未来 loader 应是独立命令，不导入或启动 FastAPI lifespan、scheduler、百度客户端、
OAuth、规则引擎、模型客户端或写回模块。首个可执行版本仍需单独评审；PR 505 仅保留
离线 JSON 生成器。

loader 在创建数据库 engine 之前必须全部满足：

1. `APP_ENV` 精确等于 `demo`，并显式设置一次性开关
   `SEM_DEMO_LOADER_ENABLED=true`；默认值和缺失值都拒绝。
2. 连接串只接受 `postgresql+asyncpg`，只允许一个 TCP hostname；拒绝 Unix socket、
   IP literal、多 host、`localhost`、URL query 中的 `host` 覆盖和未知 query 参数。
3. URL hostname 必须精确等于由部署侧只读配置固定的 demo DB hostname；数据库名
   必须精确等于 `gsnipers_demo`。host 和 database name 不能由普通 loader CLI 参数
   临时改写，也不能只凭名称中包含 `demo` 就放行。
4. 要求 TLS 且校验证书主机名。数据库网络策略和账号权限必须保证该账号不能连接
   生产实例或生产数据库；应用校验不能替代这层隔离。
5. 建立连接后、开始事务前，分别查询并精确核对 `current_database()`、
   `current_user`、`inet_server_addr()` 和 Alembic head。任何空值、多个 head、版本不符
   或结果读取失败都拒绝。
6. 演示库必须有由基础设施流程创建的不可由 loader 伪造的环境标记，例如
   `runtime_identity(environment='demo', database_name='gsnipers_demo', fixture_loading_allowed=true)`。
   loader 只读校验标记，不负责创建或修改它。
7. 首次装载要求业务表为空，或只存在同一 `fixture_key=gsnipers-sem-demo-v1` 的完整
   前一版本。发现其他租户、未知行、生产 UCID、生产账户或不匹配的 fixture key 即拒绝。
8. 对 fixture canonical SHA256、固定租户 ID、对象计数、外键顺序和允许表集合做本地
   校验。输入多出一个表或字段也拒绝，不做“尽量装载”。
9. 单个 `SERIALIZABLE` 事务内获取数据库级 advisory lock，并在写入前再次核对数据库
   身份标记。任一失败整体回滚；不允许部分提交。
10. loader 不生成 token、不创建 OAuth grant、不写生产审计系统、不访问网络服务。
    输出只含计数、fixture SHA、演示库非敏感标识和事务结果。

清理/恢复应优先采用演示数据库快照或整库重建。若后续确需行级重放，删除范围必须
同时命中固定 `tenant_id` 和 `fixture_key`，并在同一事务内执行；未解决当前多数业务表
没有 `fixture_key` 列的问题前，不实现行级 delete。

## 进入实现前的验收项

1. 数据库负责人确认独立实例/数据库、固定 hostname、`gsnipers_demo` 名称、最小权限
   账号、TLS 和网络隔离。
2. 选择 `sem_tasks`：正式纳入演示迁移链，或首版明确排除任务数据和任务接口。
3. 为无凭据 demo 账户确定独立表/只读适配，不放宽生产 `baidu_accounts` 的凭据约束。
4. 实现并测试四个 runtime 总开关，覆盖启动、所有手动入口和迟到后台任务。
5. 在全新、一次性 PostgreSQL 16 演示库运行迁移与只读 schema 快照核对；不得连接
   生产地址。
6. 单独评审 loader 的预检、事务、幂等、失败回滚和快照恢复后，才允许增加 apply。
