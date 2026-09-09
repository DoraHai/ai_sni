# SemTask 0095 实施前审计

> 状态：Draft 评审材料。本文不授权合并、部署、数据库连接、迁移执行或功能启用。

## 1. 审计结论

当前 `SemTask` ORM、任务 API 和仓库中的候选迁移 `docs/migration_proposals/0095_sem_tasks.py` 基本一致。候选迁移可以继续作为正式评审底稿，但在注册进统一生产迁移源之前，必须完成以下事项：

1. 将 `0095_sem_tasks` 作为生产单行 head `0094_seo_qa_batches` 的直接子节点；不得从 SEM 应用树的 `0076_oauth_rebind_intent` 另起分支，也不得重新执行、stamp 或改写 `0077`～`0094`。
2. 由共享迁移负责人确认包含生产 `0094` 完整祖先图的唯一迁移源。当前 checkout 的普通 `migrations/versions` 只到 `0088`，不能单独承载生产 `0094 -> 0095`。
3. 在签署最终 DDL 前决定是否增加 `(tenant_id, id)` 列表索引。现有两个索引覆盖带状态或动作类型过滤的列表，但不完整覆盖无过滤的租户任务 keyset 列表。
4. 在空 PostgreSQL 16 数据库和生产 `0094` 的脱敏恢复副本上分别完成升级矩阵。现有最小结构演练不能替代完整历史升级和生产结构副本验证。

本轮生产状态依据数据库/服务器侧回传：`sem_prod.public.alembic_version` 为单行 `0094_seo_qa_batches`，`sem_tasks` 不存在。本文没有连接或查询生产数据库。

## 2. 证据与可信度

| 证据 | 用途 | 边界 |
| --- | --- | --- |
| `app/models/sem_task.py` | 当前 ORM 字段、约束和索引基线 | 当前代码事实 |
| `app/api/sem_tasks.py` | 全部读写路径、状态转换和查询形状 | 当前代码事实 |
| `docs/migration_proposals/0095_sem_tasks.py` | 仓库候选 Alembic 迁移 | Draft，未注册进普通 script location |
| `D:/SNIPERS国内版/sem-acceptance-results/sem-migration-bundle-local-0095/.../20260906_0095_sem_tasks.py` | 历史只读交付候选 | 非 Git checkout；仅读取和比对，未复制、导入或执行 |
| 锁定源码提交 `4e83611a...` | `0094` 候选祖先图 | 源码依据不等于生产历史执行证明 |
| 数据库/服务器侧本轮回传 | 生产当前 revision 和目标对象不存在 | 外部确认，非本任务独立测量 |

历史交付候选 SHA-256 为 `e3fba9e91dc09500943ecf4c7909ac6e17da84b56fabfa480530040387047e1d`；当前工作区 Draft 文件 SHA-256 为 `16ca75867a8655c4fdcf2647fbb90e25a40072bdb6ac6e6584686ab2c29039b6`。逐行比较无差异，摘要差异来自工作区换行编码，不能把两个字节摘要写成同一文件。正式迁移应以审核提交中的 Git blob 摘要重新锁定。

## 3. 全部使用点

### 3.1 运行时入口

| 位置 | 操作 | 对 Schema 的要求 |
| --- | --- | --- |
| `app/main.py` | 注册 `/api/v1/sem/tasks` router | 表不存在时必须保持 `SEM_TASKS_ENABLED=false` |
| `GET /api/v1/sem/tasks` | 按租户、可选状态/动作、`id < before_id`、`id DESC` 列表 | 租户隔离；keyset 排序；最多读取 101 行 |
| `GET /api/v1/sem/tasks/{id}` | `id + tenant_id` 查详情 | PK 定位并追加租户条件，跨租户返回 404 |
| `POST /api/v1/sem/tasks` | 写入任务和创建时指标快照 | 所有必填列；JSONB 对象；初始状态 `open` |
| `PATCH /api/v1/sem/tasks/{id}` | `FOR UPDATE` 后修改标题、角色或非终态状态 | 行锁；不允许客户端改目标、基线或直接完成 |
| `DELETE /api/v1/sem/tasks/{id}` | 软取消，保留记录 | 状态改为 `cancelled`，没有物理删除 |
| `POST /api/v1/sem/tasks/{id}/verify` | `FOR UPDATE`，写完成证据并置 `done` | 状态和完成证据必须在同一 UPDATE 中满足约束 |

