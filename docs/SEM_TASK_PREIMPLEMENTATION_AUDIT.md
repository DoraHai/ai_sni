# SemTask 实施前审计（revision 待定）

> 状态：Draft 评审材料。原 `0095_sem_tasks -> 0094_seo_qa_batches` 仅为旧候选，
> 已因发现未合流的 `0074_geo_ticket_assignment` 分支而暂停编号和父节点结论。
> 本文不授权合并、部署、数据库连接、迁移执行或功能启用。

## 1. 审计结论

当前 `SemTask` ORM、任务 API 和仓库中的候选 DDL 基本一致，表定义可以继续作为正式评审底稿。revision=`0095_sem_tasks` 和 down_revision=`0094_seo_qa_batches` 不能继续视为确定契约，因为跨模块审计发现 `0074_geo_ticket_assignment` 是 `0094` 祖先图未包含的另一分支。该 revision 为 `geo_action_tickets` 增加 `owner_name` 和 `due_date`，不能与 `0074_merge_geo_seo_heads` 混淆。

在生产 catalog 只读结果和统筹编号到达前：

1. 不修改、注册或执行任何迁移文件，也不锁定 SemTask 或 demo binding 的 revision 编号。
2. 将仓库 `0095_sem_tasks` 和历史交付包只视为 **SemTask DDL 候选**；其中 revision 元数据已不具备最终效力。
3. 暂按“先合流、再建 SemTask、再建 demo binding”准备测试参数，但不把预计编号写成实施事实。
4. 保留字段、约束、数据安全和使用点审计；这些内容不依赖最终 revision 编号。
5. 在签署最终 DDL 前决定是否增加 `(tenant_id, id)` 列表索引。现有两个索引覆盖带状态或动作类型过滤的列表，但不完整覆盖无过滤的租户任务 keyset 列表。

本轮生产状态依据数据库/服务器侧回传：`sem_prod.public.alembic_version` 为单行 `0094_seo_qa_batches`，`sem_tasks` 不存在。该信息不足以判断 GEO 两列是否已经以迁移外方式存在，也不足以决定从生产状态出发应执行还是只合流 `0074_geo_ticket_assignment`。本文没有连接或查询生产数据库。

## 2. 证据与可信度

| 证据 | 用途 | 边界 |
| --- | --- | --- |
| `app/models/sem_task.py` | 当前 ORM 字段、约束和索引基线 | 当前代码事实 |
| `app/api/sem_tasks.py` | 全部读写路径、状态转换和查询形状 | 当前代码事实 |
| `docs/migration_proposals/0095_sem_tasks.py` | 仓库候选 SemTask DDL | Draft；revision/down_revision 已暂停，不得注册 |
| `D:/SNIPERS国内版/sem-acceptance-results/sem-migration-bundle-local-0095/.../20260906_0095_sem_tasks.py` | 历史只读交付候选 | 非 Git checkout；仅读取和比对，未复制、导入或执行 |
| 锁定源码提交 `4e83611a...` | `0094` 候选祖先图 | 未包含 `0074_geo_ticket_assignment`；源码依据不等于生产历史执行证明 |
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

任务访问还依赖现有用户身份、租户、`monitor.dashboard`、`verify.adjustments` 和 `tenant_modules(sem)`。这些表是前置依赖，不由 SemTask 迁移修改。

### 3.2 非运行时引用

- `app/models/__init__.py` 导出模型；`Base.metadata` 可见该表，但应用不调用 `create_all` 安装生产 Schema。
- `app/api/customer_modules.py` 将 `sem_tasks` 放入身份修复排除范围。基线和完成证据含租户身份，不能随客户合并盲迁移。
- `scripts/build_sem_demo_fixture.py` 生成离线任务夹具并将 `sem_tasks` 放在租户之前清理。该脚本不安装表。
- `tests/test_sem_tasks.py` 验证权限、输入白名单、租户条件、行锁、软取消、完成幂等和 keyset 查询。
- `tests/test_sem_tasks_postgres.py` 在显式本地测试库中验证模型、审核 SQL 和迁移 Draft 三种 DDL 的约束与生命周期。
- `tests/test_sem_task_migration_proposal.py` 静态提取候选定义，不执行 Alembic。
- `tests/test_sem_task_migration_bundle.py` 和 `tests/test_sem_controlled_migration.py` 当前可在显式本地 PostgreSQL 中演练旧候选假设下的单步 `0094 -> 0095`、失败回滚和对象冲突；普通环境相关用例会跳过。发现 GEO 分支后，这些用例只能证明 SemTask DDL 的事务性，不能证明最终生产谱系。

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

