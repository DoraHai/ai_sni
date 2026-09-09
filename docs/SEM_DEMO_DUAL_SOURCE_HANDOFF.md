# SEM 独立演示库只读适配交接

## 边界

生产账号、角色、菜单权限、SEM 模块资格和服务端绑定都从 `sem_prod` 校验。只有配置在
`SEM_DEMO_PRINCIPAL_TENANT_IDS` 中的生产租户身份进入演示路由；这些身份缺少唯一有效绑定、
绑定表版本不符、演示库不可达或任一安全校验失败时返回 503，不回退读取生产业务数据。

客户端的 tenant、header 和 query 不能选择数据库。`tenant_id` 只用于验证请求仍属于已认证的
生产租户；服务端再用 `demo_tenant_bindings.demo_tenant_id` 进行内部查询。响应顶层
`tenant_id` 会恢复为生产租户 ID，避免暴露内部演示租户标识。

身份预检始终读取生产库，并依次完成登录身份、租户范围、RBAC、SEM 模块资格和 SEM 身份检查：

- `/api/v1/auth/me`
- `/api/v1/auth/modules`
- `/api/v1/auth/tenants?module=sem`

只有下列四个业务 GET 可以在服务端绑定生效后读取演示库：

- `/api/v1/dashboard/cockpit`
- `/api/v1/keywords/cockpit`
- `/api/v1/keywords/cockpit/{keyword_id}`
- `/api/v1/search-terms/cockpit`

`/dashboard/today`、分析报告、月报、导出、投放、同步、OAuth、AI、任务写入以及其他路由均被
服务端门禁拒绝。OAuth 回调在消费 state 前、外部调用前和持久化前复核绑定；scheduler 在账户
枚举及领取任务后复核；同步、规则、建议、健康检查和百度写回在每次外部调用前后、每个分块
写入及提交前再次复核。长调用期间若绑定变为 active，当前事务回滚并立即停止。

## 启用前提

启用配置必须一次性完整提供：

- `SEM_DEMO_DATA_SOURCE_ENABLED=true`
- `SEM_DEMO_PRINCIPAL_TENANT_IDS`：生产租户 ID 白名单
- `SEM_DEMO_BINDING_SCHEMA_REVISION=0098_demo_binding_no_truncate`
- `SEM_DEMO_DATABASE_URL`：独立演示库的 `postgresql+asyncpg` 只读账号 URL
- `SEM_DEMO_DATABASE_NAME`：预期的独立数据库名
- `SEM_DEMO_DATABASE_USER`：预期的专用只读数据库角色
- `SEM_DEMO_DATABASE_HOST_ALLOWLIST`：精确主机名列表，不支持通配符
- `SEM_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST`：数据库返回的精确服务器地址列表
- `SEM_DEMO_DATABASE_SCHEMA_REVISION=0098_demo_binding_no_truncate`
- `SEM_DEMO_DATASET_KEY`、`SEM_DEMO_DATASET_VERSION`：服务端核准的唯一数据集
- `SEM_DEMO_MANIFEST_SHA256`：夹具清单的 64 位小写十六进制 SHA-256

启动只校验配置闭合性，不连接数据库。每次演示读取先从 `sem_prod` 读取可信绑定，然后连接
演示库并设置 `REPEATABLE READ, READ ONLY` 事务。读取前会核验数据库名、`current_user`、服务器
地址、事务只读状态及唯一 schema revision。专用角色必须可登录，且不得拥有 superuser、
createdb、createrole、replication、bypassrls、schema CREATE、数据库 CREATE/TEMP，以及表或序列
写权限。`current_user` 必须等于 `session_user`；运行时递归检查 `pg_auth_members` 并以
`pg_has_role(..., 'MEMBER')` 交叉核验，专用角色不得继承或通过 `SET ROLE` 到任何成员角色，
包括 `NOINHERIT` 成员关系。

夹具加载器必须维护 `demo_control.fixture_registry`。运行时要求同一 SEM 演示租户恰有一条
`load_status=ready` 的记录，并精确匹配 dataset key/version、manifest SHA-256、固定 schema
revision、演示租户 ID，同时 `loaded_at` 与 `verified_at` 均非空。`tenant_modules` 中的数据集标记
仍会交叉核验，不能替代加载器登记表。演示百度账户必须全部为 `status=disabled`、
`auth_mode=demo`、`sync_status=disabled`；只读接口在服务端将这些账户映射为不暴露内部 ID 的稳定
别名，并按 disabled 状态纳入默认读取范围。

## 发布与数据准备的独立记录

本代码变更没有连接数据库、执行迁移、安装夹具、同步数据、部署或合并。正式启用仍需分别
完成并留痕：生产库部署 0098 binding 契约、创建最小权限演示库只读账号、安装已审核的 SEM
演示数据集及 `dataset_version` 标记、写入生产租户到演示租户的有效 binding、配置精确主机和
地址白名单，创建并填充加载器登记表，再配置数据集 key/version 与 manifest SHA-256。任何一项
未完成时，受保护演示身份会失败关闭。