任务访问还依赖现有用户身份、租户、`monitor.dashboard`、`verify.adjustments` 和 `tenant_modules(sem)`。这些表是前置依赖，不由 `0095` 修改。

### 3.2 非运行时引用

- `app/models/__init__.py` 导出模型；`Base.metadata` 可见该表，但应用不调用 `create_all` 安装生产 Schema。
- `app/api/customer_modules.py` 将 `sem_tasks` 放入身份修复排除范围。基线和完成证据含租户身份，不能随客户合并盲迁移。
- `scripts/build_sem_demo_fixture.py` 生成离线任务夹具并将 `sem_tasks` 放在租户之前清理。该脚本不安装表。
- `tests/test_sem_tasks.py` 验证权限、输入白名单、租户条件、行锁、软取消、完成幂等和 keyset 查询。
- `tests/test_sem_tasks_postgres.py` 在显式本地测试库中验证模型、审核 SQL 和迁移 Draft 三种 DDL 的约束与生命周期。
- `tests/test_sem_task_migration_proposal.py` 静态提取候选定义，不执行 Alembic。
- `tests/test_sem_task_migration_bundle.py` 和 `tests/test_sem_controlled_migration.py` 可在显式本地 PostgreSQL 中演练单步 `0094 -> 0095`、失败回滚和对象冲突；普通环境相关用例会跳过。

未发现其他生产代码直接读写 `SemTask`。没有后台 worker、调度器或真实广告执行路径依赖该表。

## 4. 正式 Schema 规格

### 4.1 表和字段

表名：`public.sem_tasks`。首次安装为空表，不回填历史业务数据。

| 字段 | PostgreSQL 类型 | Null | 默认/生成 | 使用语义 |
| --- | --- | --- | --- | --- |
| `id` | `BIGINT` | 否 | 自增序列；候选 DDL 生成 `sem_tasks_id_seq` | PK、详情定位、倒序 keyset 游标 |
| `tenant_id` | `BIGINT` | 否 | 无 | 每个查询和写入的租户范围 |
| `module` | `VARCHAR(8)` | 否 | 应用写 `sem`，无 server default | 固定模块标识 |
| `action_type` | `VARCHAR(64)` | 否 | 无 | 当前仅 `metric_target` |
| `title` | `VARCHAR(300)` | 否 | 无 | 创建和 PATCH 可改标题 |
| `params` | `JSONB` | 否 | 无 | 目标指标、方向和目标值；必须为对象 |
| `status` | `VARCHAR(20)` | 否 | 应用写 `open`，无 server default | `open/in_progress/done/cancelled` |
| `created_by` | `VARCHAR(80)` | 否 | 无 | 当前格式 `user:<id>`，保留创建者证据 |
| `assignee_role` | `VARCHAR(64)` | 否 | 无 | 当前仅 `operator/admin` |
| `baseline_snapshot` | `JSONB` | 否 | 无 | 创建时指标、范围、来源和观测时间；必须为对象 |
| `completion_evidence` | `JSONB` | 是 | `NULL` | 仅完成态存在；记录基线、结果、目标、核验者和时间 |
| `created_at` | `TIMESTAMPTZ` | 否 | `now()` | 创建时间 |
| `updated_at` | `TIMESTAMPTZ` | 否 | `now()` | 应用更新时显式刷新；server default 只负责插入 |

候选迁移没有给 `module` 和 `status` 设置数据库默认值，这与当前 ORM 行为一致：应用提供 Python 默认，直接 SQL 必须明确赋值。若后续要求数据库端写入，应另行修改模型和契约，不能只改迁移。

### 4.2 主键、外键和删除语义

- 主键：`sem_tasks_pkey(id)`。
- 外键：`tenant_id -> tenants.id ON DELETE RESTRICT`。存在任务时阻止物理删除租户，保留审计证据。
- 不对 `created_by` 建用户外键。该列保存不可随用户删除而消失的文本证据。
- 不对 `module` 建模块表外键。CHECK 将其固定为 `sem`，模块授权仍由请求时控制面校验。