1. 在最终 SemTask revision 和 ORM 同时增加 `ix_sem_tasks_tenant_id_id(tenant_id, id)`，并更新预检、源锁和测试；适合任务可能持续增长的正式使用。
2. 明确接受首期低数据量下的租户范围扫描加排序，并记录查询计划阈值；后续以新 revision 增加索引。

建议采用第一项。当前只提交审计，不修改 ORM 或迁移 Draft，以免在索引决策未经评审时改变已锁定候选。

## 5. Upgrade 与 downgrade 数据安全

`upgrade()` 只允许：

1. 创建空 `sem_tasks`、自增序列、PK、FK 和八个 CHECK；
2. 创建批准的索引；
3. 由 Alembic 将版本推进到统筹批准的 SemTask revision；迁移本身不得手工写版本表。

禁止回填、扫描或更新客户、SEM、SEO、GEO 业务行；禁止 `IF NOT EXISTS` 掩盖同名冲突；禁止 stamp；禁止在一个执行中重放 `0089`～`0094`。表、索引和版本更新必须处于同一事务，任何对象冲突、权限不足、锁超时或后置条件失败都整体回滚。

`downgrade()` 应继续在任何 DDL 前显式拒绝。任务包含不可重建的基线和完成证据，删除表不属于安全回滚。应用回滚方式是关闭 `SEM_TASKS_ENABLED` 并使用兼容最终 SemTask revision 的应用版本，保留表和数据。正式发布清单不得把数据库 downgrade 当作恢复步骤。

## 6. 待核验的跨分支谱系

已确认的部分祖先关系是：

```text
0076_oauth_rebind_intent
          \
           0077_merge_sem_seo_heads -> 0078 -> ... -> 0094_seo_qa_batches
          /
0075_seo_content_source_page

0074_geo_ticket_assignment   # 0094 未包含的另一分支
```

因此，“`0094` 已包含 SEM `0076`”仍成立，但“SemTask 可直接成为 `0094` 的下一 revision”不再成立。若统筹决定保留 `0074_geo_ticket_assignment` 的迁移祖先，预期图形应为：

```text
0094_seo_qa_batches -----------\
                                <merge revision, upgrade 无 DDL>
0074_geo_ticket_assignment ----/             |
                                              v
                                   <SemTask revision>
                                              |
                                              v
                                   <demo binding revision>
```

这是待 catalog 核验的候选拓扑，不是最终迁移计划。特别需要区分：

- merge revision 自身应无 DDL，但从生产 `0094` 升级到 merge head 时，Alembic 是否会先执行 `0074_geo_ticket_assignment`，取决于生产版本记录与该分支在最终源图中的状态。
- 若 `geo_action_tickets.owner_name/due_date` 已存在而版本表只记录 `0094`，直接遍历 GEO revision 可能产生列冲突；不得用 `IF NOT EXISTS` 或 stamp 掩盖，需先查明形成原因并由迁移负责人决定修复方式。
- 若两列不存在，最终演练需要证明 GEO DDL 与 merge 顺序正确，且不会重放其他已执行迁移。
- `0074_geo_ticket_assignment` 和 `0074_merge_geo_seo_heads` 是不同 revision，名称或数字接近不能作为同一祖先处理。

当前普通 checkout 的迁移目录到 `0088`，锁定 SEO 候选源到 `0094`，两者都不足以单独证明包含新发现的 GEO 分支。共享迁移负责人必须先形成包含所有保留分支的统一源图，再为 merge、SemTask 和 demo binding 分配最终编号。

生产 catalog 只读结果至少要回答：目标 GEO 两列及相关约束/索引是否存在、`alembic_version` 是否确为单行、是否存在其他版本表或 schema、实际 `geo_action_tickets` 结构是否匹配 `0074_geo_ticket_assignment`、所有候选对象是否有命名冲突。