正式迁移建议显式命名租户外键，例如 `fk_sem_tasks_tenant_id_tenants`，便于跨环境结构对账。当前 ORM 和两个 Draft 候选均未显式命名，这是 DDL 可维护性漂移，不影响 PostgreSQL 实际生成 FK。

### 4.3 CHECK 约束

| 名称 | 表达式 | 目的 |
| --- | --- | --- |
| `ck_sem_tasks_module` | `module = 'sem'` | 防止跨模块复用 |
| `ck_sem_tasks_action` | `action_type = 'metric_target'` | 限制首期动作类型 |
| `ck_sem_tasks_status` | 四种状态集合 | 拒绝未知状态 |
| `ck_sem_tasks_role` | `operator/admin` | 拒绝未知指派角色 |
| `ck_sem_tasks_params` | `jsonb_typeof(params) = 'object'` | 拒绝数组或标量参数 |
| `ck_sem_tasks_baseline` | `jsonb_typeof(baseline_snapshot) = 'object'` | 保证基线容器类型 |
| `ck_sem_tasks_evidence` | NULL 或 JSON object | 保证完成证据容器类型 |
| `ck_sem_tasks_done` | `done` 当且仅当证据非 NULL | 保证完成态和证据原子一致 |

数据库约束不验证 JSON 内部 Pydantic 结构、指标白名单或时间先后；这些由当前 API 验证。若未来有多版本任务 JSON，需先设计 schema version，不能收紧 CHECK 破坏已有审计数据。

### 4.4 索引

候选迁移与 ORM 当前均定义：

- `ix_sem_tasks_queue(tenant_id, status, id)`：覆盖租户+状态过滤并按 id 分页。
- `ix_sem_tasks_action(tenant_id, action_type, id)`：覆盖租户+动作过滤并按 id 分页。

详情依靠 `id` 主键；额外的 `tenant_id` 条件用于授权，不需要 `(id, tenant_id)` 重复索引。

无 `status/action_type` 的列表只有 `tenant_id` 和 `ORDER BY id DESC`。现有两个三列索引的中间列未受约束，不能保证直接提供全局 id 排序。最终签署前需二选一：

1. 在 `0095` 和 ORM 同时增加 `ix_sem_tasks_tenant_id_id(tenant_id, id)`，并更新预检、源锁和测试；适合任务可能持续增长的正式使用。
2. 明确接受首期低数据量下的租户范围扫描加排序，并记录查询计划阈值；后续以新 revision 增加索引。

建议采用第一项。当前只提交审计，不修改 ORM 或迁移 Draft，以免在索引决策未经评审时改变已锁定候选。

## 5. Upgrade 与 downgrade 数据安全

`upgrade()` 只允许：

1. 创建空 `sem_tasks`、自增序列、PK、FK 和八个 CHECK；
2. 创建批准的索引；
3. 将单行 `alembic_version` 从 `0094_seo_qa_batches` 更新到 `0095_sem_tasks`。

禁止回填、扫描或更新客户、SEM、SEO、GEO 业务行；禁止 `IF NOT EXISTS` 掩盖同名冲突；禁止 stamp；禁止在一个执行中重放 `0089`～`0094`。表、索引和版本更新必须处于同一事务，任何对象冲突、权限不足、锁超时或后置条件失败都整体回滚。

`downgrade()` 应继续在任何 DDL 前显式拒绝。任务包含不可重建的基线和完成证据，删除表不属于安全回滚。应用回滚方式是关闭 `SEM_TASKS_ENABLED` 并使用兼容 `0095` 的应用版本，保留表和数据。正式发布清单不得把 `alembic downgrade 0094` 当作恢复步骤。

## 6. 0094 之后的谱系方案

锁定源码中的祖先关系为：

```text
0076_oauth_rebind_intent
          \
           0077_merge_sem_seo_heads -> 0078 -> ... -> 0094_seo_qa_batches
          /
0075_seo_content_source_page
```

`0077_merge_sem_seo_heads` 的父节点包含 SEM `0076`，因此生产 `0094` 已在图语义上包含 SEM 0076。正确的新节点是：

```text
0094_seo_qa_batches -> 0095_sem_tasks
```

不应创建 `(0094, 0076)` merge：`0076` 已是 `0094` 的祖先，这会制造错误谱系。也不应把 `0095` 接到 `0076`：生产版本表在 `0094`，会产生新 head 并要求额外 merge。

当前普通 checkout 的迁移目录到 `0088`，而锁定候选源含 `0089`～`0094`。正式方案只有两种可接受路径：

- 共享迁移负责人将经过核验的完整生产谱系纳入统一迁移仓库，再注册 `0095`；或
- 继续采用独立、逐文件锁定的共享迁移源包，证明唯一 head 为 `0095` 且从生产 `0094` 的计划只包含一个 revision。

无论采用哪种方案，都必须重新以批准提交锁定每个历史文件摘要，并用只读生产结构对账证明当前单行 revision、必要父表/列/约束及目标对象不存在。历史源码摘要只能证明候选源完整，不能反向证明生产执行过相同字节。

## 7. 候选迁移可复用项与漂移项

### 7.1 可直接复用

- revision=`0095_sem_tasks`、down_revision=`0094_seo_qa_batches`。
- 13 个字段的类型、nullability 和时间默认值。
- BIGINT PK 及 `tenant_id` BIGINT RESTRICT FK。
- 八个 CHECK 约束及其名称。
- 状态和动作两个索引。
- 只新增空表、不回填业务数据的 upgrade。
- downgrade 在任何破坏性动作前拒绝。

历史交付候选与仓库 Draft 在这些内容上逐行一致。

### 7.2 需处理的漂移

| 项目 | 当前状态 | 最终建议 |
| --- | --- | --- |
| 生产 revision 描述 | `SEM_TASK_IMPLEMENTATION.md` 和 `SEM_TASK_SCHEMA_REVIEW.sql` 仍写旧的 `0093` 现场信息 | 以本审计记录的外部确认 `0094` 为新基线；旧文保留为历史证据，不再作为执行前事实 |
| 普通迁移目录 | 当前 head `0088`，没有 `0094` 父节点 | 不把 `0095` 直接放入该目录；先统一谱系或批准锁定源包 |
| 默认列表索引 | 两个现有索引未完整覆盖 `(tenant_id, id DESC)` | 优先在最终 Draft 与 ORM 增加第三个索引 |
| FK 名称 | 当前候选未显式命名 | 正式 DDL 建议命名并同步结构测试 |
| 字节摘要 | 历史交付与工作区因换行不同而摘要不同 | 以最终 Git blob 重新锁定，禁止凭逐行相同复用旧摘要 |
| 空库验证 | 已有演练从最小模拟 `0094` 开始 | 增加完整统一图从空库升级到 `0095` |
| 生产副本验证 | 未在本轮执行 | 只在批准的脱敏恢复副本中执行，不直接拿生产试迁移 |

## 8. 测试矩阵

### 8.1 静态和离线契约

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| S1 | 最终源图解析 | revision 无重复/缺父，唯一 head=`0095_sem_tasks` |
| S2 | `0094 -> 0095` 计划 | 计划仅含 `0095`，无历史重放、stamp 或 downgrade |
| S3 | ORM/迁移逐字段对照 | 类型、长度、nullability、默认、FK、CHECK、索引完全一致；任何差异失败 |
| S4 | 文件完整性 | 最终迁移及历史源使用审核提交的 Git blob SHA-256；额外/缺失/符号链接失败 |
| S5 | 调用点契约 | create/list/detail/patch/cancel/verify 所需列与索引均在规格中 |
| S6 | downgrade | 调用立即拒绝，未发出 DROP/ALTER/版本回退 |

### 8.2 空 PostgreSQL 16 数据库