无论最终采用统一仓库还是锁定源包，都必须重新以批准提交锁定每个历史文件摘要。历史源码摘要只能证明候选源完整，不能反向证明生产执行过相同字节。

## 7. 候选迁移可复用项与漂移项

### 7.1 可直接复用

- 13 个字段的类型、nullability 和时间默认值。
- BIGINT PK 及 `tenant_id` BIGINT RESTRICT FK。
- 八个 CHECK 约束及其名称。
- 状态和动作两个索引。
- 只新增空表、不回填业务数据的 upgrade。
- downgrade 在任何破坏性动作前拒绝。

历史交付候选与仓库 Draft 在这些 DDL 内容上逐行一致。revision、down_revision、文件名、源锁中的 start/target 和旧的单步计划均不可直接复用。

### 7.2 需处理的漂移

| 项目 | 当前状态 | 最终建议 |
| --- | --- | --- |
| 生产 revision 描述 | `SEM_TASK_IMPLEMENTATION.md` 和 `SEM_TASK_SCHEMA_REVIEW.sql` 仍写旧的 `0093` 现场信息 | 以本审计记录的外部确认 `0094` 为新基线；旧文保留为历史证据，不再作为执行前事实 |
| 新发现 GEO 分支 | `0074_geo_ticket_assignment` 不在 0094 祖先图 | 等待 catalog 后先确定无 DDL merge 方案及编号 |
| 候选 revision 元数据 | Draft 固定 `0095 -> 0094` | 暂停；最终 SemTask 必须接在获批 merge 后并重新编号 |
| 普通迁移目录 | 当前 head `0088`，没有完整生产父图 | 不注册 SemTask；先统一包含 SEO 与 GEO 分支的谱系 |
| 默认列表索引 | 两个现有索引未完整覆盖 `(tenant_id, id DESC)` | 优先在最终 Draft 与 ORM 增加第三个索引 |
| FK 名称 | 当前候选未显式命名 | 正式 DDL 建议命名并同步结构测试 |
| 字节摘要 | 历史交付与工作区因换行不同而摘要不同 | 以最终 Git blob 重新锁定，禁止凭逐行相同复用旧摘要 |
| 空库验证 | 已有演练从最小模拟 `0094` 开始 | 增加最终统一图从空库升级到最终 head |
| 生产副本验证 | 未在本轮执行 | 只在批准的脱敏恢复副本中执行，不直接拿生产试迁移 |

## 8. 测试矩阵

### 8.1 静态和离线契约

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| S1 | 最终源图解析 | revision 无重复/缺父，唯一 head 为统筹批准的最终节点 |
| S2 | 分支合流计划 | 从生产 catalog 基线只执行获批的缺失 GEO revision（若需要）、无 DDL merge、SemTask 和后续 demo binding；无其他历史重放、stamp 或 downgrade |
| S3 | ORM/迁移逐字段对照 | 类型、长度、nullability、默认、FK、CHECK、索引完全一致；任何差异失败 |
| S4 | 文件完整性 | 最终迁移及历史源使用审核提交的 Git blob SHA-256；额外/缺失/符号链接失败 |
| S5 | 调用点契约 | create/list/detail/patch/cancel/verify 所需列与索引均在规格中 |
| S6 | downgrade | 调用立即拒绝，未发出 DROP/ALTER/版本回退 |

### 8.2 空 PostgreSQL 16 数据库