该矩阵用于新的 `gsnipers_demo` 或其他全新数据库，必须使用最终统一迁移源从 base 完整升级，不能先手工创建最小结构或 stamp 到 `0094`。

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| E1 | 空 `public` 执行 `upgrade 0095` | 全部历史迁移成功，版本表单行 `0095`，无额外 head |
| E2 | SemTask 结构对账 | 13 列、PK、序列、FK、八个 CHECK 和批准索引完全匹配 |
| E3 | 空表与既有模块结构 | `sem_tasks` 行数为 0；SEM 0076 字段仍存在；SEO 0094 对象完整 |
| E4 | 任务生命周期 | 创建、列表、详情、PATCH、软取消、并发 verify 和完成幂等通过 |
| E5 | 约束负例 | 非法模块/动作/状态/角色、非对象 JSON、完成态无证据、非完成态有证据均失败 |
| E6 | BIGINT 边界 | 32 位以上、JavaScript 安全整数以上和 `2^63-1` 租户 ID 行为明确 |
| E7 | FK 删除 | 有任务的租户删除被 RESTRICT；删除失败后任务保留 |
| E8 | 功能默认关闭 | `SEM_TASKS_ENABLED=false` 时任务 API 返回 503，不访问表 |
| E9 | downgrade 拒绝 | 表、数据和版本均保持 `0095` |

### 8.3 现有 `sem_prod@0094` 的脱敏恢复副本

执行前先取得批准的备份或 PITR 恢复副本。本文不授权读取生产客户行或运行迁移。

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| P0 | 只读预检 | 单一版本 `0094`；`tenants.id` 为 BIGINT；目标表/序列/索引/约束名均不存在 |
| P1 | 完整结构基线 | 现存表、列、约束、索引、所有者和必要权限生成可复核摘要 |
| P2 | 单步升级 | 实际 Alembic 计划和执行只包含 `0095`；版本变为单行 `0095` |
| P3 | 数据保全 | 升级前后既有 SEM/SEO/身份表行数及批准的结构摘要不变；`sem_tasks` 为空 |
| P4 | 事务故障注入 | 建表后、建索引前失败时，表、序列、索引和版本更新全部回滚 |
| P5 | 对象冲突 | 预先存在同名表/序列/索引/约束时拒绝，不使用 `IF NOT EXISTS`，既有对象不被接管 |
| P6 | revision 异常 | 空、多行、未知、`0093` 或已是 `0095` 时受控入口拒绝重复/越级执行 |
| P7 | 权限和锁 | 缺 CREATE/REFERENCES/序列权限或锁超时时整体回滚，错误不泄漏凭据 |
| P8 | FK 与租户数据 | 对副本中新建的测试租户验证 RESTRICT；不修改真实恢复行 |
| P9 | 应用兼容 | 先以开关关闭的兼容应用验证 `0094/0095` 健康策略，再在独立环境启用任务接口 |
| P10 | 回退演练 | 应用回退后保持 `0095` 表和证据，任务开关关闭；不执行数据库 downgrade |

### 8.4 正式执行前门禁

- 生产只读预检结果必须在执行窗口重新取得，不能沿用本轮回传代替临执行状态。
- 共享迁移负责人和 SEM/SEO 兼容性负责人签署最终源图、DDL、索引决策和结构摘要。
- 确认备份/PITR、恢复演练、暂停并发迁移/发布、执行角色、TLS、锁超时和退出条件。
- 先发布接受 `0094` 与 `0095` 的兼容应用；迁移、应用重启和 `SEM_TASKS_ENABLED` 启用分别授权。
- 普通发布继续 `migration=not-run`。演示库装载、正式库迁移和功能启用不能合并成一个隐式步骤。

## 9. 最终建议

保留当前 `docs/migration_proposals/0095_sem_tasks.py` 作为未注册 Draft，不直接复制历史交付文件。下一次 Schema 评审只处理两个显式变更决策：为租户外键命名，以及增加 `(tenant_id, id)` 索引并同步 ORM、预检和测试。决定后生成新的审核提交和摘要。

谱系上采用 `0094_seo_qa_batches -> 0095_sem_tasks` 单步方案。SEM 0076 已通过 `0077_merge_sem_seo_heads` 进入 0094 祖先，不需要另建 SEM 分支。正式注册前必须先解决当前 checkout 缺少生产 0089～0094 的迁移源治理问题。

在完整空库升级和 `sem_prod@0094` 脱敏恢复副本矩阵都通过前，保持任务开关关闭；不把既有最小 fixture 演练或历史交付包视为生产执行许可。