该矩阵用于新的 `gsnipers_demo` 或其他全新数据库，必须使用最终统一迁移源从 base 完整升级，不能先手工创建最小结构或 stamp 到某个中间 revision。

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| E1 | 空 `public` 升级到最终 head | 包含 GEO 分支合流、SemTask 和 demo binding 的全部批准迁移成功，版本表只含最终 head |
| E2 | SemTask 结构对账 | 13 列、PK、序列、FK、八个 CHECK 和批准索引完全匹配 |
| E3 | 空表与既有模块结构 | `sem_tasks` 行数为 0；SEM 0076、SEO 0094 和 GEO ticket assignment 结构均完整 |
| E4 | 任务生命周期 | 创建、列表、详情、PATCH、软取消、并发 verify 和完成幂等通过 |
| E5 | 约束负例 | 非法模块/动作/状态/角色、非对象 JSON、完成态无证据、非完成态有证据均失败 |
| E6 | BIGINT 边界 | 32 位以上、JavaScript 安全整数以上和 `2^63-1` 租户 ID 行为明确 |
| E7 | FK 删除 | 有任务的租户删除被 RESTRICT；删除失败后任务保留 |
| E8 | 功能默认关闭 | `SEM_TASKS_ENABLED=false` 时任务 API 返回 503，不访问表 |
| E9 | SemTask downgrade 拒绝 | 表和数据保持不变，版本不被回退到 SemTask 之前 |

### 8.3 现有 `sem_prod` catalog 基线的脱敏恢复副本

执行前先取得批准的备份或 PITR 恢复副本。本文不授权读取生产客户行或运行迁移。

| 编号 | 场景 | 通过条件 |
| --- | --- | --- |
| P0 | 只读预检 | 核对版本表全部行、GEO 两列、`tenants.id`、SemTask 与 demo binding 目标对象及所有命名冲突 |
| P1 | 完整结构基线 | 现存表、列、约束、索引、所有者和必要权限生成可复核摘要 |
| P2 | 精确升级 | 实际 Alembic 计划只包含 catalog 证明缺失且已批准的 GEO/merge/SemTask/demo binding revisions；版本到最终唯一 head |
| P3 | 数据保全 | 升级前后既有 SEM/SEO/身份表行数及批准的结构摘要不变；`sem_tasks` 为空 |
| P4 | 事务故障注入 | 建表后、建索引前失败时，表、序列、索引和版本更新全部回滚 |
| P5 | 对象冲突 | 预先存在同名表/序列/索引/约束时拒绝，不使用 `IF NOT EXISTS`，既有对象不被接管 |
| P6 | revision 异常 | 与批准 catalog 基线不一致、未知 head、意外多分支或已在目标时，受控入口拒绝重复/越级执行 |
| P7 | 权限和锁 | 缺 CREATE/REFERENCES/序列权限或锁超时时整体回滚，错误不泄漏凭据 |
| P8 | FK 与租户数据 | 对副本中新建的测试租户验证 RESTRICT；不修改真实恢复行 |
| P9 | 应用兼容 | 先以开关关闭的兼容应用验证当前 catalog 基线与最终 head，再在独立环境启用任务接口 |
| P10 | 回退演练 | 应用回退后保留 SemTask 表和证据，任务开关关闭；不执行数据库 downgrade |

### 8.4 正式执行前门禁

- 生产只读预检结果必须在执行窗口重新取得，不能沿用本轮回传代替临执行状态。
- 共享迁移负责人和 SEM/SEO 兼容性负责人签署最终源图、DDL、索引决策和结构摘要。
- 确认备份/PITR、恢复演练、暂停并发迁移/发布、执行角色、TLS、锁超时和退出条件。
- 先发布接受当前 catalog 基线与最终 head 的兼容应用；迁移、应用重启和 `SEM_TASKS_ENABLED` 启用分别授权。
- 普通发布继续 `migration=not-run`。演示库装载、正式库迁移和功能启用不能合并成一个隐式步骤。

## 9. 最终建议

保留当前 `docs/migration_proposals/0095_sem_tasks.py` 作为未注册的 **DDL 历史候选**，不直接复制历史交付文件；它的 revision 元数据、文件名和源锁不进入最终执行包。等待生产 catalog 只读结果与统筹编号后，再生成新的 SemTask 迁移 Draft。

下一次 Schema 评审需要同时处理：GEO 分支的实际落库状态、无 DDL merge 的父节点、SemTask 和 demo binding 的顺序与编号、租户外键命名，以及 `(tenant_id, id)` 索引。所有决定完成后再同步 ORM、预检、受控入口和测试并生成新摘要。

在最终统一图的完整空库升级和生产脱敏恢复副本矩阵都通过前，保持任务开关关闭；不把旧的 `0094 -> 0095` 最小 fixture 演练或历史交付包视为生产谱系或执行许可。
